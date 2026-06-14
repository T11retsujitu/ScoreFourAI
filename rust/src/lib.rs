//! Score Four エンジンの Rust 実装。
//!
//! コア (`board`/`lines`) + 探索 (`search`) + 評価 (`evaluate`) + D4対称性 (`symmetry`)
//! は純粋な Rust。バインディングは2系統あり、feature で切り替える:
//!   - `python` (既定): PyO3 拡張 `score_four_rs` (maturin でビルド、契約テスト用)。
//!   - `wasm`: 素の C-ABI 公開 (`wasm_api`)。ブラウザの WASM 対局アプリから呼ぶ。
//!
//! コア各モジュールは両系統で共有し、結果一致は契約テストで保証する。

// wasm ビルドは公開 API の一部しか使わないため、python 無効時の dead_code は許可する。
#![cfg_attr(not(feature = "python"), allow(dead_code))]

mod board;
mod evaluate;
mod lines;
mod search;
mod symmetry;

#[cfg(feature = "python")]
mod python_api;

// C-ABI 公開は pyo3 に依存しないので常に存在してよいが、wasm ビルド時のみ必要。
#[cfg(feature = "wasm")]
mod wasm_api;
