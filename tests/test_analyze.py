"""analyze() (探索統計 + PV) の契約・健全性テスト (Phase 1)。

analyze は加算的な拡張: 同条件の探索値 (score, best_move) は既存 search と一致する
必要がある。PV が合法手列であること、統計が健全であること、時間制御で完了深さが
取れることを確認する。Rust 拡張が無ければ skip。
"""
import random

import pytest

from score_four.board import Board
from score_four.search import search as py_search

rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")


def _random_nonterminal(seed: int, count: int, max_plies: int) -> list[Board]:
    rng = random.Random(seed)
    out: list[Board] = []
    for _ in range(count):
        b = Board()
        for _ in range(rng.randint(0, max_plies)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if not b.is_terminal():
            out.append(b)
    return out


def test_analyze_matches_engine_search() -> None:
    """固定深さ analyze の (score, best_move) が rs.search と一致する (加算的)。

    rs.search == Python search は test_rust_search.py で担保済みなので、ここは速い
    rs.search と突き合わせる (推移的に Python とも一致)。
    """
    for b in _random_nonterminal(1, 40, 24):
        for depth in (4, 6, 8):
            r = rs.analyze(b.bb[0], b.bb[1], depth)
            s, m = rs.search(b.bb[0], b.bb[1], depth)
            assert (r["score"], r["best_move"]) == (s, m), f"depth={depth}\n{b}"


def test_analyze_matches_python_search_directly() -> None:
    """直接の Python 契約も少数・浅めで確認する。"""
    for b in _random_nonterminal(5, 8, 18):
        for depth in (3, 5):
            r = rs.analyze(b.bb[0], b.bb[1], depth)
            ps, pm = py_search(b.copy(), depth)
            assert (r["score"], r["best_move"]) == (ps, pm), f"depth={depth}\n{b}"


def test_pv_is_a_legal_line_starting_with_best_move() -> None:
    for b in _random_nonterminal(2, 25, 22):
        r = rs.analyze(b.bb[0], b.bb[1], 6)
        pv = r["pv"]
        assert len(pv) >= 1
        assert pv[0] == r["best_move"]
        probe = b.copy()
        for mv in pv:
            assert mv in probe.legal_moves()
            probe.play(mv)


def test_stats_are_sane() -> None:
    b = Board()
    for c in (5, 6, 9, 10):
        b.play(c)
    r = rs.analyze(b.bb[0], b.bb[1], 8)
    assert r["completed_depth"] == 8        # 時間制御なし → max_depth まで完了
    assert r["nodes"] > 0
    assert r["tt_hits"] >= 0
    assert r["beta_cutoffs"] >= 0
    assert r["qnodes"] == 0                   # Phase2 まで未使用
    assert set(r.keys()) == {
        "score", "best_move", "completed_depth", "nodes", "qnodes",
        "tt_hits", "tt_cutoffs", "beta_cutoffs", "elapsed_ms", "pv",
    }


def test_immediate_win_returns_winning_move_and_pv() -> None:
    b = Board()
    for c in (0, 1, 0, 1, 0, 1):  # 先手が柱0で即勝ち
        b.play(c)
    r = rs.analyze(b.bb[0], b.bb[1], 4)
    assert r["best_move"] == 0
    assert r["pv"][0] == 0
    assert r["score"] > 1_000_000 - 64 - 1     # MATE 近傍


def test_time_limited_analyze_completes_a_depth() -> None:
    b = Board()
    for c in (5, 6, 9, 10):
        b.play(c)
    r = rs.analyze(b.bb[0], b.bb[1], 64, 0.2)
    assert r["best_move"] in b.legal_moves()
    assert r["completed_depth"] >= 1
    assert r["elapsed_ms"] <= 2000             # 締切(200ms)から大きく超過しない
