"""詰み問題の自動生成・検証・入出力 — Phase 7。

`solve.py` の詰み探索を使い、**指定手数の強制勝ち問題**を機械的に作る。良い問題の条件
(roadmap Phase 7):

  1. **強制勝ち**       : 手番側がどんな応手でも勝てる。
  2. **指定手数 (詰み手数)** : 勝ち手を打つまでの総 ply 数がちょうど N。
  3. **初手一意**       : 強制勝ちになる初手がただ 1 つ (解が一意)。
  4. **全応手で勝ち継続** : 初手の後、相手のどの受けに対しても強制勝ちが続く
                          (強制勝ちの定義から従うが `verify_problem` で明示検証する)。
  5. **D4 重複除去**     : 同じ軌道 (対称形) の問題は 1 つだけ採用 (canonical キー)。
  6. **難易度指標**      : 詰み手数とおとり (非勝ち合法手) の数から決定的に算出。

問題はランダムプレイアウトで非終端局面を多数サンプリングし、上の条件を満たすものを
集める。シード固定で決定的。生成・検証とも盤面を破壊しない。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .board import Board
from .solve import winning_moves_with_distance
from .symmetry import canonical


@dataclass(frozen=True)
class MateProblem:
    """1 つの詰み問題 (強制勝ち・初手一意)。

    setup    : 空盤からこの局面に到達する着手列 (再現・人間可読用)。
    bb       : 局面のビットボード (bb[0], bb[1])。
    turn     : 手番 (0=先手)。これが「詰ます側」。
    mate_in  : 詰み手数 (勝ち手を打つまでの総 ply 数)。
    solution : 唯一の正解初手 (現局面の柱 0..15)。
    num_legal: 合法手数 (= おとりの数 + 1)。
    difficulty: 難易度指標 (大きいほど難しい)。`grade_difficulty` 参照。
    key      : D4 正規化キー (重複除去・同一性判定用)。
    """

    setup: tuple[int, ...]
    bb: tuple[int, int]
    turn: int
    mate_in: int
    solution: int
    num_legal: int
    difficulty: int
    key: int


def grade_difficulty(mate_in: int, num_legal: int) -> int:
    """詰み手数とおとり数から難易度指標を決定的に算出する。

    主軸は詰み手数 (深いほど難しい)。同手数ではおとり (正解以外の合法手) が多いほど
    難しい。係数は単調・決定的であればよく、絶対値に意味はない (相対比較用)。
    """
    return mate_in * 100 + min(num_legal - 1, 15)


def build_problem(
    board: Board, setup: tuple[int, ...], max_plies: int
) -> MateProblem | None:
    """局面が「初手一意の強制勝ち」なら MateProblem を、そうでなければ None を返す。

    強制勝ちになる初手がちょうど 1 つのときだけ採用する (初手一意)。盤面は破壊しない。
    """
    if board.is_terminal():
        return None
    wins = winning_moves_with_distance(board, max_plies)
    if len(wins) != 1:  # 初手一意でなければ問題にしない (0=勝ちなし / 2+=非一意)。
        return None
    solution, mate_in = wins[0]
    num_legal = len(board.legal_moves())
    return MateProblem(
        setup=tuple(setup),
        bb=(board.bb[0], board.bb[1]),
        turn=board.turn,
        mate_in=mate_in,
        solution=solution,
        num_legal=num_legal,
        difficulty=grade_difficulty(mate_in, num_legal),
        key=canonical(board.bb[0], board.bb[1])[0],
    )


def verify_problem(problem: MateProblem, max_plies: int | None = None) -> bool:
    """問題が条件を満たすか独立に再検証する (決定的・盤面非破壊)。

    1. setup を打ち直すと bb/turn が一致する。
    2. 強制勝ちになる初手が solution ただ 1 つで、その手数が mate_in に一致。
    3. solution を打った後、相手のどの応手でも強制勝ちが続く (全応手で勝ち継続)。
    """
    from .solve import solve

    if max_plies is None:
        max_plies = problem.mate_in
    board = _replay(problem.setup)
    if (board.bb[0], board.bb[1]) != problem.bb or board.turn != problem.turn:
        return False

    wins = winning_moves_with_distance(board, max_plies)
    if wins != [(problem.solution, problem.mate_in)]:
        return False

    # 初手の後、相手の全応手で「こちら (problem.turn) の強制勝ち」が続くこと。
    after = board.copy()
    if after.play(problem.solution):
        return problem.mate_in == 1  # 即勝ちなら 1 手詰みで完結。
    for reply in after.legal_moves():
        grand = after.copy()
        if grand.play(reply):
            return False  # 相手がここで勝ってしまう (強制勝ちでない)。
        # grand は再び problem.turn の手番。強制勝ちが続くはず。
        if solve(grand, max_plies - 2).status != "win":
            return False
    return True


def _replay(moves: tuple[int, ...]) -> Board:
    """着手列を空盤から打ち直した局面を返す。"""
    board = Board()
    for col in moves:
        board.play(col)
    return board


def _random_position(
    rng: random.Random, setup_min: int, setup_max: int
) -> tuple[Board, tuple[int, ...]]:
    """ランダムプレイアウトで非終端局面を 1 つ作り (局面, 着手列) を返す。"""
    board = Board()
    moves: list[int] = []
    target = rng.randint(setup_min, setup_max)
    for _ in range(target):
        if board.is_terminal():
            break
        col = rng.choice(board.legal_moves())
        board.play(col)
        moves.append(col)
    return board, tuple(moves)


def generate_problems(
    target_plies: int,
    count: int,
    *,
    seed: int = 0,
    setup_min: int = 4,
    setup_max: int = 24,
    max_attempts: int = 20000,
    max_plies: int | None = None,
) -> list[MateProblem]:
    """指定手数 (target_plies) の詰み問題を count 個まで生成する (決定的)。

    ランダムプレイアウトで非終端局面をサンプリングし、初手一意かつ詰み手数が
    target_plies の強制勝ちを集める。D4 正規化キーで重複を除去する。難易度昇順で返す。

    max_plies は詰み探索の地平線 (既定 target_plies+2)。短手数の問題でも、より長い詰みと
    取り違えないために少し余裕を持たせる。
    """
    if max_plies is None:
        max_plies = target_plies + 2
    rng = random.Random(seed)
    found: dict[int, MateProblem] = {}
    for _ in range(max_attempts):
        if len(found) >= count:
            break
        board, setup = _random_position(rng, setup_min, setup_max)
        if board.is_terminal():
            continue
        problem = build_problem(board, setup, max_plies)
        if problem is None or problem.mate_in != target_plies:
            continue
        found.setdefault(problem.key, problem)
    return sorted(found.values(), key=lambda p: (p.difficulty, p.key))


def save_problems(problems: list[MateProblem], path: str | Path) -> None:
    """問題集を JSON で保存する (D4 キーは文字列化)。"""
    data = {
        "format": "score-four-mate-problems/1",
        "problems": [
            {
                "setup": list(p.setup),
                "bb": list(p.bb),
                "turn": p.turn,
                "mate_in": p.mate_in,
                "solution": p.solution,
                "num_legal": p.num_legal,
                "difficulty": p.difficulty,
                "key": str(p.key),
            }
            for p in problems
        ],
    }
    Path(path).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def load_problems(path: str | Path) -> list[MateProblem]:
    """save_problems で書いた JSON を読み込む。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        MateProblem(
            setup=tuple(d["setup"]),
            bb=(d["bb"][0], d["bb"][1]),
            turn=d["turn"],
            mate_in=d["mate_in"],
            solution=d["solution"],
            num_legal=d["num_legal"],
            difficulty=d["difficulty"],
            key=int(d["key"]),
        )
        for d in data["problems"]
    ]
