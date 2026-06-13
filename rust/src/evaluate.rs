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

/// 占有数 k(=0..3) のライン価値。
const WEIGHT: [i64; 4] = [0, 1, 5, 25];

/// 検証済みパリティ重み。
pub const PARITY: i64 = -8;

pub const MODE_ALL: u8 = 0;
pub const MODE_LOWEST: u8 = 1;
pub const MODE_REACHABLE: u8 = 2;

/// 評価のパラメータ。トーナメントで候補を切り替えるために使う。
#[derive(Clone, Copy)]
pub struct EvalConfig {
    pub parity_weight: i64,
    pub immediate: i64,
    pub parity_mode: u8,
}

impl EvalConfig {
    /// 既定 (検証済み): ALL / weight -8 / 即時脅威なし。
    pub fn default_config() -> Self {
        EvalConfig {
            parity_weight: PARITY,
            immediate: 0,
            parity_mode: MODE_ALL,
        }
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

/// 設定 cfg に基づく手番側視点の評価。
pub fn eval_with(board: &Board, cfg: &EvalConfig) -> i64 {
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
        score += sign * WEIGHT[count];

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
            immediate: 0,
            parity_mode: MODE_ALL,
        },
    )
}

/// 探索が既定で使う評価 (検証済みパリティ付き)。
pub fn default_eval(board: &Board) -> i64 {
    eval_with(board, &EvalConfig::default_config())
}
