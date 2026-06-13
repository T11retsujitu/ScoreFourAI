"""76 本の勝利ラインを生成する。

実装の最優先事項: まず総当たりで全ラインを列挙し、本数が必ず 76 本
(軸 48 + 平面の斜め 24 + 立体対角線 4) であることをテストで保証すること。
セルのインデックス規約は board.py の docstring を唯一の定義として参照する::

    index = z * 16 + y * 4 + x    # x,y in 0..3 (基盤), z in 0..3 (高さ)
"""

from itertools import product

N = 4  # 各軸のサイズ (4x4x4)


def cell_index(x: int, y: int, z: int) -> int:
    """座標 (x, y, z) をセルインデックスに変換する (board.py の規約に従う)。"""
    return z * 16 + y * 4 + x


def all_lines() -> list[tuple[int, ...]]:
    """全 76 本の勝利ラインを、セルインデックスの 4-tuple のリストで返す。

    手法は総当たり: 全 64 セルを始点に、26 方向 (各成分 -1/0/+1 で全ゼロ以外)
    へ 4 マス伸ばし、4 マスすべてが盤内に収まる組だけを採用する。1 本のライン
    は順方向・逆方向の両端から 2 度生成されるため、セル集合で正規化して重複を
    除く。結果は決定的になるよう整列して返す。
    """
    directions = [d for d in product((-1, 0, 1), repeat=3) if d != (0, 0, 0)]

    seen: set[frozenset[int]] = set()
    lines: list[tuple[int, ...]] = []
    for x, y, z in product(range(N), repeat=3):
        for dx, dy, dz in directions:
            cells = []
            for i in range(N):
                cx, cy, cz = x + i * dx, y + i * dy, z + i * dz
                if not (0 <= cx < N and 0 <= cy < N and 0 <= cz < N):
                    break
                cells.append(cell_index(cx, cy, cz))
            else:
                key = frozenset(cells)
                if key not in seen:
                    seen.add(key)
                    lines.append(tuple(sorted(cells)))

    return sorted(lines)
