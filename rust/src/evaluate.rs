//! 評価関数 (evaluate.py の Rust 移植 + 実験用の精緻化)。すべて D4 対称不変。
//!
//! 既定 default_eval = eval_with(parity_weight=-8, immediate=0, mode=ALL)。多シード
//! 自己対戦で検証済み (docs/eval_measurements.md)。Python の default_eval と同値。
//!
//! パリティモード (実験): どの open-3 脅威を偶奇カウントに含めるか。z(高さ)は D4 で
//! 不変なので、いずれのモードも D4 対称不変。
//!   ALL      : 全 open-3 脅威 (現行の既定)。
//!   REACHABLE: 完成セルが今すぐ着手できる脅威のみ。
//!   LOWEST   : 各プレイヤーの最下段 (最小 z) の脅威のみ (Connect Four 流)。

use crate::board::{line_masks, Board};

/// 検証済みパリティ重み。
pub const PARITY: i64 = -8;

pub const MODE_ALL: u8 = 0;
pub const MODE_LOWEST: u8 = 1;
pub const MODE_REACHABLE: u8 = 2;

/// 学習評価 (Phase 8) の D4 不変・整数特徴量の本数。
/// 並び: [open1, open2, open3, parity, reach3, center] の先手-後手差。
pub const NF: usize = 6;

/// 中央 2x2 柱 (x,y ∈ {1,2} = 柱 5,6,9,10) の全高さセルのマスク。
/// D4 はこの 4 柱の集合を保つので center 占有数は D4 不変。
const fn center_mask() -> u64 {
    let cols = [5u64, 6, 9, 10];
    let mut m = 0u64;
    let mut z = 0u64;
    while z < 4 {
        let mut i = 0;
        while i < 4 {
            m |= 1u64 << (z * 16 + cols[i]);
            i += 1;
        }
        z += 1;
    }
    m
}
const CENTER_MASK: u64 = center_mask();

/// 評価のパラメータ。トーナメントで候補を切り替えるために使う。
#[derive(Clone, Copy)]
pub struct EvalConfig {
    pub parity_weight: i64,
    pub immediate: i64,
    pub parity_mode: u8,
    /// 占有数 1/2/3 の基本ライン価値 (count=0 は常に 0)。既定 [1, 5, 25]。
    pub weights: [i64; 3],
    /// 学習評価モード (Phase 8)。0 = 手書きパリティ式 (既定); !=0 = 線形学習評価 `lw·features`。
    pub learned: u8,
    /// 学習線形重み (量子化整数)。learned!=0 のとき features との内積を取る。
    pub lw: [i64; NF],
}

impl EvalConfig {
    /// 既定 (検証済み): ALL / weight -8 / 即時脅威なし / 基本重み 1,5,25。学習評価オフ。
    pub fn default_config() -> Self {
        EvalConfig {
            parity_weight: PARITY,
            immediate: 0,
            parity_mode: MODE_ALL,
            weights: [1, 5, 25],
            learned: 0,
            lw: [0; NF],
        }
    }

    /// 学習線形重み lw を使う評価設定 (Phase 8 の A/B 計測用)。
    pub fn learned_config(lw: [i64; NF]) -> Self {
        EvalConfig {
            learned: 1,
            lw,
            ..EvalConfig::default_config()
        }
    }
}

/// D4 不変な整数特徴量 (先手0 視点の先手-後手差) を返す。
///
/// すべて整数・1 回のライン走査 + center popcount で計算するため決定的。z(高さ)は D4 で
/// 不変、柱集合 {5,6,9,10} は D4 で保たれるので全特徴量が D4 対称不変。並びは:
///   0 open1   : 占有1のライン数
///   1 open2   : 占有2のライン数
///   2 open3   : 占有3 (未完成3並び) のライン数
///   3 parity  : open3 の完成セル z が奇数=+1/偶数=-1 の総和 (既存パリティ項)
///   4 reach3  : open3 のうち完成セルが今すぐ着手可能なライン数
///   5 center  : 中央 2x2 柱の占有駒数
pub fn features(board: &Board) -> [i64; NF] {
    let (p0, p1) = (board.bb[0], board.bb[1]);
    let heights = &board.heights;
    let mut f = [0i64; NF];

    for &mask in line_masks() {
        let a = p0 & mask;
        let b = p1 & mask;
        let (occ, sign): (u64, i64) = if a != 0 {
            if b != 0 {
                continue; // 両者混在 = 死んだライン
            }
            (a, 1)
        } else if b != 0 {
            (b, -1)
        } else {
            continue;
        };
        match occ.count_ones() {
            1 => f[0] += sign,
            2 => f[1] += sign,
            3 => {
                f[2] += sign;
                let e = (mask ^ occ).trailing_zeros() as usize; // 残り1マス
                let z = (e >> 4) as u8;
                f[3] += sign * parity_bit(z);
                if z == heights[e & 15] {
                    f[4] += sign;
                }
            }
            _ => {}
        }
    }
    f[5] = (p0 & CENTER_MASK).count_ones() as i64 - (p1 & CENTER_MASK).count_ones() as i64;
    f
}

/// 学習線形重み lw による手番側視点の評価 (整数内積)。D4 不変・決定的。
pub fn eval_learned(board: &Board, lw: &[i64; NF]) -> i64 {
    let f = features(board);
    let mut score = 0i64;
    for i in 0..NF {
        score += lw[i] * f[i];
    }
    if board.turn == 0 {
        score
    } else {
        -score
    }
}

#[inline]
fn parity_bit(z: u8) -> i64 {
    if z & 1 == 1 {
        1
    } else {
        -1
    }
}

#[inline]
fn line_weight(cfg: &EvalConfig, count: usize) -> i64 {
    // count: 1..3 (0 と 4 は呼ばれない)。
    cfg.weights[count - 1]
}

/// 設定 cfg に基づく手番側視点の評価。
pub fn eval_with(board: &Board, cfg: &EvalConfig) -> i64 {
    if cfg.learned != 0 {
        return eval_learned(board, &cfg.lw);
    }
    let (p0, p1) = (board.bb[0], board.bb[1]);
    let heights = &board.heights;
    let mut score: i64 = 0;
    let mut parity: i64 = 0; // ALL / REACHABLE 用 (先手 - 後手)
    let mut min_z = [u8::MAX; 2]; // LOWEST 用: 各プレイヤーの最小 z 脅威

    for &mask in line_masks() {
        let a = p0 & mask;
        let b = p1 & mask;
        let (occ, player): (u64, usize) = if a != 0 {
            if b != 0 {
                continue; // 両者混在 = 死んだライン
            }
            (a, 0)
        } else if b != 0 {
            (b, 1)
        } else {
            continue;
        };

        let count = occ.count_ones() as usize;
        let sign: i64 = if player == 0 { 1 } else { -1 };
        score += sign * line_weight(cfg, count);

        if count == 3 {
            let e = (mask ^ occ).trailing_zeros() as usize; // 残り1マス
            let z = (e >> 4) as u8;
            if cfg.immediate != 0 && z == heights[e & 15] {
                score += sign * cfg.immediate;
            }
            match cfg.parity_mode {
                MODE_REACHABLE => {
                    if z == heights[e & 15] {
                        parity += sign * parity_bit(z);
                    }
                }
                MODE_LOWEST => {
                    if z < min_z[player] {
                        min_z[player] = z;
                    }
                }
                _ => {
                    parity += sign * parity_bit(z); // ALL
                }
            }
        }
    }

    let parity_total = if cfg.parity_mode == MODE_LOWEST {
        let mut t = 0i64;
        if min_z[0] != u8::MAX {
            t += parity_bit(min_z[0]);
        }
        if min_z[1] != u8::MAX {
            t -= parity_bit(min_z[1]);
        }
        t
    } else {
        parity
    };
    score += cfg.parity_weight * parity_total;

    if board.turn == 0 {
        score
    } else {
        -score
    }
}

/// ライン potential (脅威カウント) のみ。ベースライン参照用。
#[allow(dead_code)]
pub fn line_potential(board: &Board) -> i64 {
    eval_with(
        board,
        &EvalConfig {
            parity_weight: 0,
            ..EvalConfig::default_config()
        },
    )
}

/// 探索が既定で使う評価 (検証済みパリティ付き)。
pub fn default_eval(board: &Board) -> i64 {
    eval_with(board, &EvalConfig::default_config())
}
