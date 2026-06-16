"""Stage 2: 定石起点の自己対局 (勝敗) からロジスティック評価を学習し計測する。

`scripts/selfplay_from_book.py` が作る (局面, 勝敗) データを教師に、**勝ち確率**を予測する
線形評価をロジスティック回帰で学習する。Phase 8 の score 回帰 (fit≠strength) を避け、目的を
「勝ち」に揃えるユーザー案 (docs/book_web_and_learning.md §2)。学習は標準化空間で行い、生特徴の
重みへ戻して**整数へ量子化** (推論は整数・決定的・D4 不変)。**バイアスは捨てる** (符号対称を
保ち default_eval と同じ意味論にする)。

特徴は player-0 視点の `features` (NF=6)。自己対局ラベルは手番側視点なので、復元した手番で
player-0 視点へ符号を揃えてから y=勝1/負0/引分0.5 にする。

採否は **固定時間自己対局の勝率** で判断する (`--measure`、CLAUDE.md「計測してから採用」)。
fit が良くても強さに直結しない前提で、勝ち越して初めて default へ統合する。

使い方:
    PYTHONPATH=src python scripts/train_eval_from_selfplay.py \
        [--data data/selfplay.json] [--out data/selfplay_eval.json]
        [--epochs 400] [--lr 0.5] [--l2 1e-3] [--holdout 0.2] [--min-ply 0]
        [--measure] [--time-ms 100,300] [--seeds 101,202,303] [--n-openings 24]
"""
import argparse
import json
import time

from score_four.board import Board
from score_four.evaluate import NF
from score_four.learn import (
    fit_logistic,
    logistic_accuracy,
    quantize,
    standardize,
)

FEATURE_NAMES = ["open1", "open2", "open3", "parity", "reach3", "center"]
PARITY_WEIGHTS = [1, 5, 25, -8, 0, 0]  # default_eval と等価 (基準点)


def load_dataset(path: str, min_ply: int) -> tuple[list[list[int]], list[float], list[int]]:
    """selfplay JSON を (X=player0視点特徴, y=勝1/負0/引分0.5, plies) に展開する。

    保存ラベル lab は手番側視点 (勝=1/負=-1/引分=0)。復元した手番で player-0 視点へ
    符号を揃え、勝1/負0/引分0.5 のソフトラベルにする。min_ply 未満の手数は除外。
    """
    from score_four.evaluate import features

    data = json.loads(open(path, encoding="utf-8").read())
    x: list[list[int]] = []
    y: list[float] = []
    plies: list[int] = []
    for b0s, b1s, lab in data["samples"]:
        board = Board.from_bitboards(int(b0s), int(b1s))
        if board.num_moves < min_ply:
            continue
        p0lab = lab if board.turn == 0 else -lab  # player-0 視点へ
        x.append(features(board))
        y.append(1.0 if p0lab == 1 else 0.0 if p0lab == -1 else 0.5)
        plies.append(board.num_moves)
    return x, y, plies


def measure(weights: list[int], time_ms: int, n_openings: int, seeds: list[int]) -> dict:
    """学習評価 (weights) vs 既定パリティ評価を固定時間自己対戦で A/B 計測する。"""
    import score_four_rs as rs

    from score_four.selfplay import random_openings

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
    ap = argparse.ArgumentParser(description="自己対局の勝敗からロジスティック評価を学習")
    ap.add_argument("--data", default="data/selfplay.json")
    ap.add_argument("--out", default="data/selfplay_eval.json")
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--lr", type=float, default=0.5)
    ap.add_argument("--l2", type=float, default=1e-3)
    ap.add_argument("--holdout", type=float, default=0.2, help="ホールドアウト比率")
    ap.add_argument("--min-ply", type=int, default=0, help="この手数未満の局面を除外")
    ap.add_argument("--seed", type=int, default=0, help="train/holdout 分割のシード")
    ap.add_argument("--measure", action="store_true", help="固定時間自己対戦で A/B 計測")
    ap.add_argument("--time-ms", default="100,300", help="計測の持ち時間 (カンマ区切り)")
    ap.add_argument("--seeds", default="101,202,303", help="計測シード (カンマ区切り)")
    ap.add_argument("--n-openings", type=int, default=24)
    args = ap.parse_args()

    t0 = time.time()
    x, y, _ = load_dataset(args.data, args.min_ply)
    if not x:
        raise SystemExit(f"no samples in {args.data} (min-ply={args.min_ply})")
    wins = sum(1 for v in y if v == 1.0)
    losses = sum(1 for v in y if v == 0.0)
    draws = len(y) - wins - losses
    print(f"samples {len(x)}  (player0 win {wins} / loss {losses} / draw {draws})  "
          f"min-ply {args.min_ply}  ({time.time() - t0:.1f}s)", flush=True)

    # train/holdout 分割 (決定的)。
    import random as _random

    idx = list(range(len(x)))
    _random.Random(args.seed).shuffle(idx)
    n_hold = int(len(idx) * args.holdout)
    hold_i, train_i = idx[:n_hold], idx[n_hold:]
    xtr = [[float(v) for v in x[i]] for i in train_i]
    ytr = [y[i] for i in train_i]
    xho = [[float(v) for v in x[i]] for i in hold_i]
    yho = [y[i] for i in hold_i]

    # 標準化空間で学習 → 生特徴の重みへ戻す (バイアスは捨てる)。
    xs, mean, std = standardize(xtr)
    w_std = fit_logistic(xs, ytr, epochs=args.epochs, lr=args.lr, l2=args.l2)
    lw_raw = [w_std[j] / std[j] for j in range(NF)]
    w_int = quantize(lw_raw, q=100)

    # 的中率は標準化空間 (学習空間) で測る (バイアスを捨てた整数重みは生空間で別物)。
    xho_s = [[(xho[r][j] - mean[j]) / std[j] for j in range(NF)] for r in range(len(xho))]
    acc_tr = logistic_accuracy(xs, ytr, w_std)
    acc_ho = logistic_accuracy(xho_s, yho, w_std)
    print(f"\nlogistic accuracy  train {acc_tr:.3f}  holdout {acc_ho:.3f}", flush=True)

    print("\nfeature        std_w     raw_w     int_w")
    for name, ws, wr, wi in zip(FEATURE_NAMES, w_std, lw_raw, w_int, strict=True):
        print(f"  {name:<9} {ws:8.3f} {wr:9.4f} {wi:8d}")

    result = {
        "format": "score_four_selfplay_eval/1",
        "feature_names": FEATURE_NAMES,
        "nf": NF,
        "data": args.data,
        "n_samples": len(x),
        "n_train": len(train_i),
        "n_holdout": len(hold_i),
        "epochs": args.epochs,
        "lr": args.lr,
        "l2": args.l2,
        "weights_std": w_std,
        "weights_raw": lw_raw,
        "weights": w_int,
        "acc_train": acc_tr,
        "acc_holdout": acc_ho,
        "parity_weights": PARITY_WEIGHTS,
    }

    if args.measure:
        seeds = [int(s) for s in args.seeds.split(",") if s]
        print("\nmeasuring learned vs parity (fixed-time self-play) ...", flush=True)
        measurements = []
        for tms in (int(t) for t in args.time_ms.split(",") if t):
            m = measure(w_int, tms, n_openings=args.n_openings, seeds=seeds)
            measurements.append(m)
            print(f"  {tms}ms: learned winrate {m['learned_winrate']:.3f} "
                  f"({m['learned_wins']}-{m['parity_wins']}-{m['draws']} over {m['games']} games)",
                  flush=True)
        result["measurements"] = measurements

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nsaved -> {args.out} ({time.time() - t0:.1f}s total)")


if __name__ == "__main__":
    main()
