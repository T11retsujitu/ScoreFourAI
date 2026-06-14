"""定石(opening book)を生成して JSON に保存するスクリプト (Phase 6: 選択的・再開可能)。

使い方:
    PYTHONPATH=src python scripts/generate_book.py \
        [max_plies] [depth] [out_path] [owner] [opp_width] [ai_width]

    owner: 0=先手 / 1=後手 / both=両側(既定)。both は owner0/owner1 を別ファイルに生成して
           merge する。ai_width=自分手番の展開幅(既定1=principal)、opp_width=相手手番の幅
           (既定4=robust。大きいほど exhaustive)。

**途中保存・再開可能**: out_path と out_path.ckpt.json へ周期保存し、中断後に同じ引数で
再実行すると続きから生成する(Windows CPU での長時間生成・追加延長向け)。Rust 拡張があれば
自動で使う(無ければ純 Python 探索)。固定深さで決定的(再現可能)。
"""
import sys
import time
from pathlib import Path

from score_four.book import generate_book_resumable


def main() -> None:
    max_plies = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    depth = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("data/opening_book.json")
    owner = sys.argv[4] if len(sys.argv) > 4 else "both"
    opp_width = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    ai_width = int(sys.argv[6]) if len(sys.argv) > 6 else 1
    t = time.time()

    def progress(ply: int, n: int) -> None:
        print(f"  ply{ply}: {n} entries ({time.time() - t:.0f}s)", flush=True)

    common = dict(
        max_plies=max_plies, depth=depth, ai_width=ai_width,
        opp_width=opp_width, on_progress=progress,
    )
    if owner in ("0", "1"):
        book = generate_book_resumable(out, owner=int(owner), **common)
    else:  # both: 同じ out へ owner=0 → owner=1 を順に生成 (共有局面は再利用され和集合になる)。
        print("owner=0 ...", flush=True)
        generate_book_resumable(out, owner=0, **common)
        print("owner=1 ...", flush=True)
        book = generate_book_resumable(out, owner=1, **common)

    print(f"generated {len(book)} entries (max_plies={max_plies}, depth={depth}, "
          f"owner={owner}, ai={ai_width}, opp={opp_width}) -> {out} in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
