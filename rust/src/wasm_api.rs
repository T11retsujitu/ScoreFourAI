//! WASM / C-ABI バインディング。`wasm-bindgen` を使わず素の `extern "C"` で公開し、
//! JS から `WebAssembly.instantiate` で直接呼ぶ (追加ツール不要)。
//!
//! ビットボード b0(先手)/b1(後手) は u64。JS からは BigInt で渡す。**時間制御は使わない**
//! (wasm32-unknown-unknown では `std::time::Instant` が使えないため)。固定深さ探索のみ。
//! 探索結果は sf_search が原子変数に格納し、sf_score / sf_move で取り出す。

use std::sync::atomic::{AtomicI32, AtomicI64, Ordering};

use crate::board::Board;
use crate::evaluate::{eval_with, EvalConfig};
use crate::search;

static R_SCORE: AtomicI64 = AtomicI64::new(0);
static R_MOVE: AtomicI32 = AtomicI32::new(-1);

/// 既定評価・固定深さ depth で探索し、結果を格納する (手番側視点の score と最善柱)。
///
/// # Safety
/// 純粋な数値計算のみ。ポインタは扱わない。`extern "C"` は wasm 公開のためのもの。
#[no_mangle]
pub extern "C" fn sf_search(b0: u64, b1: u64, depth: u32) {
    let (score, mv) = search::search_position(b0, b1, depth as u8, None);
    R_SCORE.store(score, Ordering::Relaxed);
    R_MOVE.store(mv, Ordering::Relaxed);
}

/// 直前の sf_search のスコア (手番側視点)。
#[no_mangle]
pub extern "C" fn sf_score() -> i64 {
    R_SCORE.load(Ordering::Relaxed)
}

/// 直前の sf_search の最善柱 (0..15) / 無ければ -1。
#[no_mangle]
pub extern "C" fn sf_move() -> i32 {
    R_MOVE.load(Ordering::Relaxed)
}

/// 局面 (b0,b1) の既定評価値 (手番側視点)。探索せず静的評価のみ。
#[no_mangle]
pub extern "C" fn sf_eval(b0: u64, b1: u64) -> i64 {
    eval_with(
        &Board::from_bitboards(b0, b1),
        &EvalConfig::default_config(),
    )
}
