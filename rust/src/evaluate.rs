//! 評価関数 (evaluate.py の Rust 移植)。すべて D4 対称不変。
//!
//! 既定 default_eval = parity_eval(weight=-8, immediate=0)。多シード自己対戦で
//! 検証済み (docs/eval_measurements.md)。Python 実装と同一の値を返す。

use crate::board::{line_masks, Board};

/// 占有数 k(=0..3) のライン価値。
const WEIGHT: [i64; 4] = [0, 1, 5, 25];

/// 検証済みパリティ重み。
pub const PARITY: i64 = -8;

/// ライン potential (脅威カウント) のみ。手番側視点。
/// ベースライン参照用 (既定は default_eval)。parity_eval(_,0,0) と一致する。
#[allow(dead_code)]
pub fn line_potential(board: &Board) -> i64 {
    let (p0, p1) = (board.bb[0], board.bb[1]);
    let mut score: i64 = 0;
    for &mask in line_masks() {
        let a = p0 & mask;
        let b = p1 & mask;
        if a != 0 {
            if b != 0 {
                continue;
            }
            score += WEIGHT[a.count_ones() as usize];
        } else if b != 0 {
            score -= WEIGHT[b.count_ones() as usize];
        }
    }
    if board.turn == 0 {
        score
    } else {
        -score
    }
}

/// パリティ評価 (任意で即時脅威加点)。parity_weight=0, immediate=0 で line_potential。
pub fn parity_eval(board: &Board, parity_weight: i64, immediate: i64) -> i64 {
    let (p0, p1) = (board.bb[0], board.bb[1]);
    let heights = &board.heights;
    let mut score: i64 = 0;
    let mut parity: i64 = 0; // 先手視点: (先手の奇-偶脅威) - (後手の奇-偶脅威)
    for &mask in line_masks() {
        let a = p0 & mask;
        let b = p1 & mask;
        if a != 0 {
            if b != 0 {
                continue;
            }
            let ca = a.count_ones() as usize;
            score += WEIGHT[ca];
            if ca == 3 {
                let e = (mask ^ a).trailing_zeros() as usize; // 残り1マス
                if immediate != 0 && (e >> 4) as u8 == heights[e & 15] {
                    score += immediate;
                }
                parity += if (e >> 4) & 1 == 1 { 1 } else { -1 };
            }
        } else if b != 0 {
            let cb = b.count_ones() as usize;
            score -= WEIGHT[cb];
            if cb == 3 {
                let e = (mask ^ b).trailing_zeros() as usize;
                if immediate != 0 && (e >> 4) as u8 == heights[e & 15] {
                    score -= immediate;
                }
                parity -= if (e >> 4) & 1 == 1 { 1 } else { -1 };
            }
        }
    }
    score += parity_weight * parity;
    if board.turn == 0 {
        score
    } else {
        -score
    }
}

/// 探索が既定で使う評価 (検証済みパリティ付き)。
pub fn default_eval(board: &Board) -> i64 {
    parity_eval(board, PARITY, 0)
}
