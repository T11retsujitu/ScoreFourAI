"""selfplay.py (計測ハーネス) のテスト。

強さの結論ではなく、ハーネス自体が壊れていないこと (決定性・整合性・終局保証) を
確認する。実際の評価関数比較は計測スクリプトで行い、結果は人手で判断する。
"""
from score_four.board import Board
from score_four.evaluate import line_potential, threat_eval
from score_four.selfplay import (
    make_mover,
    play_game,
    play_match,
    random_openings,
)


def test_random_openings_are_distinct_and_nonterminal() -> None:
    openings = random_openings(count=20, plies=6, seed=1)
    assert len(openings) == 20
    assert len(set(openings)) == 20  # 相異なる
    for seq in openings:
        assert len(seq) == 6
        board = Board()
        for col in seq:
            board.play(col)
        assert not board.is_terminal()


def test_random_openings_are_deterministic() -> None:
    assert random_openings(10, 8, seed=42) == random_openings(10, 8, seed=42)


def test_play_game_reaches_terminal_and_is_deterministic() -> None:
    mover = make_mover(line_potential, depth=2)
    opening = random_openings(1, 4, seed=3)[0]
    w1 = play_game(opening, mover, mover)
    w2 = play_game(opening, mover, mover)
    assert w1 == w2  # 決定的
    assert w1 in (0, 1, None)


def test_play_game_finds_forced_win() -> None:
    """先手が即勝ちできる序盤から始めれば、先手 mover が必ず勝つ。"""
    mover = make_mover(line_potential, depth=2)
    # 先手 柱0 を z0,z1,z2、後手 柱1。手番=先手で柱0 が即勝ち。
    winner = play_game((0, 1, 0, 1, 0, 1), mover, mover)
    assert winner == 0


def test_play_match_counts_are_consistent() -> None:
    """総局数 = openings*2、自分同士の対戦は勝敗が左右対称になる。"""
    openings = random_openings(count=6, plies=6, seed=5)
    a_wins, b_wins, draws = play_match(line_potential, threat_eval, openings, depth=2)
    assert a_wins + b_wins + draws == len(openings) * 2

    # 同一評価同士なら、先後を入れ替えた2局構成上 A/B の勝ち数は一致するはず。
    a2, b2, d2 = play_match(line_potential, line_potential, openings, depth=2)
    assert a2 == b2
    assert a2 + b2 + d2 == len(openings) * 2
