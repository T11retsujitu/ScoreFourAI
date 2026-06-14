"""軽量学習評価 (Phase 8) を学習し、自己対戦で計測して JSON 保存するスクリプト。

使い方:
    PYTHONPATH=src python scripts/train_eval.py \
        [n_positions] [teacher_depth] [out_path] [--measure]

深い αβ 探索を教師に線形モデルを最小二乗で学習し、整数へ量子化する (詳細は
src/score_four/learn.py)。`--measure` を付けると学習評価 (重み) と既定パリティ評価を
固定時間自己対戦で A/B 計測し、勝率を表示する (採否判定; CLAUDE.md「計測してから採用」)。

Rust 拡張 (score_four_rs) があれば教師ラベル付け・計測に使う (無くても学習は動くが遅い)。
"""

import json
import sys
import time

from score_four.evaluate import NF
from score_four.learn import (
    build_dataset,
    fit_linear,
    quantize,
    r2_score,
    sample_positions,
)
from score_four.selfplay import random_openings

FEATURE_NAMES = ["open1", "open2", "open3", "parity", "reach3", "center"]
# 既定パリティ評価 default_eval と等価な学習重み (健全性の基準点)。
PARITY_WEIGHTS = [1, 5, 25, -8, 0, 0]


def measure(weights: list[int], time_ms: int, n_openings: int, seeds: list[int]) -> dict:
    """学習評価 (weights) vs 既定パリティ評価を固定時間自己対戦で A/B 計測する。

    各シードで相異なる序盤を生成し、先後入れ替えで総当たり対局 (play_match_learned)。
    learned が A、parity が B。多シード集計で頑健性を見る。
    """
    import score_four_rs as rs

    total_a = total_b = total_d = 0
    per_seed = []
    for seed in seeds:
        openings = [list(o) for o in random_openings(n_openings, 6, seed=seed)]
        aw, bw, dr = rs.play_match_learned(weights, openings, 64, time_ms)
        total_a += aw
        total_b += bw
        total_d += dr
        games = aw + bw + dr
        wr = (aw + 0.5 * dr) / games if games else 0.0
        per_seed.append({"seed": seed, "learned": aw, "parity": bw, "draws": dr, "winrate": wr})
    games = total_a + total_b + total_d
    winrate = (total_a + 0.5 * total_d) / games if games else 0.0
    return {
        "time_ms": time_ms,
        "games": games,
        "learned_wins": total_a,
        "parity_wins": total_b,
        "draws": total_d,
        "learned_winrate": winrate,
        "per_seed": per_seed,
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    n_positions = int(args[0]) if len(args) > 0 else 4000
    teacher_depth = int(args[1]) if len(args) > 1 else 8
    out = args[2] if len(args) > 2 else "data/learned_eval.json"

    t0 = time.time()
    print(f"sampling {n_positions} positions ...", flush=True)
    positions = sample_positions(n_positions, max_plies=24, seed=12345)
    print(f"  got {len(positions)} unique non-terminal positions "
          f"({time.time() - t0:.1f}s)", flush=True)

    print(f"labeling with depth-{teacher_depth} teacher search ...", flush=True)
    x, y = build_dataset(positions, teacher_depth)
    print(f"  {len(x)} labeled (dropped {len(positions) - len(x)} forced-result) "
          f"({time.time() - t0:.1f}s)", flush=True)

    w_float = fit_linear(x, y)
    w_int = quantize(w_float, q=100)
    r2_f = r2_score(x, y, w_float)
    r2_parity = r2_score(x, y, PARITY_WEIGHTS)
    # 量子化は一様スケール (手の選択に無関係) なので R^2 はスケールを戻して評価し、
    # 丸め誤差だけを見る (これが学習評価の質に効く部分)。
    peak = max((abs(w) for w in w_float), default=1.0) or 1.0
    descaled = [wi * peak / 100 for wi in w_int]
    r2_q = r2_score(x, y, descaled)

    print("\nfeature        float_w     int_w")
    for name, wf, wi in zip(FEATURE_NAMES, w_float, w_int, strict=True):
        print(f"  {name:<9} {wf:10.3f} {wi:8d}")
    print(f"\nR^2  float={r2_f:.4f}  quantized(round-only)={r2_q:.4f}  "
          f"parity_baseline={r2_parity:.4f}")

    result = {
        "format": "score_four_learned_eval/1",
        "feature_names": FEATURE_NAMES,
        "nf": NF,
        "teacher_depth": teacher_depth,
        "n_samples": len(x),
        "weights_float": w_float,
        "weights": w_int,
        "r2_float": r2_f,
        "r2_quantized": r2_q,
        "r2_parity_baseline": r2_parity,
        "parity_weights": PARITY_WEIGHTS,
    }

    if "--measure" in flags:
        print("\nmeasuring learned vs parity (fixed-time self-play) ...", flush=True)
        measurements = []
        for time_ms in (100, 300):
            m = measure(w_int, time_ms, n_openings=24, seeds=[101, 202, 303])
            measurements.append(m)
            print(f"  {time_ms}ms: learned winrate {m['learned_winrate']:.3f} "
                  f"({m['learned_wins']}-{m['parity_wins']}-{m['draws']} over {m['games']} games)",
                  flush=True)
        result["measurements"] = measurements

    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nsaved -> {out} ({time.time() - t0:.1f}s total)")


if __name__ == "__main__":
    main()
