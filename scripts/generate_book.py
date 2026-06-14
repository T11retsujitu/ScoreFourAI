"""定石(opening book)を生成して JSON に保存するスクリプト。

使い方:
    PYTHONPATH=src python scripts/generate_book.py [max_plies] [depth] [out_path]

固定深さ(depth)の探索で決定的に生成する(再現可能)。Rust 拡張があれば自動で使う。
"""
import sys
import time

from score_four.book import generate_book, save_book

def main() -> None:
    max_plies = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    depth = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    out = sys.argv[3] if len(sys.argv) > 3 else "data/opening_book.json"
    t = time.time()

    def progress(ply: int, n_pos: int, total: int) -> None:
        print(f"  ply{ply}: {n_pos} positions searched, {total} entries "
              f"({time.time() - t:.0f}s)", flush=True)

    book = generate_book(max_plies=max_plies, depth=depth, on_ply=progress)
    save_book(book, out)
    print(f"generated {len(book)} entries (max_plies={max_plies}, depth={depth}) "
          f"-> {out} in {time.time() - t:.1f}s")

if __name__ == "__main__":
    main()
