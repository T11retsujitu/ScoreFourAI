"""軽量学習評価 (Phase 8) のオフライン学習ユーティリティ。

設計 (docs/roadmap.md Phase 8, CLAUDE.md の非目標): AlphaZero/大型 NN/GPU は使わない。
**深い αβ 探索を教師**に、CPU で高速・決定的に推論できる小さな線形モデルを学習する。

- 推論側 (エンジンが使う): `evaluate.features` / `evaluate.learned_eval` は **整数のみ**で
  決定的・D4 不変。Rust 側 (`score_four_rs.eval_learned`) と同値 (契約テスト済み)。
- 学習側 (このモジュール): 浮動小数の最小二乗で連続重みを求め、**整数へ量子化**してから
  エンジンへ渡す。浮動小数はオフライン学習のみで、エンジン実行時には現れない (非決定性回避)。

外部依存なし (numpy 不使用)。最小二乗は正規方程式 + 部分ピボット Gauss 消去で解く
(特徴量は NF=6 個なので 6x6 の自明な系)。教師ラベルは Rust 拡張があれば使い、無ければ
純 Python 探索にフォールバックする。

重要な前提:
  - 特徴量は先手0視点の差分 (符号反転対称)。教師スコアも先手0視点へ正規化してから学習する
    ので、学習評価は手番入れ替えで符号反転する (= バイアス項なし)。これにより D4/符号対称性が
    保たれ、対称性圧縮 TT と矛盾しない。
  - 強制決着 (|score| > MATE_LO) の局面は除外する。詰みは探索のメイト検出が扱うので、静的
    評価が真似る必要はなく、巨大なメイト値が回帰を支配するのを防ぐ。
"""

import random

from .board import Board
from .evaluate import NF, features
from .search import MATE_LO
from .search import search as py_search

try:  # 教師ラベル付けは重いので Rust があれば使う (無くても動く)
    import score_four_rs as _rs
except ImportError:  # pragma: no cover - 拡張未ビルド環境
    _rs = None


def sample_positions(
    n: int, max_plies: int = 20, seed: int = 0
) -> list[tuple[int, int]]:
    """ランダム対局から相異なる非終端局面を n 個サンプルする (D4 正規化で重複除去)。

    各ロールアウトの途中局面 (ply>=2) を候補に採り、canonical キーで重複を除く。
    多様な中盤局面を集めるための種。返り値は (b0, b1) のビットボード対。
    """
    rng = random.Random(seed)
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    attempts = 0
    while len(out) < n and attempts < n * 200:
        attempts += 1
        board = Board()
        depth = rng.randint(2, max_plies)
        for _ in range(depth):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if board.is_terminal():
            continue
        if _rs is not None:
            key = _rs.canonical(board.bb[0], board.bb[1])[0]
        else:  # pragma: no cover - 純 Python 経路
            from .symmetry import canonical

            key = canonical(board.bb[0], board.bb[1])[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((board.bb[0], board.bb[1]))
    return out


def teacher_label(b0: int, b1: int, depth: int) -> int:
    """局面 (b0,b1) を深さ depth の探索で評価し、**先手0視点**のスコアを返す。

    探索は手番側視点の値を返すので、後手番なら符号反転して先手0視点へ揃える。
    Rust 拡張があれば使い (高速)、無ければ純 Python 探索にフォールバックする。
    """
    board = Board.from_bitboards(b0, b1)
    if _rs is not None:
        r = _rs.analyze(b0, b1, depth)
        score = int(r["score"])
    else:  # pragma: no cover - 純 Python 経路
        score, _ = py_search(board, depth)
    return score if board.turn == 0 else -score


def build_dataset(
    positions: list[tuple[int, int]], depth: int
) -> tuple[list[list[int]], list[int]]:
    """局面列から (X=特徴量行列, y=教師スコア) を作る。強制決着の局面は除外。

    X[i] は先手0視点の整数特徴量 (長さ NF)、y[i] は先手0視点の教師スコア。
    |teacher| > MATE_LO (詰みを読み切った局面) は静的評価の対象外なので落とす。
    """
    x: list[list[int]] = []
    y: list[int] = []
    for b0, b1 in positions:
        label = teacher_label(b0, b1, depth)
        if abs(label) > MATE_LO:
            continue  # 強制決着は静的評価の範囲外
        x.append(features(Board.from_bitboards(b0, b1)))
        y.append(label)
    return x, y


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """線形系 a·w = b を部分ピボット Gauss 消去で解く (a は正方・破壊的)。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            continue  # 退化列はスキップ (重み 0 に倒れる)
        m[col], m[piv] = m[piv], m[col]
        inv = 1.0 / m[col][col]
        for j in range(col, n + 1):
            m[col][j] *= inv
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col]
                for j in range(col, n + 1):
                    m[r][j] -= f * m[col][j]
    return [m[i][n] for i in range(n)]


def fit_linear(
    x: list[list[int]], y: list[int], ridge: float = 1e-6
) -> list[float]:
    """最小二乗で連続重み w (長さ NF) を求める。バイアス項なし (符号対称を保つ)。

    正規方程式 (XᵀX + ridge·I) w = Xᵀy を解く。ridge は数値安定化の微小正則化。
    """
    nf = NF
    ata = [[0.0] * nf for _ in range(nf)]
    aty = [0.0] * nf
    for row, target in zip(x, y, strict=True):
        for i in range(nf):
            ri = row[i]
            aty[i] += ri * target
            for j in range(nf):
                ata[i][j] += ri * row[j]
    for i in range(nf):
        ata[i][i] += ridge
    return _solve(ata, aty)


def quantize(weights: list[float], q: int = 100) -> list[int]:
    """連続重みを整数へ量子化する (最大絶対値が約 q になるよう一様スケール)。

    一様スケールは手の選択 (argmax) を変えない (探索内の比較のみ)。整数化することで
    エンジン実行時は浮動小数を一切使わない (決定論)。すべて 0 のときは 0 ベクトル。
    """
    peak = max((abs(w) for w in weights), default=0.0)
    if peak < 1e-12:
        return [0] * len(weights)
    scale = q / peak
    return [round(w * scale) for w in weights]


def r2_score(x: list[list[int]], y: list[int], weights: list[float]) -> float:
    """決定係数 R² (学習当てはまりの目安)。weights は連続/整数どちらでも可。"""
    if not y:
        return 0.0
    mean = sum(y) / len(y)
    ss_tot = sum((t - mean) ** 2 for t in y)
    ss_res = 0.0
    for row, target in zip(x, y, strict=True):
        pred = sum(w * v for w, v in zip(weights, row, strict=True))
        ss_res += (target - pred) ** 2
    if ss_tot < 1e-12:
        return 0.0
    return 1.0 - ss_res / ss_tot
