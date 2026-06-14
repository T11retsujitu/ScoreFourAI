"""詰み探索 (solve.py) の契約・健全性テスト — Phase 7。

センサー先行 (CLAUDE.md): 詰み探索の手数は **全幅 negamax + 零評価** の参照で独立に
再現する。零評価 negamax は test_search.py で negamax_full と同値が固められているので、
これが詰み手数の基準になる。加えて既知局面 (即詰み・受け・引分) の回帰を持つ。

全幅 negamax (枝刈りなし) は深いと爆発するので、参照は **空き柱の少ない深めの局面を
浅い地平線で** 突き合わせる (短手数の詰みが出やすく全幅木も小さい)。solve 自身は αβ＋
TT＋脅威枝刈り付きで速いので、PV・回帰は通常局面でも回せる。
"""
import random

from score_four.board import Board
from score_four.search import MATE_LO, WIN, negamax_full
from score_four.solve import (
    is_forced_win,
    solve,
    winning_moves_with_distance,
    zero_eval,
)


def _ref_mate(board: Board, max_plies: int) -> tuple[str, int | None]:
    """全幅 negamax + 零評価で (status, plies) を求める参照実装。

    depth を 1 から増やし、最初に |value| が MATE_LO を超えた深さが最短詰み。
    零評価では詰みでない局面の値は 0 のまま。
    """
    for d in range(1, max_plies + 1):
        v = negamax_full(board, d, zero_eval)
        if v > MATE_LO:
            return "win", (WIN - v) - board.num_moves
        if v < -MATE_LO:
            return "loss", (WIN + v) - board.num_moves
    return "none", None


def _positions(
    seed: int, count: int, setup_lo: int, setup_hi: int
) -> list[Board]:
    """ランダムプレイアウトで非終端局面を集める (setup を深くすると分岐が小さい)。"""
    rng = random.Random(seed)
    out: list[Board] = []
    while len(out) < count:
        b = Board()
        for _ in range(rng.randint(setup_lo, setup_hi)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if not b.is_terminal():
            out.append(b)
    return out


# --- 契約: 参照 (全幅 + 零評価) と一致 ---------------------------------------


def test_solve_matches_full_width_reference() -> None:
    """空き柱の少ない深めの局面で solve の status/plies が全幅参照と一致する。"""
    max_plies = 5
    for b in _positions(11, 30, setup_lo=24, setup_hi=42):
        ref_status, ref_plies = _ref_mate(b.copy(), max_plies)
        r = solve(b.copy(), max_plies)
        if ref_status == "none":
            assert r.status in ("unknown", "draw"), f"{r}\n{b}"
        else:
            assert (r.status, r.plies) == (ref_status, ref_plies), f"{r}\n{b}"


def test_solve_is_deterministic() -> None:
    for b in _positions(3, 12, setup_lo=10, setup_hi=20):
        assert solve(b.copy(), 6) == solve(b.copy(), 6)


# --- PV (詰み手順) の健全性 -------------------------------------------------


def test_winning_pv_is_a_legal_line_that_realises_the_mate() -> None:
    """win の PV を打ち切ると、宣言手数で詰ます側が実際に勝つ。"""
    found = 0
    for b in _positions(5, 50, setup_lo=14, setup_hi=30):
        r = solve(b.copy(), 6)
        if r.status != "win":
            continue
        found += 1
        winner = b.turn
        assert r.pv and r.pv[0] == r.best_move
        assert len(r.pv) == r.plies
        probe = b.copy()
        for mv in r.pv:
            assert mv in probe.legal_moves()
            probe.play(mv)
        assert probe.winner == winner
    assert found > 0  # 強制勝ち局面を少なくとも1つは検査している


def test_losing_pv_leads_to_opponent_win() -> None:
    found = 0
    for b in _positions(8, 50, setup_lo=14, setup_hi=30):
        r = solve(b.copy(), 6)
        if r.status != "loss":
            continue
        found += 1
        loser = b.turn
        assert len(r.pv) == r.plies
        probe = b.copy()
        for mv in r.pv:
            probe.play(mv)
        assert probe.winner == loser ^ 1
    assert found > 0


# --- 既知局面の回帰 ---------------------------------------------------------


def test_immediate_mate_in_one() -> None:
    b = Board()
    for c in (0, 1, 0, 2, 0, 3):  # 先手 X が柱0に3つ → 柱0で即勝ち
        b.play(c)
    r = solve(b, 4)
    assert (r.status, r.plies, r.best_move) == ("win", 1, 0)
    assert is_forced_win(b)
    assert winning_moves_with_distance(b, 4) == [(0, 1)]


def test_terminal_position_is_loss_for_side_to_move() -> None:
    b = Board()
    for c in (0, 1, 0, 1, 0, 1, 0):  # 先手 X が柱0で勝ち、手番は後手 O に移る
        b.play(c)
    assert b.winner == 0
    r = solve(b, 4)
    assert (r.status, r.plies) == ("loss", 0)


def test_mate_found_at_exact_horizon_is_not_unknown() -> None:
    """詰み手数ちょうどの地平線でも win を読み切る (地平線不足で unknown にしない)。"""
    b = Board()
    for c in (0, 1, 0, 2, 0, 3):  # 1 手詰み
        b.play(c)
    assert solve(b, 1).status == "win"  # max_plies=1 でちょうど読み切る


def test_short_horizon_returns_unknown_when_undecided() -> None:
    """地平線が残り全マスに届かず決着も無ければ unknown。"""
    b = Board()
    for c in (5, 6, 9, 10):  # 序盤、1 手で決着しない
        b.play(c)
    r = solve(b, 1)  # 1 手では強制勝ちも負けも出ない
    assert r.status == "unknown"
    assert r.best_move in b.legal_moves()
