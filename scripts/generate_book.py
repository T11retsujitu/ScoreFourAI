"""定石(opening book)を生成して JSON に保存するスクリプト (Phase 6)。

選択的・途中保存・再開・追加延長・フェーズ別パラメータ・評価打ち切りに対応。

使い方 (例):
    # 序盤を広く浅く (depth10/相手6手) で 8 手まで、both
    PYTHONPATH=src python scripts/generate_book.py data/opening_book.json \
        --plies 8 --depth 10 --opp-width 6 --owner both

    # フェーズ別: 序盤 0-8 広く浅く / 中盤 9-16 深く広く / 終盤 17-30 狭く深く
    PYTHONPATH=src python scripts/generate_book.py data/opening_book.json \
        --profile 8:10:1:6,16:14:1:4,30:18:1:2 --owner both --cutoff 400

    # 続き: 上の book に 11 手以降を別パラメータで足す場合も、早い区間を変えなければ接続する。
    #   (profile の早い区間 8:10:1:6 を据え置き、後ろの区間を伸ばして再実行する)

**途中保存・再開**: 中断後に同じ引数で再実行すると保存済みを再利用して続きを生成する。
**追加延長**: --plies / profile の手数を増やして再実行すると既存を再利用し新しい手数だけ探索。
profile の区間は ``until_ply:depth:ai_width:opp_width`` をカンマ区切り (until 昇順)。
--cutoff N: 局面の評価が ±N 以上なら決着が見えたとみなしその変化を打ち切る。
Rust 拡張があれば自動で使う。固定深さで決定的 (再現可能)。
"""
import argparse
import time
from pathlib import Path

from score_four.book import Profile, generate_book_resumable


def parse_profile(s: str) -> Profile:
    """"8:10:1:6,16:14:1:4" -> [(8,10,1,6),(16,14,1,4)] (until_ply 昇順)。"""
    segs: Profile = []
    for part in s.split(","):
        nums = part.split(":")
        if len(nums) != 4:
            raise ValueError(f"profile 区間は until:depth:ai:opp 形式: {part!r}")
        until, d, aw, ow = (int(x) for x in nums)
        segs.append((until, d, aw, ow))
    segs.sort()
    return segs


def main() -> None:
    ap = argparse.ArgumentParser(description="選択的・再開可能・フェーズ別の定石生成")
    ap.add_argument("out", nargs="?", default="data/opening_book.json", help="出力ファイル")
    ap.add_argument("--plies", type=int, default=6, help="最大手数 (--profile 指定時は無視)")
    ap.add_argument("--depth", type=int, default=10, help="探索深さ (--profile 指定時は無視)")
    ap.add_argument("--owner", default="both", choices=["0", "1", "both"], help="0=先手/1=後手/both")
    ap.add_argument("--ai-width", type=int, default=1, help="自分手番の展開幅 (1=最善のみ)")
    ap.add_argument("--opp-width", type=int, default=4, help="相手手番の展開幅 (robust)")
    ap.add_argument("--profile", default=None,
                    help="フェーズ別 until:depth:ai:opp をカンマ区切り 例 8:10:1:6,16:14:1:4")
    ap.add_argument("--cutoff", type=int, default=None, help="|eval|>=N で変化を打ち切り")
    ap.add_argument("--time-ms", type=int, default=0, help=">0 で固定時間/手 (既定 0=固定深さ)")
    ap.add_argument("--shared-tt", action="store_true",
                    help="局面間で置換表を共有して高速化 (結果は fresh とビット一致しない場合あり)")
    args = ap.parse_args()

    out = Path(args.out)
    profile = parse_profile(args.profile) if args.profile else None
    max_plies = profile[-1][0] if profile else args.plies
    time_limit = args.time_ms / 1000 if args.time_ms > 0 else None
    t0 = time.time()

    def progress(ply: int, n: int) -> None:
        print(f"  ply{ply}: {n} entries ({time.time() - t0:.0f}s)", flush=True)

    common = dict(
        max_plies=max_plies, depth=args.depth, ai_width=args.ai_width,
        opp_width=args.opp_width, time_limit=time_limit, profile=profile,
        cutoff=args.cutoff, on_progress=progress, shared_tt=args.shared_tt,
    )
    if args.owner in ("0", "1"):
        book = generate_book_resumable(out, owner=int(args.owner), **common)
    else:  # both: 同じ out へ owner=0 → owner=1 を順に生成 (共有局面は再利用され和集合になる)。
        print("owner=0 ...", flush=True)
        generate_book_resumable(out, owner=0, **common)
        print("owner=1 ...", flush=True)
        book = generate_book_resumable(out, owner=1, **common)

    desc = f"profile={args.profile}" if profile else \
        f"plies={max_plies} depth={args.depth} opp={args.opp_width}"
    print(f"generated {len(book)} entries ({desc}, owner={args.owner}, cutoff={args.cutoff}) "
          f"-> {out} in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
