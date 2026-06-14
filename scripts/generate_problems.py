"""詰み問題集を生成して JSON に保存するスクリプト — Phase 7。

使い方:
    PYTHONPATH=src python scripts/generate_problems.py \
        [target_plies] [count] [out_path] [seed]

ランダムプレイアウトで非終端局面をサンプリングし、初手一意の強制勝ち (指定手数) を
集める。シード固定で決定的 (再現可能)。D4 正規化で重複除去し、難易度昇順で保存する。
"""
import sys
import time

from score_four.problems import generate_problems, save_problems, verify_problem


def main() -> None:
    target_plies = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    out = sys.argv[3] if len(sys.argv) > 3 else "data/mate_problems.json"
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    t = time.time()

    problems = generate_problems(target_plies, count, seed=seed)
    for p in problems:  # 保存前に各問題を独立に再検証する。
        assert verify_problem(p), p

    save_problems(problems, out)
    print(
        f"generated {len(problems)} mate-in-{target_plies} problems "
        f"(seed={seed}) -> {out} in {time.time() - t:.1f}s"
    )


if __name__ == "__main__":
    main()
