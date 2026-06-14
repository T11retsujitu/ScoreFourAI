"""定石 (opening book) の生成・保存・照会。

設計 (docs/design.md 5.3 / CLAUDE.md): 序盤の各局面で深い探索の最善手と評価値を
保存し、既知局面は即座に着手できるようにする。**強いエンジンの出力として抽出される
派生物**であり、手で書くものではない。

索引は **D4 正規化キー** (symmetry.canonical)。同じ軌道の局面は 1 エントリを共有し、
保存する最善手は正規形の柱番号にしておく。照会時は現局面 -> 正規形の変換 t で逆写像し、
現局面の柱へ戻す (探索の置換表と同じ流儀)。

エントリ: ``book[canonical_key] = (best_move_canonical, score, ply)``
  best_move_canonical: 正規形での最善柱 (0..15)
  score: 手番側視点の評価値 (探索の返り値)
  ply : その局面の手数 (= 正規化キーから一意に決まる)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .board import Board
from .symmetry import COL_PERMS, INV_COL_PERMS, canonical

# book の型: 正規化キー(int) -> (正規形の最善柱, score, ply)
Book = dict[int, tuple[int, int, int]]


def _engine_search(board: Board, depth: int, time_limit: float | None) -> tuple[int, int]:
    """(score, best_move) を返す。Rust 拡張があれば使い、無ければ Python 探索。

    どちらも既定評価 (検証済みパリティ ALL/-8) を使い、同じ結果を返す。
    """
    try:
        import score_four_rs as rs

        return rs.search(board.bb[0], board.bb[1], depth, time_limit)
    except ImportError:
        from .search import search as py_search

        return py_search(board, depth, time_limit=time_limit)


def generate_book(
    max_plies: int,
    depth: int,
    time_limit: float | None = None,
    on_ply: "Callable[[int, int, int], None] | None" = None,
) -> Book:
    """root から max_plies 手までの全局面を D4 正規化で列挙し、各局面の最善手を保存。

    各局面で固定深さ (depth) の反復深化探索を行い、最善手と評価値を記録する。
    非終端局面のみ保存 (終端には着手が無い)。決定的。``on_ply(ply, n_positions,
    total)`` を渡すと各 ply 完了時に進捗を通知する。
    """
    book: Book = {}
    seen: set[int] = set()
    # frontier は各 ply の正規化ユニークな代表局面。
    frontier: list[Board] = [Board()]
    seen.add(canonical(0, 0)[0])

    for ply in range(max_plies + 1):
        # 現 frontier の各局面を探索して保存。
        for board in frontier:
            key, t = canonical(board.bb[0], board.bb[1])
            if board.is_terminal():
                continue
            _score, move = _engine_search(board, depth, time_limit)
            book[key] = (COL_PERMS[t][move], _score, ply)
        if on_ply is not None:
            on_ply(ply, len(frontier), len(book))

        if ply == max_plies:
            break

        # 次の ply の正規化ユニークな子局面を作る。
        next_frontier: list[Board] = []
        for board in frontier:
            if board.is_terminal():
                continue
            for col in board.legal_moves():
                child = board.copy()
                child.play(col)
                ckey = canonical(child.bb[0], child.bb[1])[0]
                if ckey not in seen:
                    seen.add(ckey)
                    next_frontier.append(child)
        frontier = next_frontier

    return book


def book_move(book: Book, board: Board) -> tuple[int, int] | None:
    """book に board の手があれば (現局面の最善柱, score)、無ければ None。"""
    key, t = canonical(board.bb[0], board.bb[1])
    entry = book.get(key)
    if entry is None:
        return None
    move_canonical, score, _ply = entry
    return INV_COL_PERMS[t][move_canonical], score


def choose_move(
    book: Book,
    board: Board,
    depth: int,
    time_limit: float | None = None,
) -> tuple[int, int]:
    """book にあれば即座にその手、無ければ探索して (best_move, score) を返す。

    対戦・解析の入口。既知の序盤は探索せず book で即応し、book を抜けたら探索する。
    """
    hit = book_move(book, board)
    if hit is not None:
        return hit
    score, move = _engine_search(board, depth, time_limit)
    return move, score


def save_book(book: Book, path: str | Path) -> None:
    """book を JSON で保存する (128bit キーは文字列化)。"""
    data = {
        "format": "score-four-opening-book/1",
        "entries": {str(key): list(value) for key, value in book.items()},
    }
    Path(path).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def load_book(path: str | Path) -> Book:
    """save_book で書いた JSON を読み込む。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        int(key): (value[0], value[1], value[2])
        for key, value in data["entries"].items()
    }
