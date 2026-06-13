"""evaluate.py の基本性質テスト。

評価関数はまだ第一次ヒューリスティック (ライン potential) なので、強さ自体は
保証しない。ここでは「純粋関数であること」「手番対称性」「脅威が多い側を
正しく優位と判定すること」など、壊れていないことの最低限を確認する。
"""
from score_four.board import Board
from score_four.evaluate import line_potential


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
