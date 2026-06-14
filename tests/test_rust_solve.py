"""Rust 詰み探索 (score_four_rs.solve) と Python solve.solve の言語横断契約テスト。

Phase 7 の詰み探索を Rust へ移植した (Phase 9 の WASM solve 公開の土台)。Rust は零評価
反復深化を Python と同一アルゴリズムで行うので、(status, plies, best_move, pv) が **完全
一致** することを保証する。Python 側の正しさ自体は test_solve.py が全幅 negamax 参照で
固めているので、ここでは Rust==Python の一致のみを見る。

拡張未ビルドなら skip (純 Python のスイートは独立に緑)。
"""
import random

import pytest

from score_four.board import Board
from score_four.solve import solve as py_solve

rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")


def _positions(seed: int, count: int, lo: int, hi: int) -> list[Board]:
    """ランダムプレイアウトで非終端局面を集める (setup を深くすると詰みが出やすい)。"""
    rng = random.Random(seed)
    out: list[Board] = []
    while len(out) < count:
        b = Board()
        for _ in range(rng.randint(lo, hi)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if not b.is_terminal():
            out.append(b)
    return out


def _assert_match(b: Board, max_plies: int) -> None:
    r = rs.solve(b.bb[0], b.bb[1], max_plies)
    p = py_solve(b.copy(), max_plies)
    assert r["status"] == p.status, f"status py={p.status} rs={r['status']}\n{b}"
    assert r["plies"] == p.plies, f"plies py={p.plies} rs={r['plies']}\n{b}"
    assert r["best_move"] == p.best_move, f"move py={p.best_move} rs={r['best_move']}\n{b}"
    assert tuple(r["pv"]) == p.pv, f"pv py={p.pv} rs={tuple(r['pv'])}\n{b}"


def test_solve_matches_python_midgame() -> None:
    """中盤の浅い地平線で status/plies/move/pv が一致 (詰みあり/なし両方)。"""
    for b in _positions(11, 40, lo=14, hi=30):
        _assert_match(b, 6)


def test_solve_matches_python_deep_sparse() -> None:
    """空き柱の少ない深めの局面 (短手数詰みが出やすい) で一致する。"""
    for b in _positions(12, 40, lo=24, hi=42):
        _assert_match(b, 7)


def test_solve_matches_python_full_horizon() -> None:
    """地平線が残り全マスを覆う深い max_plies でも draw/win/loss が一致する。"""
    for b in _positions(13, 20, lo=30, hi=46):
        _assert_match(b, 64)


def test_solve_terminal_and_empty() -> None:
    """終端 (勝者あり) は loss/0、満杯は draw、空盤は探索が走り一致する。"""
    # 空盤 (引分が読み切れない浅い地平線では unknown)。
    empty = Board()
    assert rs.solve(empty.bb[0], empty.bb[1], 4)["status"] == py_solve(empty, 4).status
    # 即詰み局面: 先手が a1,b1,c1 を持ち d1 で勝てる手番。
    b = Board()
    for c in [0, 4, 1, 5, 2, 6]:  # 先手 0,1,2 / 後手 4,5,6
        b.play(c)
    _assert_match(b, 6)


def test_solve_on_already_won_board() -> None:
    """既に決着した局面 (ビットボードから復元) でも Rust==Python: loss/0/move-1。

    rs.solve は (b0,b1) から from_bitboards で復元するので、Rust 側の勝者検出が
    Python と一致している必要がある (一致しないと終局局面で誤って探索を続ける)。
    """
    b = Board()
    for c in [0, 4, 1, 5, 2, 6, 3]:  # 先手が a1-d1 を完成して勝利
        b.play(c)
    assert b.winner == 0  # 先手の勝ち (盤は終局)
    r = rs.solve(b.bb[0], b.bb[1], 13)
    p = py_solve(b.copy(), 13)
    assert (r["status"], r["plies"], r["best_move"]) == ("loss", 0, -1)
    assert (p.status, p.plies, p.best_move) == ("loss", 0, -1)
