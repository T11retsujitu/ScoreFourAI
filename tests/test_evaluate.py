"""evaluate.py の基本性質テスト。

評価関数の強さ自体は自己対戦 (selfplay.py) で測る。ここでは「純粋関数である
こと」「手番対称性」「脅威が多い側を正しく優位と判定すること」「即時脅威の
加点」「parity_weight=0 で threat_eval と一致」など、壊れていないことの最低限を
確認する。D4 対称不変性は test_symmetry.py で全評価について検証する。
"""
from score_four.board import Board
from score_four.evaluate import (
    _PARITY,
    default_eval,
    line_potential,
    parity_eval,
    threat_eval,
)


def _play(columns: list[int]) -> Board:
    board = Board()
    for col in columns:
        board.play(col)
    return board


def test_empty_board_is_neutral() -> None:
    assert line_potential(Board()) == 0


def test_is_pure_does_not_mutate_board() -> None:
    board = _play([0, 5, 1, 6])
    before = (board.bb[0], board.bb[1], board.turn, board.key)
    line_potential(board)
    after = (board.bb[0], board.bb[1], board.turn, board.key)
    assert before == after


def test_perspective_is_side_to_move() -> None:
    """同一盤面でも手番が逆なら符号が反転する。"""
    board = _play([0, 5, 1, 6, 2])  # 先手が z=0 に脅威を作りつつ手番交代
    p1_view = line_potential(board)  # 手番=後手 視点
    board.turn ^= 1
    p0_view = line_potential(board)  # 手番=先手 視点
    assert p1_view == -p0_view


def test_advantage_for_more_threats() -> None:
    """脅威で劣る側 (手番側) のスコアは負になる。

    先手が柱0,1,2(z0) で強いライン(3個)を持ち、後手は柱12,13(z0)の2個だけ。
    手番は後手なので、その視点のスコアは負になるべき。
    """
    board = _play([0, 12, 1, 13, 2])
    assert board.turn == 1
    assert line_potential(board) < 0


# --- threat_eval / parity_eval -------------------------------------------


def test_threat_eval_is_pure() -> None:
    board = _play([0, 5, 1, 6])
    before = (board.bb[0], board.bb[1], board.turn, list(board.heights))
    threat_eval(board)
    after = (board.bb[0], board.bb[1], board.turn, list(board.heights))
    assert before == after


def test_threat_eval_empty_is_neutral() -> None:
    assert threat_eval(Board()) == 0


def test_immediate_threat_scores_above_latent_potential() -> None:
    """今すぐ詰められる3並び (即時脅威) は、同じ3並びでも latent 評価より高い。

    手番=後手の局面で、先手が z=0 横 (柱0,1,2) を持ち柱3 が即着手可能 = 即時脅威。
    threat_eval は line_potential より (後手視点で) さらに負に振れる。
    """
    board = _play([0, 12, 1, 13, 2])  # 先手 0,1,2(z0) / 後手 12,13 / 手番=後手
    assert board.turn == 1
    # 先手の即時脅威 (柱3) があるぶん、threat_eval の方が後手に厳しい。
    assert threat_eval(board) < line_potential(board)


def test_parity_eval_reduces_to_baselines() -> None:
    """parity_weight=0 のとき: immediate=0 で line_potential、immediate=w で threat_eval。"""
    import random

    rng = random.Random(0)
    for _ in range(60):
        board = Board()
        for _ in range(rng.randint(1, 30)):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if board.is_terminal():
            continue
        assert parity_eval(board, parity_weight=0, immediate=0) == line_potential(board)
        assert parity_eval(board, parity_weight=0, immediate=40) == threat_eval(
            board, immediate=40
        )


def test_default_eval_is_tuned_parity() -> None:
    """探索の既定評価 = 検証済み重み (_PARITY=-8) のパリティ評価。"""
    import random

    assert _PARITY == -8  # docs/eval_measurements.md で採用した値
    rng = random.Random(1)
    for _ in range(40):
        board = Board()
        for _ in range(rng.randint(1, 28)):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if board.is_terminal():
            continue
        assert default_eval(board) == parity_eval(board, parity_weight=_PARITY, immediate=0)


def test_features_are_pure_and_sized() -> None:
    """Phase 8: features は純粋・長さ NF・整数のみ (決定論の前提)。"""
    from score_four.evaluate import NF, features

    board = _play([5, 6, 9, 10, 5])
    snap = (board.bb[0], board.bb[1])
    f = features(board)
    assert len(f) == NF
    assert all(isinstance(x, int) for x in f)
    assert (board.bb[0], board.bb[1]) == snap  # 非破壊
    assert features(Board()) == [0] * NF  # 空盤は中立


def test_learned_eval_reproduces_default() -> None:
    """Phase 8: 学習重み [1,5,25,-8,0,0] は手書きパリティ評価 default_eval と完全一致。

    パリティ式が特徴量の線形分解で表せること (= 学習評価が既定の上位互換) の健全性。
    """
    import random

    from score_four.evaluate import learned_eval

    rng = random.Random(7)
    for _ in range(60):
        board = Board()
        for _ in range(rng.randint(1, 32)):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if board.is_terminal():
            continue
        assert learned_eval(board, [1, 5, 25, -8, 0, 0]) == default_eval(board)


def test_geometric_features_pure_and_sized() -> None:
    """Phase 10: geometric_features は純粋・長さ GEO_NF・整数。空盤は決まった play 分布。"""
    from score_four.evaluate import GEO_NF, geometric_features

    board = _play([5, 6, 9, 10, 5])
    snap = (board.bb[0], board.bb[1])
    f = geometric_features(board)
    assert len(f) == GEO_NF
    assert all(isinstance(x, int) for x in f)
    assert (board.bb[0], board.bb[1]) == snap  # 非破壊
    # 空盤: 占有差は全 0、着地は z=0 層 → 角4/辺8/面4/中心0。
    assert geometric_features(Board()) == [0, 0, 0, 0, 4, 8, 4, 0]


def test_eval_default_plus_geometric_zero_weights_is_default() -> None:
    """Phase 10: 幾何重みすべて 0 のとき candidate == default_eval（採否判定の基準点）。"""
    import random

    from score_four.evaluate import GEO_NF, eval_default_plus_geometric

    rng = random.Random(11)
    for _ in range(60):
        board = Board()
        for _ in range(rng.randint(1, 32)):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if board.is_terminal():
            continue
        assert eval_default_plus_geometric(board, [0] * GEO_NF) == default_eval(board)
