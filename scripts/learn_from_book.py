"""Stage 1 診断: 定石を教師に「最善手を選べる線形評価」を選好学習し move 一致率を測る。

book を正とした自己学習 (docs/book_web_and_learning.md §2) の安価な第一歩。Phase 8 の教訓
(fit≠strength) を踏まえ score 回帰はせず、**book の最善手 = 線形評価で選べるか**を測る:
各 book 局面で「book 手の子局面が手番側にとって最善 = 評価最小 (negamax)」となるよう 14 次元
(features 6 + geometric 8、D4 不変・整数) の重みを構造化パーセプトロンで学習し、ホールドアウト
move 一致率を **default_eval を 1-ply 選択器にしたベースライン**・中央寄り・ランダムと比較する。

learned が default_eval を明確に上回れば、着手順序バイアスや評価統合へ進む価値がある。
上回らなければ「線形 1-ply ポリシーでは book の深い最善手を再現しきれない」限界として記録。
**人間対局なし**。

使い方: PYTHONPATH=src python scripts/learn_from_book.py [book_path] [epochs]
"""
import random
import sys

from score_four.board import Board
from score_four.book import book_move, load_book
from score_four.evaluate import default_eval, features, geometric_features
from score_four.symmetry import canonical

DIM = 14  # features(6) + geometric(8)


def _feat(board: Board) -> list[int]:
    return [*features(board), *geometric_features(board)]


def _centrality(col: int) -> int:
    x, y = col % 4, col // 4
    return abs(2 * x - 3) + abs(2 * y - 3)


class Sample:
    """1 つの book 局面: 各合法手の (子特徴, 子評価, 柱) と book の最善手。"""

    __slots__ = ("feats", "nfeats", "deval", "best")

    def __init__(self, board: Board, best: int):
        self.best = best
        self.feats: dict[int, list[int]] = {}
        self.nfeats: dict[int, list[float]] = {}  # 標準化後 (train 統計で後から埋める)
        self.deval: dict[int, int] = {}
        for col in board.legal_moves():
            ch = board.copy()
            ch.play(col)
            self.feats[col] = _feat(ch)
            # 子の手番側スコア (相手視点)。親(手番側)は min を選ぶ = negamax。
            self.deval[col] = default_eval(ch) if not ch.is_terminal() else -10**9


def enumerate_samples(book: dict) -> list[Sample]:
    """book 局面を root から辿って実体化し Sample を作る。"""
    seen = {canonical(0, 0)[0]}
    frontier = [Board()]
    out: list[Sample] = []
    while frontier:
        nxt = []
        for b in frontier:
            if b.is_terminal():
                continue
            e = book_move(book, b)
            if e is not None:
                out.append(Sample(b, e[0]))
            for col in b.legal_moves():
                ch = b.copy()
                ch.play(col)
                k = canonical(ch.bb[0], ch.bb[1])[0]
                if k not in seen and k in book:
                    seen.add(k)
                    nxt.append(ch)
        frontier = nxt
    return out


def _dot(w: list[float], f: list[float]) -> float:
    return sum(wi * fi for wi, fi in zip(w, f, strict=True))


def standardize(samples: list[Sample], train: list[Sample]) -> None:
    """train 統計で各特徴を標準化し s.nfeats に格納 (線形学習の条件数を整える)。"""
    import statistics

    allf = [f for s in train for f in s.feats.values()]
    mean = [statistics.mean(c) for c in zip(*allf, strict=True)]
    std = [statistics.pstdev(c) or 1.0 for c in zip(*allf, strict=True)]
    for s in samples:
        for col, f in s.feats.items():
            s.nfeats[col] = [(f[i] - mean[i]) / std[i] for i in range(DIM)]


def learned_rank(w: list[float], s: Sample) -> list[int]:
    return sorted(s.nfeats, key=lambda c: (_dot(w, s.nfeats[c]), c))


def match(rank_fn, data: list[Sample], topk: int = 1) -> float:
    hit = sum(1 for s in data if s.best in rank_fn(s)[:topk])
    return hit / len(data) if data else 0.0


def train_perceptron(train: list[Sample], epochs: int) -> list[float]:
    """構造化パーセプトロン (平均化): book 手の子が評価最小になるよう更新。"""
    w = [0.0] * DIM
    acc = [0.0] * DIM
    n = 0
    for _ in range(epochs):
        for s in train:
            pred = learned_rank(w, s)[0]
            if pred != s.best:
                fb, fp = s.nfeats[s.best], s.nfeats[pred]
                for i in range(DIM):
                    w[i] += fp[i] - fb[i]
            for i in range(DIM):
                acc[i] += w[i]
            n += 1
    return [a / n for a in acc]


def main() -> None:
    book_path = sys.argv[1] if len(sys.argv) > 1 else "data/opening_book.json"
    epochs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    samples = enumerate_samples(load_book(book_path))
    rng = random.Random(0)
    rng.shuffle(samples)
    n_hold = max(1, len(samples) // 5)
    holdout, train = samples[:n_hold], samples[n_hold:]
    standardize(samples, train)  # train 統計で特徴を標準化
    print(f"samples {len(samples)} (train {len(train)} / holdout {len(holdout)}), "
          f"dim {DIM}, epochs {epochs}\n")

    w = train_perceptron(train, epochs)

    def learned(s): return learned_rank(w, s)
    def default(s): return sorted(s.deval, key=lambda c: (s.deval[c], c))
    def center(s): return sorted(s.feats, key=lambda c: (_centrality(c), c))

    print("move 一致率 (book の最善手を選べるか):")
    print(f"  learned   top-1 holdout {match(learned, holdout):.3f}  "
          f"(train {match(learned, train):.3f})  top-3 {match(learned, holdout, 3):.3f}")
    print(f"  default_eval top-1 holdout {match(default, holdout):.3f}  "
          f"top-3 {match(default, holdout, 3):.3f}   <- 既存評価の 1-ply ベースライン")
    print(f"  中央寄り  top-1 holdout {match(center, holdout):.3f}")
    print(f"  ランダム期待 ~{1/16:.3f}")
    print("\n学習重み [open1,open2,open3,parity,reach3,center, "
          "occ_c,occ_e,occ_f,occ_i, play_c,play_e,play_f,play_i]:")
    print("  " + " ".join(f"{x:+.1f}" for x in w))


if __name__ == "__main__":
    main()
