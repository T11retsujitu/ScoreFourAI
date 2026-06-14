"""df-PN 詰み探索 (dfpn.py) の契約・健全性テスト — Phase 7。

センサー先行 (CLAUDE.md): df-PN は別アルゴリズムなので、検証済みの零評価 αβ `solve` と
**同じ勝ち判定** を返すことを契約で固める。`solve` 自体は test_solve.py が全幅 negamax
参照で固めているので、これが df-PN の正しさの基準になる。CI を軽く保つため局面は浅め。
"""
import random

from score_four.board import Board
from score_four.dfpn import prove_win, prove_win_stats
from score_four.solve import solve


def _positions(seed: int, count: int, lo: int, hi: int) -> list[Board]:
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


def test_dfpn_matches_solve_midgame() -> None:
    """中盤の浅い地平線で df-PN の勝ち判定が αβ solve と一致 (詰みあり/なし)。"""
    saw_win = saw_nonwin = False
    for b in _positions(11, 60, lo=14, hi=30):
        for mp in (5, 7):
            won = prove_win(b.copy(), mp)
            ref = solve(b.copy(), mp).status == "win"
            assert won == ref, f"mp={mp} dfpn={won} solve={ref}\n{b}"
            saw_win |= ref
            saw_nonwin |= not ref
    assert saw_win and saw_nonwin  # 両方のケースを実際に踏んでいる


def test_dfpn_matches_solve_deep_sparse() -> None:
    """空き柱の少ない局面 (短手数詰みが出やすい) で一致する。"""
    for b in _positions(12, 40, lo=24, hi=42):
        won = prove_win(b.copy(), 7)
        assert won == (solve(b.copy(), 7).status == "win"), f"\n{b}"


def test_dfpn_is_pure_and_deterministic() -> None:
    """非破壊・決定的 (同一局面で同一判定・同一ノード数)。"""
    for b in _positions(3, 20, lo=12, hi=24):
        snap = (b.bb[0], b.bb[1])
        r1 = prove_win_stats(b, 7)
        r2 = prove_win_stats(b, 7)
        assert (b.bb[0], b.bb[1]) == snap  # board を変更しない
        assert r1 == r2  # 決定的 (判定・ノード数とも)


def test_dfpn_immediate_and_terminal() -> None:
    """即詰み=win、決着済み/満杯=not win の基本ケース。"""
    # 先手が a1,b1,c1 を持ち d1 で即勝ち (手番=先手)。
    b = Board()
    for c in [0, 4, 1, 5, 2, 6]:
        b.play(c)
    assert prove_win(b, 3) is True
    # 既に先手が勝った局面: 手番側 (後手) に勝ちは無い。
    b.play(3)  # 先手 a1-d1 完成
    assert b.winner == 0
    assert prove_win(b, 5) is False
