"""df-PN 詰み探索 vs 零評価 αβ `solve` のノード数・時間ベンチ (Phase 7)。

CLAUDE.md「改善が確認できない最適化は採用しない / 変更前にベンチ→計測で判断」に従い、
df-PN が既存の αβ 詰み探索より**少ないノード・短い時間**で同じ勝ち判定に到達するかを
測る。採否はこの計測で決める (port to Rust するか棚上げするか)。

公平性: 両アルゴリズムとも `Board.play` (= 局面を 1 つ生成する操作) の回数を同一の
カウンタで数える。αβ は **実際にデプロイされている `solve`** をそのまま使う (反復深化で
詰みを読み切ったら停止)。df-PN も完全解決まで走らせる。両者「解けたら止まる」点が揃う。

使い方:
    PYTHONPATH=src python scripts/benchmark_dfpn.py [max_plies] [n_positions]
"""

import sys
import time

from score_four.board import Board
from score_four.dfpn import prove_win
from score_four.solve import solve


def _count_plays():
    """Board.play の呼び出し回数を数えるコンテキスト用の (リセット, 取得, 復元)。"""
    orig = Board.play
    counter = [0]

    def counting(self, col):
        counter[0] += 1
        return orig(self, col)

    Board.play = counting
    return orig, counter


def _restore(orig):
    Board.play = orig


def _mate_positions(seed: int, count: int, lo: int, hi: int, max_plies: int):
    """詰み (αβ 判定で win) の非終端局面を集める。比較は詰みありで意味を持つ。"""
    import random

    rng = random.Random(seed)
    wins, others = [], []
    attempts = 0
    while (len(wins) < count or len(others) < count // 2) and attempts < count * 400:
        attempts += 1
        b = Board()
        for _ in range(rng.randint(lo, hi)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if b.is_terminal():
            continue
        st = solve(b.copy(), max_plies).status
        if st == "win" and len(wins) < count:
            wins.append(b)
        elif st != "win" and len(others) < count // 2:
            others.append(b)
    return wins, others


def _measure(label, positions, max_plies):
    orig, counter = _count_plays()
    try:
        ab_nodes = dfpn_nodes = 0
        ab_time = dfpn_time = 0.0
        for b in positions:
            counter[0] = 0
            t = time.perf_counter()
            ab_status = solve(b.copy(), max_plies).status
            ab_time += time.perf_counter() - t
            ab_nodes += counter[0]

            counter[0] = 0
            t = time.perf_counter()
            won = prove_win(b.copy(), max_plies)
            dfpn_time += time.perf_counter() - t
            dfpn_nodes += counter[0]

            assert won == (ab_status == "win"), f"verdict mismatch {ab_status} {won}"
    finally:
        _restore(orig)
    n = len(positions)
    print(f"  {label} ({n} pos, max_plies={max_plies}):")
    print(f"    αβ solve : {ab_nodes:>10d} plays   {ab_time*1e3:8.1f} ms   "
          f"({ab_nodes // max(n,1)} plays/pos)")
    print(f"    df-PN    : {dfpn_nodes:>10d} plays   {dfpn_time*1e3:8.1f} ms   "
          f"({dfpn_nodes // max(n,1)} plays/pos)")
    ratio = dfpn_nodes / ab_nodes if ab_nodes else 0.0
    print(f"    df-PN/αβ nodes = {ratio:.3f}   time = "
          f"{dfpn_time/ab_time if ab_time else 0:.3f}")


def main() -> None:
    max_plies = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    print(f"df-PN vs αβ 詰み探索ベンチ (max_plies={max_plies})\n")
    for seed, lo, hi in [(11, 14, 30), (12, 22, 38), (13, 28, 44)]:
        wins, others = _mate_positions(seed, count, lo, hi, max_plies)
        _measure(f"mate (setup {lo}-{hi})", wins, max_plies)
        if others:
            _measure(f"no-mate (setup {lo}-{hi})", others, max_plies)
    print()


if __name__ == "__main__":
    main()
