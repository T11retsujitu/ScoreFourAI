"""ビットボード表現・着手生成・勝利判定。

セルのインデックス規約 (このプロジェクト唯一の定義):
    index = z * 16 + y * 4 + x    # x,y in 0..3 (基盤), z in 0..3 (高さ)
着手は「柱(列) の選択」のみ。コマはその柱の最下段の空きに落ちる。
勝利判定は直前に置いたセルを通る線だけを見る増分判定にする。

柱(列) の番号付け:
    col = y * 4 + x               # 0..15
    柱 col のセルは index = col + z * 16 (z = 0..3, 下から上へ)
各色の占有を 64bit 整数 (bb[0], bb[1]) で保持する。bit `index` が立って
いれば、そのセルがその色のコマで埋まっている。
"""

import random as _random

from .lines import all_lines

N = 4
NUM_COLUMNS = 16
NUM_CELLS = 64


def _build_line_tables() -> tuple[list[int], list[tuple[int, ...]]]:
    """76 ラインのビットマスクと、各セルを通るラインの一覧を構築する。

    Returns:
        line_masks: 各ラインの 64bit マスク (長さ 76)。
        cell_lines: cell_lines[idx] は セル idx を含むラインマスクのタプル。
            増分勝利判定で「直前に置いたセルを通る線」だけを走査するために使う。
    """
    line_masks: list[int] = []
    cell_lines: list[list[int]] = [[] for _ in range(NUM_CELLS)]
    for line in all_lines():
        mask = 0
        for idx in line:
            mask |= 1 << idx
        line_masks.append(mask)
        for idx in line:
            cell_lines[idx].append(mask)
    return line_masks, [tuple(masks) for masks in cell_lines]


LINE_MASKS, CELL_LINES = _build_line_tables()


def _build_zobrist() -> list[list[int]]:
    """各 (色, セル) に割り当てる 64bit 乱数表を構築する。

    置換表のキーに使う増分ハッシュ用。乱数はシード固定で、同一バイナリでは
    常に同じ表になる (CLAUDE.md: 探索の非決定性はテストで排除)。
    """
    rng = _random.Random(0x5C04E_F0E4)
    return [[rng.getrandbits(64) for _ in range(NUM_CELLS)] for _ in range(2)]


ZOBRIST = _build_zobrist()


def landing_cell(column: int, height: int) -> int:
    """柱 column の現在の高さ height のとき、次に落ちるコマのセルインデックス。"""
    return column + height * 16


class Board:
    """4x4x4 Score Four の局面 (重力あり)。

    着手は柱(列) 0..15 の選択。`play` で着手し `undo` で取り消せる
    (探索の make/unmake 用)。勝敗は属性 `winner` (None / 0 / 1) で持つ。
    """

    __slots__ = ("bb", "heights", "turn", "winner", "key", "_history")

    def __init__(self) -> None:
        self.bb: list[int] = [0, 0]
        self.heights = bytearray(NUM_COLUMNS)  # 各柱に積まれたコマ数 0..4
        self.turn: int = 0  # 手番のプレイヤー (0 = 先手)
        self.winner: int | None = None
        self.key: int = 0  # Zobrist ハッシュ (占有のみ; 手番は手数の偶奇で一意)
        self._history: list[tuple[int, int | None]] = []  # (column, 着手前の winner)

    # --- 照会 (純粋) -----------------------------------------------------

    def legal_moves(self) -> list[int]:
        """着手可能な柱 (満杯でない列) のリスト。勝負がついていれば空。"""
        if self.winner is not None:
            return []
        return [c for c in range(NUM_COLUMNS) if self.heights[c] < N]

    def _completes_line(self, player: int, idx: int) -> bool:
        """player がセル idx に置いたら idx を通る線で4が揃うか (純粋)。"""
        occ = self.bb[player] | (1 << idx)
        for mask in CELL_LINES[idx]:
            if occ & mask == mask:
                return True
        return False

    def winning_moves(self, player: int) -> list[int]:
        """player が今すぐ着手して4を完成できる柱の一覧 (重複なし・純粋)。

        各柱は着地セルが1つだけなので、即勝ち脅威は柱ごとに高々1つ。脅威ベースの
        強制手枝刈りで「相手の即勝ち柱」を数えるために使う。決着後は空。
        """
        if self.winner is not None:
            return []
        res: list[int] = []
        for c in range(NUM_COLUMNS):
            h = self.heights[c]
            if h < N and self._completes_line(player, c + h * 16):
                res.append(c)
        return res

    def has_winning_move(self, player: int) -> bool:
        """player に即勝ち手が1つでもあるか (winning_moves の早期脱出版・純粋)。"""
        if self.winner is not None:
            return False
        for c in range(NUM_COLUMNS):
            h = self.heights[c]
            if h < N and self._completes_line(player, c + h * 16):
                return True
        return False

    def is_full(self) -> bool:
        """全 64 マスが埋まっているか。"""
        return len(self._history) == NUM_CELLS

    def is_terminal(self) -> bool:
        """勝敗が確定したか、または引き分け (満杯) か。"""
        return self.winner is not None or self.is_full()

    @property
    def num_moves(self) -> int:
        """これまでに置かれたコマの総数。"""
        return len(self._history)

    # --- 更新 (副作用) ---------------------------------------------------

    def play(self, column: int) -> bool:
        """手番のプレイヤーが柱 column に着手する。勝ちを決めた手なら True。

        コマは柱の最下段の空きに落ちる。満杯の柱や決着後の着手は ValueError。
        """
        if self.winner is not None:
            raise ValueError("game is already decided")
        height = self.heights[column]
        if height >= N:
            raise ValueError(f"column {column} is full")

        player = self.turn
        idx = column + height * 16
        self.bb[player] |= 1 << idx
        self.key ^= ZOBRIST[player][idx]
        self.heights[column] = height + 1
        self._history.append((column, self.winner))

        won = self._wins_through(player, idx)
        if won:
            self.winner = player
        self.turn = player ^ 1
        return won

    def undo(self) -> None:
        """直前の着手を取り消す。"""
        column, prev_winner = self._history.pop()
        self.turn ^= 1  # 着手したプレイヤーへ戻す
        player = self.turn
        height = self.heights[column] - 1
        self.heights[column] = height
        idx = column + height * 16
        self.bb[player] &= ~(1 << idx)
        self.key ^= ZOBRIST[player][idx]
        self.winner = prev_winner

    # --- 勝利判定 (増分) -------------------------------------------------

    def _wins_through(self, player: int, idx: int) -> bool:
        """セル idx に置いた直後、idx を通るラインで player が4つ揃ったか。"""
        occupied = self.bb[player]
        for mask in CELL_LINES[idx]:
            if occupied & mask == mask:
                return True
        return False

    # --- 補助 ------------------------------------------------------------

    def copy(self) -> "Board":
        """局面の独立したコピーを返す。"""
        new = Board()
        new.bb = self.bb.copy()
        new.heights = bytearray(self.heights)
        new.turn = self.turn
        new.winner = self.winner
        new.key = self.key
        new._history = self._history.copy()
        return new

    def __str__(self) -> str:
        rows = []
        marks = {None: ".", 0: "X", 1: "O"}
        for z in range(N - 1, -1, -1):
            line_cells = []
            for y in range(N):
                row = []
                for x in range(N):
                    idx = z * 16 + y * 4 + x
                    bit = 1 << idx
                    if self.bb[0] & bit:
                        row.append(marks[0])
                    elif self.bb[1] & bit:
                        row.append(marks[1])
                    else:
                        row.append(marks[None])
                line_cells.append("".join(row))
            rows.append(f"z={z}: " + "  ".join(line_cells))
        return "\n".join(rows)
