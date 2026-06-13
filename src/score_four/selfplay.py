"""自己対戦による評価関数の計測ハーネス。

設計メモ (docs/design.md 4.7) が要求する「評価ヒューリスティックは自己対戦で効果を
測ってから採否・重みを決める」を実現する。2 つの評価関数で固定深さの探索エンジンを
対戦させ、勝敗を集計する。

決定論を保つため (CLAUDE.md): 探索は time_limit を使わず固定 max_depth、評価関数は
決定的。多様性は「ランダムな序盤手順 (opening) を多数生成し、左右両方の先後で打つ」
ことで確保する。同一 opening を両エンジンが先手・後手で 1 局ずつ打ち、先手有利を
相殺する。
"""

import random
from collections.abc import Callable

from .board import Board
from .search import best_move

Mover = Callable[[Board], int]
Heuristic = Callable[[Board], int]


def make_mover(heuristic: Heuristic, depth: int) -> Mover:
    """評価関数と固定探索深さから、局面 -> 着手柱 の決定的な mover を作る。"""
    return lambda board: best_move(board, depth, heuristic)


def random_openings(count: int, plies: int, seed: int = 0) -> list[tuple[int, ...]]:
    """相異なる非終端の序盤手順を count 個生成する (各 plies 手)。

    途中で決着した手順は捨てる。多様な中盤局面から計測するための種。
    """
    rng = random.Random(seed)
    seen: set[tuple[int, ...]] = set()
    openings: list[tuple[int, ...]] = []
    attempts = 0
    while len(openings) < count and attempts < count * 100:
        attempts += 1
        board = Board()
        seq: list[int] = []
        ok = True
        for _ in range(plies):
            if board.is_terminal():
                ok = False
                break
            col = rng.choice(board.legal_moves())
            board.play(col)
            seq.append(col)
        if ok and not board.is_terminal():
            key = tuple(seq)
            if key not in seen:
                seen.add(key)
                openings.append(key)
    return openings


def play_game(
    opening: tuple[int, ...],
    mover0: Mover,
    mover1: Mover,
) -> int | None:
    """opening から打ち継ぎ、先手=mover0 / 後手=mover1 で対局して勝者を返す。

    返り値: 勝者 0 / 1、引き分けは None。opening は手番に関係なく盤に置かれる
    (双方の手として交互に積まれる) 初期手順。
    """
    board = Board()
    for col in opening:
        board.play(col)
    movers = (mover0, mover1)
    while not board.is_terminal():
        col = movers[board.turn](board)
        board.play(col)
    return board.winner


def play_match(
    heuristic_a: Heuristic,
    heuristic_b: Heuristic,
    openings: list[tuple[int, ...]],
    depth: int,
) -> tuple[int, int, int]:
    """A と B の評価関数を openings で総当たり対戦させ ``(a_wins, b_wins, draws)``。

    各 opening につき 2 局: (A 先手 / B 後手) と (B 先手 / A 後手)。先手有利を
    相殺するため必ず両者が一度ずつ先手を持つ。決定的。
    """
    mover_a = make_mover(heuristic_a, depth)
    mover_b = make_mover(heuristic_b, depth)
    a_wins = b_wins = draws = 0
    for opening in openings:
        # A 先手, B 後手
        w = play_game(opening, mover_a, mover_b)
        if w == 0:
            a_wins += 1
        elif w == 1:
            b_wins += 1
        else:
            draws += 1
        # B 先手, A 後手
        w = play_game(opening, mover_b, mover_a)
        if w == 0:
            b_wins += 1
        elif w == 1:
            a_wins += 1
        else:
            draws += 1
    return a_wins, b_wins, draws
