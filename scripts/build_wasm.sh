#!/usr/bin/env bash
# Score Four エンジンを WASM にビルドして web/ へ配置する。
# 依存: rustup target add wasm32-unknown-unknown （wasm-bindgen は不要、素の C-ABI）。
set -euo pipefail
cd "$(dirname "$0")/.."
rustup target add wasm32-unknown-unknown >/dev/null 2>&1 || true
cargo build --release --manifest-path rust/Cargo.toml \
  --target wasm32-unknown-unknown --no-default-features --features wasm
mkdir -p web
cp rust/target/wasm32-unknown-unknown/release/score_four_rs.wasm web/engine.wasm
echo "built web/engine.wasm ($(wc -c < web/engine.wasm) bytes)"
