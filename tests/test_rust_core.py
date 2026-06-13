"""Rust コア (score_four_rs) と Python 参照の言語横断契約テスト (センサー先行)。

C++/Rust への移植でもコアの正しさが全ての土台、という原則 (CLAUDE.md) を守るため、
Rust の `RustBoard` が Python の `Board` と **全局面で完全一致** することを property
test で保証する。ランダム対局を多数回し、各手番で着手可能手・勝者・終局判定・
ビットボード・高さ・即勝ち柱が一致することを確認する。

拡張がビルドされていない環境では skip する (純 Python のスイートは独立に緑)。
ビルド: `cd rust && maturin build --release && pip install --force-reinstall \
        --no-deps target/wheels/score_four_rs-*.whl`
"""
import random

import pytest

from score_four.board import Board
from score_four.lines import all_lines

rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")


def test_rust_lines_match_python() -> None:
    rl = sorted(rs.lines())
    pl = sorted(tuple(line) for line in all_lines())
    assert len(rl) == 76
    assert rl == pl


def _assert_states_match(py: Board, rust) -> None:
    assert sorted(py.legal_moves()) == sorted(rust.legal_moves())
    assert py.winner == rust.winner
    assert py.is_terminal() == rust.is_terminal()
    assert py.is_full() == rust.is_full()
    assert py.num_moves == rust.num_moves
    assert (py.bb[0], py.bb[1]) == rust.bb()
    # Rust の Vec<u8> は PyO3 で bytes になるので list で揃えて比較。
    assert list(py.heights) == list(rust.heights())
    for player in (0, 1):
        assert sorted(py.winning_moves(player)) == sorted(rust.winning_moves(player))
        assert py.has_winning_move(player) == rust.has_winning_move(player)


def test_random_games_match_reference() -> None:
    """ランダム対局を多数回し、全局面で Python 参照と Rust が一致することを検証。"""
    saw_win = False
    for seed in range(300):
        rng = random.Random(seed)
        py = Board()
        rust = rs.RustBoard()
        while not py.is_terminal():
            _assert_states_match(py, rust)
            column = rng.choice(py.legal_moves())
            won_py = py.play(column)
            won_rust = rust.play(column)
            assert won_py == won_rust
        _assert_states_match(py, rust)
        if py.winner is not None:
            saw_win = True
    assert saw_win  # ランダム対局なので勝ち局面は必ず出る


def test_undo_matches_reference() -> None:
    """途中まで打って全手 undo すると、Python と Rust がともに初期局面へ戻る。"""
    for seed in range(60):
        rng = random.Random(5000 + seed)
        py = Board()
        rust = rs.RustBoard()
        played = 0
        while not py.is_terminal():
            column = rng.choice(py.legal_moves())
            py.play(column)
            rust.play(column)
            played += 1
        for _ in range(played):
            py.undo()
            rust.undo()
            _assert_states_match(py, rust)
        assert rust.bb() == (0, 0)
        assert rust.num_moves == 0
