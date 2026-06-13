"""コアの契約テスト (センサー先行)。

最初に書くべきテスト: 勝利ラインがちょうど 76 本であること。
その後、参照実装との一致テスト・既知局面の回帰テストを増やす。
"""
from score_four.lines import all_lines


def _coords(index: int) -> tuple[int, int, int]:
    """セルインデックスを座標 (x, y, z) に戻す (board.py の規約の逆変換)。"""
    z, rem = divmod(index, 16)
    y, x = divmod(rem, 4)
    return x, y, z


def _direction(line: tuple[int, ...]) -> tuple[int, int, int]:
    """ラインの方向ベクトル (各成分の絶対値) を返す。

    4 セルが等差数列 (一定の方向ステップ) をなすことも併せて検証する。
    """
    pts = [_coords(i) for i in line]
    pts.sort()
    step = tuple(b - a for a, b in zip(pts[0], pts[1]))
    for a, b in zip(pts, pts[1:]):
        assert tuple(d2 - d1 for d1, d2 in zip(a, b)) == step
    return tuple(abs(s) for s in step)


def test_there_are_exactly_76_lines() -> None:
    assert len(all_lines()) == 76


def test_lines_are_unique() -> None:
    lines = all_lines()
    assert len({frozenset(line) for line in lines}) == len(lines)


def test_each_line_has_four_valid_distinct_cells() -> None:
    for line in all_lines():
        assert len(line) == 4
        assert len(set(line)) == 4
        assert all(0 <= idx < 64 for idx in line)


def test_line_type_breakdown_is_48_24_4() -> None:
    """軸平行 48 + 平面斜め 24 + 立体対角線 4。

    方向ベクトルの非ゼロ成分数で分類する: 1 成分=軸平行, 2 成分=平面斜め,
    3 成分=立体対角線。立体対角線と段をまたぐ斜めの取りこぼしを検出する。
    """
    counts = {1: 0, 2: 0, 3: 0}
    for line in all_lines():
        direction = _direction(line)
        nonzero = sum(1 for s in direction if s != 0)
        counts[nonzero] += 1

    assert counts == {1: 48, 2: 24, 3: 4}
