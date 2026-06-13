"""D4 対称性 (8 重) による局面の正規化。

Score Four は重力が z 軸固定なので、ゲームを保つ空間対称性は底面 (x, y) の
二面体群 **D4 (位数 8: 回転4 + 鏡映4)**。z を動かさないので重力制約を壊さず、
76 本の勝利ラインの集合もこの 8 変換で不変 (= 真のゲーム対称性)。

これを使って局面を 8 変換の最小形へ正規化し、置換表のキーにすることで実効
状態空間を約 1/8 に圧縮する。

セルのインデックス規約は board.py の docstring を唯一の定義として参照する::

    index = z * 16 + y * 4 + x      # col = y*4 + x,  index = col + z*16

各変換は (x, y) のみを写し z は不変。よって 4 枚の z 平面はすべて同じ 16 個の
柱 (列) の置換を受ける。これを利用し、16bit 平面 -> 16bit 平面 の置換テーブルを
事前計算して、64bit ビットボードを 4 回のルックアップで変換する。
"""

N = 4
NUM_COLUMNS = 16
_PLANE_MASK = 0xFFFF

# D4 の 8 元を (x, y) -> (x', y') の写像として定義 (中心 1.5 まわり)。
_D4_MAPS = (
    lambda x, y: (x, y),          # 恒等
    lambda x, y: (y, N - 1 - x),  # 90度回転
    lambda x, y: (N - 1 - x, N - 1 - y),  # 180度回転
    lambda x, y: (N - 1 - y, x),  # 270度回転
    lambda x, y: (N - 1 - x, y),  # x 反転
    lambda x, y: (x, N - 1 - y),  # y 反転
    lambda x, y: (y, x),          # 主対角 (転置)
    lambda x, y: (N - 1 - y, N - 1 - x),  # 反対角
)


def _build_column_perms() -> tuple[tuple[int, ...], ...]:
    """各変換の柱(列)置換 COL_PERMS[t][c] = 変換後の柱番号 を作る。"""
    perms: list[tuple[int, ...]] = []
    for fn in _D4_MAPS:
        perm = [0] * NUM_COLUMNS
        for c in range(NUM_COLUMNS):
            x, y = c % N, c // N
            nx, ny = fn(x, y)
            perm[c] = ny * N + nx
        perms.append(tuple(perm))
    return tuple(perms)


COL_PERMS: tuple[tuple[int, ...], ...] = _build_column_perms()


def _build_inverse_perms() -> tuple[tuple[int, ...], ...]:
    """INV_COL_PERMS[t][m] = COL_PERMS[t] で m に写る元の柱 (逆置換)。"""
    inverses: list[tuple[int, ...]] = []
    for perm in COL_PERMS:
        inv = [0] * NUM_COLUMNS
        for c, p in enumerate(perm):
            inv[p] = c
        inverses.append(tuple(inv))
    return tuple(inverses)


INV_COL_PERMS: tuple[tuple[int, ...], ...] = _build_inverse_perms()


def _build_plane_perms() -> tuple[tuple[int, ...], ...]:
    """各変換の 16bit 平面置換テーブル PLANE_PERM[t][plane] を事前計算する。

    plane は 16 柱の占有ビット (bit c が柱 c)。出力は柱を COL_PERMS[t] で写した
    平面。最下位ビットを 1 つ外しながら部分和を再利用して O(2^16) で構築する。
    """
    tables: list[tuple[int, ...]] = []
    for perm in COL_PERMS:
        bitmap = [1 << perm[c] for c in range(NUM_COLUMNS)]
        table = [0] * (1 << NUM_COLUMNS)
        for plane in range(1, 1 << NUM_COLUMNS):
            low = plane & (-plane)
            c = low.bit_length() - 1
            table[plane] = table[plane ^ low] | bitmap[c]
        tables.append(tuple(table))
    return tuple(tables)


PLANE_PERM: tuple[tuple[int, ...], ...] = _build_plane_perms()


def transform_bitboard(bb: int, t: int) -> int:
    """64bit ビットボード bb を変換 t で写す (z 平面ごとに同じ列置換)。"""
    table = PLANE_PERM[t]
    return (
        table[bb & _PLANE_MASK]
        | (table[(bb >> 16) & _PLANE_MASK] << 16)
        | (table[(bb >> 32) & _PLANE_MASK] << 32)
        | (table[(bb >> 48) & _PLANE_MASK] << 48)
    )


def canonical(b0: int, b1: int) -> tuple[int, int]:
    """局面 (b0, b1) の正規化キーと、それを与える変換 t を返す。

    8 変換すべてを試し ``(b0' << 64) | b1'`` が最小になる形を採用する。同じ D4
    軌道の局面は必ず同じキーになる。返り値の t は「現局面 -> 正規形」へ写す変換で、
    最善手を正規形/現局面の座標系へ読み替えるのに使う。手番は両色の占有から一意
    なのでキーに含めなくてよい。
    """
    best_key = -1
    best_t = 0
    for t in range(8):
        cand = (transform_bitboard(b0, t) << 64) | transform_bitboard(b1, t)
        if best_key < 0 or cand < best_key:
            best_key = cand
            best_t = t
    return best_key, best_t
