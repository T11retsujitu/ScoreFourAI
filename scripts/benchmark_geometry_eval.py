"""幾何・解放評価 (Phase 10 実験) の自動 A/B 計測。**人間対局・手動ラベルは使わない**。

候補 = default_eval + 幾何加点（単独特徴 × 重み）、基準 = default_eval。固定シードの自己対局を
先後入れ替えで打ち、勝率を集計する（rs.play_match_geometric を再利用）。計画は
docs/experiments/geometric_relational_eval.md の §8/§13。結果は JSON / Markdown に保存。

採否はこの計測（多シード・固定時間/固定深さ）だけで決める。Stage 1 は単独特徴スクリーニング
（play_* を先に、次に occ_*）。Rust 拡張が必要（無ければ即終了）。

使い方:
    PYTHONPATH=src python scripts/benchmark_geometry_eval.py \
        [depth] [n_openings] [time_ms] [out_prefix]
    # time_ms>0 で固定時間、0 で固定深さ。
"""

import json
import sys
import time

from score_four.evaluate import GEO_NF
from score_four.selfplay import random_openings

try:
    import score_four_rs as rs
except ImportError:  # pragma: no cover
    print("score_four_rs（Rust 拡張）が必要です。ビルドしてください。", file=sys.stderr)
    sys.exit(1)

FEATURE_NAMES = [
    "occ_corner", "occ_edge", "occ_face", "occ_interior",
    "play_corner", "play_edge", "play_face", "play_interior",
]
# 仮説の主眼は play_*。計画の順序に従い play_* を先に評価する。
SCREEN_ORDER = [4, 5, 6, 7, 0, 1, 2, 3]
# 単独特徴の重み候補（計画 §13.2 の -8..8 の部分集合）。
WEIGHTS = [-8, -4, -2, -1, 1, 2, 4, 8]

SEEDS = [101, 202, 303]
OPENING_PLIES = 6


def _unit(idx: int, w: int) -> list[int]:
    v = [0] * GEO_NF
    v[idx] = w
    return v


def screen_feature(idx: int, n_openings: int, depth: int, time_ms: int) -> list[dict]:
    """1 特徴を重み掃引で default と対戦させ、各重みの集計を返す。"""
    rows = []
    for w in WEIGHTS:
        gw = _unit(idx, w)
        ta = tb = td = 0
        for seed in SEEDS:
            openings = [list(o) for o in random_openings(n_openings, OPENING_PLIES, seed=seed)]
            aw, bw, dr = rs.play_match_geometric(gw, openings, depth, time_ms)
            ta += aw
            tb += bw
            td += dr
        games = ta + tb + td
        wr = (ta + 0.5 * td) / games if games else 0.0
        rows.append({"weight": w, "winrate": wr, "wins": ta, "losses": tb, "draws": td, "games": games})
    return rows


def _fmt_md(meta: dict, results: dict) -> str:
    games_per = len(SEEDS) * meta["n_openings"] * 2
    se = (0.25 / games_per) ** 0.5 if games_per else 0.0
    cond = f"固定時間 {meta['time_ms']}ms" if meta["time_ms"] else f"固定深さ {meta['depth']}"
    lines = [
        "# 幾何・解放評価 単独特徴スクリーニング (Phase 10 実験)",
        "",
        f"> 候補 = default + 単独幾何特徴 × 重み、基準 = default。{cond}・"
        f"{len(SEEDS)} シード × {meta['n_openings']} openings（先後入替）= {games_per} 局/設定。",
        f"> winrate は候補視点。1SE ≈ {se:.3f}（0.5±1SE 以内は誤差レンジ）。**人間対局なし**。",
        "",
        "重み別 winrate（行=特徴、列=重み）:",
        "",
        "| 特徴 | " + " | ".join(f"w={w}" for w in WEIGHTS) + " | 最大偏差 |",
        "|------|" + "------|" * (len(WEIGHTS) + 1),
    ]
    for name in [FEATURE_NAMES[i] for i in SCREEN_ORDER]:
        rows = {r["weight"]: r["winrate"] for r in results[name]}
        cells = [f"{rows[w]:.3f}" for w in WEIGHTS]
        best = max(rows.values(), key=lambda v: abs(v - 0.5))
        mark = "**" if abs(best - 0.5) > 2 * se else ""
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {mark}{best - 0.5:+.3f}{mark} |")
    lines += [
        "",
        f"**所見**: 0.5 から 2SE（≈{2 * se:.3f}）以上ずれた設定だけが有意候補。play_* が主眼。",
        "正シグナルのある特徴のみ次段（固定時間・段階別・ホールドアウト）へ進める。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    depth = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    n_openings = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    time_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    prefix = sys.argv[4] if len(sys.argv) > 4 else "docs/benchmarks/geometry_eval"

    meta = {
        "depth": depth, "n_openings": n_openings, "time_ms": time_ms,
        "seeds": SEEDS, "opening_plies": OPENING_PLIES, "weights": WEIGHTS,
        "feature_names": FEATURE_NAMES,
    }
    cond = f"time={time_ms}ms" if time_ms else f"depth={depth}"
    t0 = time.time()
    print(f"geometry eval screening ({cond}, {len(SEEDS)} seeds × {n_openings} openings)\n", flush=True)

    results: dict[str, list[dict]] = {}
    for idx in SCREEN_ORDER:
        name = FEATURE_NAMES[idx]
        rows = screen_feature(idx, n_openings, depth, time_ms)
        results[name] = rows
        best = max(rows, key=lambda r: abs(r["winrate"] - 0.5))
        print(f"  {name:<14} best w={best['weight']:+d} winrate={best['winrate']:.3f} "
              f"({time.time() - t0:.0f}s)", flush=True)

    with open(f"{prefix}.json", "w") as f:
        json.dump({"meta": meta, "results": results}, f, indent=2)
    with open(f"{prefix}.md", "w") as f:
        f.write(_fmt_md(meta, results))
    print(f"\nsaved -> {prefix}.json / {prefix}.md ({time.time() - t0:.0f}s total)")


if __name__ == "__main__":
    main()
