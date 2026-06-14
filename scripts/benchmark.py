"""固定時間ベンチマーク (強化指示書 Phase 1)。

分類済み局面を {50,100,300,1000}ms で analyze し、完了深さ・ノード数・NPS・TT hit率・
beta cutoff率・PV・最善手・スコア・実行時間を記録する。結果は JSON に保存し、要約を表示。
各 Phase の前後で実行し、強さ(深さ)・速度(NPS)の変化を比較するためのベースライン。

使い方:
    PYTHONPATH=src python scripts/benchmark.py [out.json]   # 既定 docs/benchmarks/baseline.json
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

from score_four.board import Board

try:
    import score_four_rs as rs
except ImportError:
    sys.exit("score_four_rs が必要です: cd rust && maturin build --release && pip install ...")

TIMES_MS = [50, 100, 300, 1000]
MAX_DEPTH = 64


_MATE_LO = 1_000_000 - 64 - 1


def _deep_seq(target_plies: int, seed: int, require_live: bool = True) -> list[int]:
    """target_plies 手ちょうどで非終端になる手順を返す。

    require_live なら、浅い探索で既に勝敗が読み切れている (詰み済み) 局面は除外し、
    深い探索が意味を持つ「生きた」局面だけを採用する。
    """
    for s in range(seed, seed + 4000):
        rng = random.Random(s)
        b = Board()
        seq: list[int] = []
        for _ in range(target_plies):
            if b.is_terminal():
                break
            c = rng.choice(b.legal_moves())
            b.play(c)
            seq.append(c)
        if len(seq) != target_plies or b.is_terminal():
            continue
        if require_live:
            r = rs.analyze(b.bb[0], b.bb[1], 4)
            if abs(r["score"]) > _MATE_LO:
                continue  # 既に詰み読み切り → スキップ
        return seq
    raise RuntimeError(f"could not build live non-terminal seq of {target_plies} plies")


# 分類済み局面 (柱番号の列。非終端であること)。midgame/endgame はシード固定で生成。
POSITIONS: dict[str, list[list[int]]] = {
    "opening": [[], [5], [5, 6]],
    "midgame": [_deep_seq(18, 11), _deep_seq(22, 22)],
    "endgame": [_deep_seq(40, 33), _deep_seq(48, 44)],
    "immediate_win": [[0, 1, 0, 1, 0, 1]],          # 先手が柱0で即勝ち
    "forced_block": [[0, 1, 0, 1, 0]],              # 後手は柱0を受けるしかない
    "double_reach": [[1, 2, 4, 8, 6, 11, 9, 14]],   # 先手が柱5でフォーク
    "forced_sequence": [[0, 5, 1, 6, 2, 7, 4]],     # 数手の強制手順を含む
    "quiet_eval": [[5, 10, 6, 9]],                  # 戦術の無い静穏局面
    "horizon": [[5, 6, 9, 10, 0, 15, 3, 12]],       # 浅い地平線の先に戦術
}


def _bb(seq: list[int]) -> tuple[int, int, int]:
    b = Board()
    for c in seq:
        b.play(c)
    if b.is_terminal():
        raise ValueError(f"terminal position in benchmark set: {seq}")
    return b.bb[0], b.bb[1], b.num_moves


def run() -> dict:
    results = []
    for category, seqs in POSITIONS.items():
        for pi, seq in enumerate(seqs):
            b0, b1, plies = _bb(seq)
            for t_ms in TIMES_MS:
                r = rs.analyze(b0, b1, MAX_DEPTH, t_ms / 1000.0)
                elapsed = max(r["elapsed_ms"], 1)
                nps = int(r["nodes"] * 1000 / elapsed)
                tt_hit_rate = (r["tt_hits"] / r["nodes"]) if r["nodes"] else 0.0
                beta_rate = (r["beta_cutoffs"] / r["nodes"]) if r["nodes"] else 0.0
                results.append({
                    "category": category, "pos": pi, "plies": plies, "time_ms": t_ms,
                    "completed_depth": r["completed_depth"], "nodes": r["nodes"], "nps": nps,
                    "tt_hit_rate": round(tt_hit_rate, 3), "beta_cutoff_rate": round(beta_rate, 3),
                    "score": r["score"], "best_move": r["best_move"], "pv": r["pv"],
                    "elapsed_ms": r["elapsed_ms"],
                })
    return {
        "meta": {"times_ms": TIMES_MS, "max_depth": MAX_DEPTH,
                 "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        "results": results,
    }


def summarize(data: dict) -> None:
    print(f"{'category':16} {'pl':>3} {'t_ms':>5} {'depth':>5} {'nodes':>10} "
          f"{'NPS':>9} {'tt_hit':>6} {'beta':>5} {'score':>8} {'mv':>3}")
    for r in data["results"]:
        print(f"{r['category']:16} {r['plies']:>3} {r['time_ms']:>5} "
              f"{r['completed_depth']:>5} {r['nodes']:>10} {r['nps']:>9} "
              f"{r['tt_hit_rate']:>6.2f} {r['beta_cutoff_rate']:>5.2f} "
              f"{r['score']:>8} {r['best_move']:>3}")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/benchmarks/baseline.json")
    data = run()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    summarize(data)
    print(f"\nsaved {len(data['results'])} records -> {out}")


if __name__ == "__main__":
    main()
