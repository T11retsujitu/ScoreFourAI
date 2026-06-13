"""Rust 探索 (score_four_rs) と Python 探索の言語横断契約テスト (センサー先行)。

段階2: symmetry / evaluate / search を Rust 化した。Rust は Python と同一アルゴリズム・
同一着手順序・同一 TT 意味論・同一 PVS なので、各層が **完全一致** することを保証する:
  - canonical (D4 正規化キー)
  - eval_default (既定評価値)
  - negamax_value (全幅 negamax 値)
  - search の (score, best_move)

拡張未ビルドなら skip (純 Python のスイートは独立に緑)。
"""
import random

import pytest

from score_four.board import Board
from score_four.evaluate import default_eval
from score_four.search import INF
from score_four.search import negamax as py_negamax
from score_four.search import search as py_search
from score_four.symmetry import canonical as py_canonical

rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")


def _random_nonterminal(seed: int, count: int, max_plies: int) -> list[Board]:
    rng = random.Random(seed)
    boards: list[Board] = []
    for _ in range(count):
        b = Board()
        for _ in range(rng.randint(0, max_plies)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if not b.is_terminal():
            boards.append(b)
    return boards


def test_canonical_matches_python() -> None:
    for b in _random_nonterminal(1, 80, 30):
        assert rs.canonical(b.bb[0], b.bb[1]) == py_canonical(b.bb[0], b.bb[1])


def test_eval_default_matches_python() -> None:
    for b in _random_nonterminal(2, 80, 32):
        assert rs.eval_default(b.bb[0], b.bb[1]) == default_eval(b)


def test_negamax_value_matches_python() -> None:
    """全幅 negamax 値 (fresh TT) が depth 1..5 で一致する。"""
    for b in _random_nonterminal(3, 30, 22):
        for depth in range(1, 6):
            py = py_negamax(b.copy(), depth, -INF, INF, {}, default_eval)
            ru = rs.negamax_value(b.bb[0], b.bb[1], depth)
            assert py == ru, f"depth={depth} py={py} rs={ru}\n{b}"


def test_search_matches_python() -> None:
    """反復深化 search の (score, best_move) が depth 1..6 で一致する。"""
    for b in _random_nonterminal(4, 30, 24):
        for depth in range(1, 7):
            ps, pm = py_search(b.copy(), depth)
            rsc, rsm = rs.search(b.bb[0], b.bb[1], depth)
            assert (ps, pm) == (rsc, rsm), f"depth={depth} py={(ps, pm)} rs={(rsc, rsm)}\n{b}"


def _play(columns: list[int]) -> Board:
    b = Board()
    for col in columns:
        b.play(col)
    return b


def test_finds_immediate_win() -> None:
    b = _play([0, 1, 0, 1, 0, 1])  # 先手が柱0で即勝ち
    score, move = rs.search(b.bb[0], b.bb[1], 2)
    assert move == 0
    assert score > rs_mate_lo()


def test_finds_fork() -> None:
    b = _play([1, 2, 4, 8, 6, 11, 9, 14])  # 柱5でダブルリーチ
    score, move = rs.search(b.bb[0], b.bb[1], 5)
    assert move == 5
    assert score > rs_mate_lo()


def test_time_limit_returns_legal_move() -> None:
    b = _play([5, 6, 9, 10, 0])
    score, move = rs.search(b.bb[0], b.bb[1], 64, 0.2)
    assert move in b.legal_moves()


def rs_mate_lo() -> int:
    # search.rs の MATE_LO = WIN - 64 - 1
    return 1_000_000 - 64 - 1


# --- 精緻化パリティ特徴 (実験用) の D4 不変性とハーネス整合 -----------------

# (parity_weight, immediate, parity_mode): mode 0=ALL, 1=LOWEST, 2=REACHABLE
_EVAL_CONFIGS = [
    (0, 0, 0),     # ベースライン (line_potential)
    (-8, 0, 0),    # ALL (既定)
    (-8, 0, 1),    # LOWEST
    (-8, 0, 2),    # REACHABLE
    (-8, 12, 0),   # ALL + 即時脅威
]


def test_all_eval_modes_are_d4_invariant() -> None:
    """新しいパリティモードを含む全評価が D4 不変 (対称性 TT の前提)。"""
    from score_four.symmetry import COL_PERMS

    def image(seq: list[int], t: int) -> Board:
        b = Board()
        for c in seq:
            b.play(COL_PERMS[t][c])
        return b

    rng = random.Random(9)
    for _ in range(40):
        seq: list[int] = []
        b = Board()
        for _ in range(rng.randint(1, 30)):
            if b.is_terminal():
                break
            c = rng.choice(b.legal_moves())
            b.play(c)
            seq.append(c)
        if b.is_terminal():
            continue
        for pw, imm, mode in _EVAL_CONFIGS:
            base = rs.eval_cfg(b.bb[0], b.bb[1], pw, imm, mode)
            for t in range(8):
                im = image(seq, t)
                assert rs.eval_cfg(im.bb[0], im.bb[1], pw, imm, mode) == base


def test_play_match_consistency() -> None:
    """同一評価同士は左右対称で勝ち数一致。総局数 = openings*2。"""
    from score_four.selfplay import random_openings

    openings = [list(o) for o in random_openings(12, 6, seed=5)]
    aw, bw, dr = rs.play_match((-8, 0, 0), (-8, 0, 0), openings, 3)
    assert aw == bw  # 同一評価なので先後入替で対称
    assert aw + bw + dr == len(openings) * 2
