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

// 詰み探索 (Phase 7) の結果。PV は柱列を固定長配列に格納する (盤は 64 マス)。
static S_STATUS: AtomicI32 = AtomicI32::new(0);
static S_PLIES: AtomicI32 = AtomicI32::new(-1);
static S_MOVE: AtomicI32 = AtomicI32::new(-1);
static S_PV_LEN: AtomicI32 = AtomicI32::new(0);
static S_PV: [AtomicI32; 64] = [const { AtomicI32::new(-1) }; 64];

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

/// 詰み探索 (Phase 7)。max_plies 手以内の強制勝ち/負けを読み切り、結果を格納する。
/// status/plies/move/PV は sf_solve_status / _plies / _move / _pv_len / _pv で取り出す。
///
/// # Safety
/// 純粋な数値計算のみ。ポインタは扱わない。
#[no_mangle]
pub extern "C" fn sf_solve(b0: u64, b1: u64, max_plies: u32) {
    let r = search::solve(b0, b1, max_plies as u8);
    S_STATUS.store(r.status as i32, Ordering::Relaxed);
    S_PLIES.store(r.plies, Ordering::Relaxed);
    S_MOVE.store(r.best_move, Ordering::Relaxed);
    let n = r.pv.len().min(64);
    for (i, &c) in r.pv.iter().take(64).enumerate() {
        S_PV[i].store(c as i32, Ordering::Relaxed);
    }
    S_PV_LEN.store(n as i32, Ordering::Relaxed);
}

/// 直前の sf_solve のステータス (0=unknown, 1=win, 2=loss, 3=draw, 手番側視点)。
#[no_mangle]
pub extern "C" fn sf_solve_status() -> i32 {
    S_STATUS.load(Ordering::Relaxed)
}

/// 直前の sf_solve の詰み手数 (win/loss のみ意味あり、それ以外 -1)。
#[no_mangle]
pub extern "C" fn sf_solve_plies() -> i32 {
    S_PLIES.load(Ordering::Relaxed)
}

/// 直前の sf_solve の最善柱 (win=詰ます手 / loss=最長の受け / 無ければ -1)。
#[no_mangle]
pub extern "C" fn sf_solve_move() -> i32 {
    S_MOVE.load(Ordering::Relaxed)
}

/// 直前の sf_solve の PV (詰み手順) の長さ。
#[no_mangle]
pub extern "C" fn sf_solve_pv_len() -> i32 {
    S_PV_LEN.load(Ordering::Relaxed)
}

/// 直前の sf_solve の PV の i 番目の柱 (範囲外なら -1)。
#[no_mangle]
pub extern "C" fn sf_solve_pv(i: i32) -> i32 {
    if (0..64).contains(&i) {
        S_PV[i as usize].load(Ordering::Relaxed)
    } else {
        -1
    }
}
