"""幾何セル分類 (Phase 10 実験・Commit 1) のテスト。

計画は docs/experiments/geometric_relational_eval.md。この段階では**評価関数は未変更**で、
セルの 4 分類プリミティブ（CORNER/EDGE/FACE/INTERIOR）だけを検証する:
個数 8/24/24/8・勝利ライン所属数 7/4/4/7・3 種類の柱パターン・D4 変換前後の種類一致・
Python/Rust の CELL_TYPE 一致。
"""
from collections import Counter

import pytest

from score_four.board import CELL_LINES
from score_four.evaluate import (
    CELL_LINE_DEGREE,
    CELL_TYPE,
    CELL_TYPE_MASKS,
    COLUMN_CLASS,
    COLUMN_CENTER,
    COLUMN_CORNER,
    COLUMN_EDGE,
    CORNER,
    EDGE,
    FACE,
    INTERIOR,
)
from score_four.symmetry import COL_PERMS


def test_cell_type_counts() -> None:
    """4 分類のセル数: CORNER 8 / EDGE 24 / FACE 24 / INTERIOR 8。"""
    c = Counter(CELL_TYPE)
    assert c[CORNER] == 8
    assert c[EDGE] == 24
    assert c[FACE] == 24
    assert c[INTERIOR] == 8
    assert sum(c.values()) == 64


def test_line_degree_by_type() -> None:
    """各セルの勝利ライン所属数: CORNER/INTERIOR=7, EDGE/FACE=4（実 CELL_LINES と一致）。"""
    expected = {CORNER: 7, INTERIOR: 7, EDGE: 4, FACE: 4}
    for i in range(64):
        assert CELL_LINE_DEGREE[i] == len(CELL_LINES[i]) == expected[CELL_TYPE[i]]
    # 次数総和 = 76 ライン × 4 セル = 304。
    assert sum(CELL_LINE_DEGREE) == 304


def test_cell_type_masks_partition() -> None:
    """種類別マスクが 64 セルを過不足なく分割する。"""
    for t in range(4):
        cells = [i for i in range(64) if CELL_TYPE[i] == t]
        m = 0
        for i in cells:
            m |= 1 << i
        assert CELL_TYPE_MASKS[t] == m
        assert bin(CELL_TYPE_MASKS[t]).count("1") == len(cells)
    union = CELL_TYPE_MASKS[0] | CELL_TYPE_MASKS[1] | CELL_TYPE_MASKS[2] | CELL_TYPE_MASKS[3]
    assert union == (1 << 64) - 1  # 全 64 セルを覆う
    # 互いに素（重なりなし）。
    assert CELL_TYPE_MASKS[0] & CELL_TYPE_MASKS[1] == 0
    assert CELL_TYPE_MASKS[2] & CELL_TYPE_MASKS[3] == 0


def test_column_patterns() -> None:
    """柱クラスごとに底→上のセル種類列が固定（重力を含む幾何）。"""
    patterns: dict[int, list[tuple[int, ...]]] = {
        COLUMN_CORNER: [],
        COLUMN_EDGE: [],
        COLUMN_CENTER: [],
    }
    for col in range(16):
        x, y = col % 4, col // 4
        seq = tuple(CELL_TYPE[z * 16 + y * 4 + x] for z in range(4))
        patterns[COLUMN_CLASS[col]].append(seq)
    assert len(patterns[COLUMN_CORNER]) == 4
    assert all(p == (CORNER, EDGE, EDGE, CORNER) for p in patterns[COLUMN_CORNER])
    assert len(patterns[COLUMN_EDGE]) == 8
    assert all(p == (EDGE, FACE, FACE, EDGE) for p in patterns[COLUMN_EDGE])
    assert len(patterns[COLUMN_CENTER]) == 4
    assert all(p == (FACE, INTERIOR, INTERIOR, FACE) for p in patterns[COLUMN_CENTER])


def test_cell_type_is_d4_invariant() -> None:
    """D4（柱置換・z 不変）でセル種類が保たれる（対称性圧縮 TT・幾何特徴の前提）。"""

    def transform_cell(idx: int, t: int) -> int:
        z, col = divmod(idx, 16)  # col = y*4 + x
        return COL_PERMS[t][col] + z * 16

    for t in range(8):
        for i in range(64):
            assert CELL_TYPE[transform_cell(i, t)] == CELL_TYPE[i]


def test_rust_cell_types_match_python() -> None:
    """Rust の cell_types() が Python の CELL_TYPE と完全一致（言語横断契約）。"""
    rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")
    assert list(rs.cell_types()) == list(CELL_TYPE)
