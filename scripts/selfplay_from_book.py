"""Stage 2: 定石を起点にした自己対局で (局面, 勝敗) データを生成する。

book を正とした自己学習 (docs/book_web_and_learning.md §2 / ユーザー案) のデータ生成。
序盤は定石で健全に始め、softmax で多様化しつつ終局まで自己対局し、各局面に**最終勝敗**
(手番側視点 勝=1/負=-1/引分=0) を付与する。Phase 8 の score 回帰 (fit≠strength) を避け、
学習目的を「勝ち」に揃えるための教師データ。**人間対局なし**・固定シードで決定的。

着手方針 (各手):
  - 序盤 (ply < book_plies) かつ定石内: 確率 (1-explore_prob) で**定石の最善手** (深さ14/16 品質)、
    残りは softmax で逸れる (多様化)。
  - それ以外: 各子局面を gen_depth 探索した手番側評価を softmax(温度) でサンプル。即勝ち/負けは
    score_cap でクリップ (詰みを過剰に重み付けしない・オーバーフロー回避)。

**追記・再開可能**: 既存データに --games 局を足して原子保存する (Windows での長時間生成向け)。
Rust 拡張があれば探索に使う (無ければ純 Python・低速)。

使い方:
    PYTHONPATH=src python scripts/selfplay_from_book.py [--games N] [--gen-depth D]
        [--temp T] [--open-temp T] [--book-plies P] [--explore-prob E]
        [--out data/selfplay.json] [--book data/opening_book.json] [--seed S] [--no-book]
"""
import argparse
import json
import math
import os
import random
import tempfile
import time
from pathlib import Path

from score_four.board import Board
from score_four.book import book_move, load_book

try:
    import score_four_rs as _rs
except ImportError:  # pragma: no cover
    _rs = None


def _search(b0: int, b1: int, depth: int) -> int:
    """局面 (b0,b1) の手番側スコアを返す (best_move は不要)。"""
    if _rs is not None:
        return _rs.search(b0, b1, depth)[0]
    from score_four.search import search as py_search

    return py_search(Board.from_bitboards(b0, b1), depth)[0]


def _child_scores(board: Board, gen_depth: int, cap: int) -> tuple[list[int], list[int]]:
    """各合法手の手番側視点スコア (即勝ち=+cap, 引分=0, それ以外=-子の手番側スコア)。"""
    legal = board.legal_moves()
    scores = []
    for col in legal:
        ch = board.copy()
        won = ch.play(col)
        if won:
            sc = cap
        elif ch.is_terminal():
            sc = 0
        else:
            sc = -_search(ch.bb[0], ch.bb[1], gen_depth)
        scores.append(max(-cap, min(cap, sc)))
    return legal, scores


def _sample(legal: list[int], scores: list[int], temp: float, rng: random.Random) -> int:
    """softmax(score/temp) で柱をサンプル。"""
    m = max(scores)
    exps = [math.exp((s - m) / temp) for s in scores]
    r = rng.random() * sum(exps)
    acc = 0.0
    for col, e in zip(legal, exps, strict=True):
        acc += e
        if r <= acc:
            return col
    return legal[-1]


def play_game(book, rng: random.Random, args) -> list[list]:
    """1 局を自己対局し、各局面に最終勝敗ラベルを付けて返す。"""
    board = Board()
    visited = []  # (b0, b1, turn)
    while not board.is_terminal():
        visited.append((board.bb[0], board.bb[1], board.turn))
        ply = board.num_moves
        if not args.no_book and book is not None and ply < args.book_plies:
            e = book_move(book, board)
            if e is not None and rng.random() > args.explore_prob:
                board.play(e[0])
                continue
        legal, scores = _child_scores(board, args.gen_depth, args.score_cap)
        temp = args.open_temp if ply < args.book_plies else args.temp
        board.play(_sample(legal, scores, temp, rng))
    winner = board.winner
    out = []
    for b0, b1, turn in visited:
        lab = 0 if winner is None else (1 if winner == turn else -1)
        out.append([str(b0), str(b1), lab])
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main() -> None:
    ap = argparse.ArgumentParser(description="定石起点の自己対局で (局面, 勝敗) を生成")
    ap.add_argument("--games", type=int, default=200, help="今回追加する対局数")
    ap.add_argument("--gen-depth", type=int, default=6, help="着手選択の探索深さ (浅めで多様)")
    ap.add_argument("--temp", type=float, default=10.0, help="中盤以降の softmax 温度")
    ap.add_argument("--open-temp", type=float, default=4.0, help="序盤の softmax 温度 (低=健全)")
    ap.add_argument("--book-plies", type=int, default=9, help="この手数未満を序盤扱い")
    ap.add_argument("--explore-prob", type=float, default=0.25, help="序盤で定石から逸れる確率")
    ap.add_argument("--score-cap", type=int, default=100, help="softmax 前のスコアクリップ")
    ap.add_argument("--no-book", action="store_true", help="定石を使わず純 softmax 自己対局")
    ap.add_argument("--out", default="data/selfplay.json")
    ap.add_argument("--book", default="data/opening_book.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--checkpoint-every", type=int, default=50)
    args = ap.parse_args()

    out = Path(args.out)
    book = None if args.no_book else load_book(args.book)
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else \
        {"format": "score-four-selfplay/1", "samples": []}
    base = len(data["samples"])
    rng = random.Random(args.seed ^ (base * 2654435761))  # 既存量で種をずらし重複を避ける
    t0 = time.time()
    for g in range(args.games):
        data["samples"].extend(play_game(book, rng, args))
        if (g + 1) % args.checkpoint_every == 0:
            _atomic_write(out, json.dumps(data, separators=(",", ":")))
            print(f"  {g + 1}/{args.games} games, {len(data['samples'])} samples "
                  f"({time.time() - t0:.0f}s)", flush=True)
    _atomic_write(out, json.dumps(data, separators=(",", ":")))
    print(f"total {len(data['samples'])} samples (+{len(data['samples']) - base}) -> {out} "
          f"in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
