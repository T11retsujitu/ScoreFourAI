"""軽量学習評価 (Phase 8) の学習ユーティリティ test (learn.py)。

学習側は浮動小数を使うが、ここで検証するのは「線形回帰が正しく解けること」「量子化が
一様スケール (= 手の選択を変えない) であること」「サンプリングが非終端・D4 重複なし」など
の決定的な性質。評価器自体の D4 不変性・整数性・Rust 一致は test_symmetry / test_evaluate /
test_rust_search で担保する。
"""
import random

from score_four.board import Board
from score_four.evaluate import NF
from score_four.learn import (
    _solve,
    build_dataset,
    fit_linear,
    fit_logistic,
    logistic_accuracy,
    quantize,
    r2_score,
    sample_positions,
    standardize,
)


def test_solve_linear_system() -> None:
    # 2x + y = 5 ; x + 3y = 10  -> x=1, y=3
    w = _solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0])
    assert round(w[0], 9) == 1.0
    assert round(w[1], 9) == 3.0


def test_fit_recovers_exact_linear_target() -> None:
    """目標が特徴量の厳密な線形結合なら、回帰は元の重みを復元し R^2=1。"""
    rng = random.Random(0)
    true = [1, 5, 25, -8, 3, 2]
    x = [[rng.randint(-5, 5) for _ in range(NF)] for _ in range(300)]
    y = [sum(a * b for a, b in zip(true, row, strict=True)) for row in x]
    w = fit_linear(x, y)
    assert all(abs(wi - ti) < 1e-6 for wi, ti in zip(w, true, strict=True))
    assert abs(r2_score(x, y, w) - 1.0) < 1e-9


def test_quantize_is_uniform_scaling() -> None:
    """量子化は一様スケール: 最大絶対値が約 q、相対比を保つ。全 0 は 0 ベクトル。"""
    iw = quantize([1.0, 5.0, 25.0, -8.0, 0.0, 0.0], q=100)
    assert iw == [4, 20, 100, -32, 0, 0]  # ×4 の一様スケール (= パリティ重み)
    assert max(abs(v) for v in iw) == 100
    assert quantize([0.0] * NF) == [0] * NF


def test_quantize_rounds_within_half_step() -> None:
    """量子化は wf×scale を四捨五入したもの: 各重みは厳密スケールから 0.5 以内。

    これが量子化を「一様スケール (= 手の選択を保つ) + 微小丸め」と特徴づける。整数比に
    既になっている重み (パリティ等) では丸め誤差ゼロで順序を完全に保つ。
    """
    wf = [0.7, 4.9, 24.3, -7.6, 1.2, 0.4]
    iw = quantize(wf, q=100)
    scale = 100 / max(abs(w) for w in wf)
    assert all(abs(i - w * scale) <= 0.5 for i, w in zip(iw, wf, strict=True))
    # 整数比の重みは厳密な一様スケールになり丸め誤差ゼロ。
    assert quantize([2.0, 10.0, 50.0, -16.0, 0.0, 0.0], q=100) == [4, 20, 100, -32, 0, 0]


def test_sample_positions_are_unique_nonterminal() -> None:
    """サンプルは非終端で D4 正規化キーが相異なる (重複なし)。"""
    from score_four.symmetry import canonical

    positions = sample_positions(60, max_plies=20, seed=1)
    assert len(positions) == 60
    keys = set()
    for b0, b1 in positions:
        b = Board.from_bitboards(b0, b1)
        assert not b.is_terminal()
        keys.add(canonical(b0, b1)[0])
    assert len(keys) == 60  # 全て相異なる軌道


def test_build_dataset_drops_forced_results() -> None:
    """build_dataset は強制決着を落とし、特徴量長 NF の行列を返す。"""
    positions = sample_positions(30, max_plies=16, seed=2)
    x, y = build_dataset(positions, depth=4)
    assert len(x) == len(y)
    assert len(x) <= len(positions)
    assert all(len(row) == NF for row in x)


def test_standardize_zero_mean_unit_std() -> None:
    """standardize は train 統計で各列を平均0・分散1 にする (定数列は std=1)。"""
    import statistics

    x = [[1.0, 5.0], [3.0, 5.0], [5.0, 5.0], [7.0, 5.0]]
    xs, mean, std = standardize(x)
    cols = list(zip(*xs, strict=True))
    assert abs(statistics.mean(cols[0])) < 1e-9
    assert abs(statistics.pstdev(cols[0]) - 1.0) < 1e-9
    assert std[1] == 1.0  # 定数列は 0 でなく 1 に倒す
    assert all(v == 0.0 for v in cols[1])  # 定数列は中心化で全ゼロ


def test_fit_logistic_separates_linearly_separable_data() -> None:
    """線形分離可能なデータで高い的中率に達する (勾配降下が正しく収束)。"""
    rng = random.Random(0)
    true = [2.0, -3.0]
    x = []
    y = []
    for _ in range(400):
        row = [rng.uniform(-1.0, 1.0) for _ in range(2)]
        x.append(row)
        z = sum(t * v for t, v in zip(true, row, strict=True))
        y.append(1.0 if z > 0 else 0.0)
    w = fit_logistic(x, y, epochs=400, lr=0.5, l2=1e-4)
    assert logistic_accuracy(x, y, w) > 0.95
    # 学習した境界の向きが真の重みに揃う (符号一致)。
    assert (w[0] > 0) and (w[1] < 0)


def test_logistic_accuracy_ignores_draw_labels() -> None:
    """引分ラベル 0.5 は的中率の母数から除外される。"""
    x = [[1.0], [-1.0], [0.0]]
    y = [1.0, 0.0, 0.5]  # 3 つ目は引分
    w = [10.0]  # x>0 -> p~1, x<0 -> p~0 で 2 件とも的中
    assert logistic_accuracy(x, y, w) == 1.0
