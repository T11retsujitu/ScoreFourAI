"""board.py の契約テスト (センサー先行)。

ビットボードのコア (着手生成・増分勝利判定) を、3 次元配列で愚直に判定する
独立した参照実装と突き合わせる。ランダム対局を多数回し、全局面で
着手可能手・勝者・終局判定が一致することを property test で保証する。

参照実装は lines.py のラインマスクに依存せず、置いたセルから 13 方向へ
連続数を数える方式 (Connect Four 風の素朴な判定) を使う。これにより
ビットボード側 (lines.py 由来のマスクで増分判定) との交差検証になる。
"""
import random
from itertools import product

from score_four.board import Board

# 13 方向 (26 方向のうち、逆向きを正規化して半分にしたもの)。
_DIRS = [
    d
    for d in product((-1, 0, 1), repeat=3)
    if d != (0, 0, 0) and d > tuple(-c for c in d)
]


class NaiveBoard:
    """3 次元配列による参照実装。勝利判定はラインマスクを使わず素朴に数える。"""

    def __init__(self) -> None:
        # grid[z][y][x] in {None, 0, 1}
        self.grid = [[[None] * 4 for _ in range(4)] for _ in range(4)]
        self.heights = [0] * 16
        self.turn = 0
        self.winner: int | None = None

    def legal_moves(self) -> list[int]:
        if self.winner is not None:
            return []
        return [c for c in range(16) if self.heights[c] < 4]

    def is_full(self) -> bool:
        return all(h == 4 for h in self.heights)

    def is_terminal(self) -> bool:
        return self.winner is not None or self.is_full()

    def play(self, column: int) -> bool:
        x, y = column % 4, column // 4
        z = self.heights[column]
        player = self.turn
        self.grid[z][y][x] = player
        self.heights[column] += 1
        won = self._wins(x, y, z, player)
        if won:
            self.winner = player
        self.turn ^= 1
        return won

    def _wins(self, x: int, y: int, z: int, player: int) -> bool:
        for dx, dy, dz in _DIRS:
            count = 1
            for sign in (1, -1):
                cx, cy, cz = x + sign * dx, y + sign * dy, z + sign * dz
                while (
                    0 <= cx < 4
                    and 0 <= cy < 4
                    and 0 <= cz < 4
                    and self.grid[cz][cy][cx] == player
                ):
                    count += 1
                    cx += sign * dx
                    cy += sign * dy
                    cz += sign * dz
            if count >= 4:
                return True
        return False


def test_directions_cover_13_axes() -> None:
    assert len(_DIRS) == 13


def test_random_games_match_reference() -> None:
    """ランダム対局を多数回し、全局面で参照実装と一致することを検証する。"""
    saw_win = False
    for seed in range(300):
        rng = random.Random(seed)
        board = Board()
        naive = NaiveBoard()

        while not board.is_terminal():
            assert sorted(board.legal_moves()) == sorted(naive.legal_moves())
            assert board.winner == naive.winner
            assert board.is_terminal() == naive.is_terminal()

            mover = board.turn
            column = rng.choice(board.legal_moves())
            won_board = board.play(column)
            won_naive = naive.play(column)

            # 増分判定 (ビットボード) と素朴判定 (3次元配列) の一致。
            assert won_board == won_naive
            if won_board:
                assert board.winner == mover

        # 終局時の最終一致。
        assert board.winner == naive.winner
        assert board.is_terminal() and naive.is_terminal()
        assert sorted(board.legal_moves()) == sorted(naive.legal_moves()) == []

        if board.winner is not None:
            saw_win = True

    # ランダム対局なので勝ち局面は必ず出る (引き分けは稀なので必須にしない)。
    assert saw_win


def test_undo_restores_initial_state() -> None:
    """ランダム対局を最後まで打ってから全手 undo すると初期局面に戻る。"""
    for seed in range(80):
        rng = random.Random(10_000 + seed)
        board = Board()
        played = 0
        while not board.is_terminal():
            board.play(rng.choice(board.legal_moves()))
            played += 1
        for _ in range(played):
            board.undo()
        assert board.bb == [0, 0]
        assert list(board.heights) == [0] * 16
        assert board.turn == 0
        assert board.winner is None
        assert board.num_moves == 0


def test_undo_midgame_matches_replay() -> None:
    """途中まで打って 1 手 undo した局面が、その手を打たない再生と一致する。"""
    rng = random.Random(42)
    board = Board()
    moves: list[int] = []
    for _ in range(12):
        if board.is_terminal():
            break
        col = rng.choice(board.legal_moves())
        board.play(col)
        moves.append(col)

    board.undo()
    moves.pop()

    replay = Board()
    for col in moves:
        replay.play(col)

    assert board.bb == replay.bb
    assert list(board.heights) == list(replay.heights)
    assert board.turn == replay.turn
    assert board.winner == replay.winner


# --- 既知局面の回帰テスト ------------------------------------------------


def _play_sequence(columns: list[int]) -> Board:
    board = Board()
    for col in columns:
        board.play(col)
    return board


def test_vertical_win() -> None:
    """同じ柱に先手が4つ縦に積んで勝つ。"""
    board = _play_sequence([0, 1, 0, 1, 0, 1, 0])
    assert board.winner == 0


def test_horizontal_win_along_x() -> None:
    """z=0 平面で先手が x 軸方向に4つ並べて勝つ。"""
    board = _play_sequence([0, 4, 1, 5, 2, 6, 3])
    assert board.winner == 0


def test_planar_diagonal_win() -> None:
    """z=0 平面の対角線 (柱 0,5,10,15) で先手が勝つ。"""
    board = _play_sequence([0, 1, 5, 2, 10, 3, 15])
    assert board.winner == 0


def test_space_diagonal_win() -> None:
    """段をまたぐ立体対角線 (0,0,0)-(1,1,1)-(2,2,2)-(3,3,3) で先手が勝つ。

    CLAUDE.md が取りこぼし注意として挙げる、最も間違えやすいケース。
    """
    board = _play_sequence([0, 5, 5, 10, 15, 10, 10, 15, 15, 3, 15])
    assert board.winner == 0


def test_not_won_when_blocked() -> None:
    """間に相手のコマが入ると勝ちにならない。"""
    board = _play_sequence([0, 0, 1, 2, 3])  # 先手は柱0(z0),1(z0)... 連続しない
    assert board.winner is None


# --- winning_moves / has_winning_move (脅威枝刈りの土台) -----------------


def _naive_winning_columns(board: Board, player: int) -> list[int]:
    """参照: 各空き柱に player を試し置きして勝つかを undo で確かめる。"""
    if board.winner is not None:
        return []
    cols: list[int] = []
    for col in range(16):
        if board.heights[col] >= 4:
            continue
        probe = board.copy()
        probe.turn = player  # player の手番として試す
        if probe.play(col):
            cols.append(col)
    return cols


def test_winning_moves_match_naive_probe() -> None:
    """ランダム局面で winning_moves が「試し置き」参照と一致する。"""
    for seed in range(200):
        rng = random.Random(50_000 + seed)
        board = Board()
        while not board.is_terminal():
            for player in (0, 1):
                expected = sorted(_naive_winning_columns(board, player))
                assert sorted(board.winning_moves(player)) == expected
                assert board.has_winning_move(player) == bool(expected)
            board.play(rng.choice(board.legal_moves()))


def test_winning_moves_detects_vertical_threat() -> None:
    """柱0に先手が3つ。先手は柱0で即勝ちできる。"""
    board = _play_sequence([0, 1, 0, 1, 0, 1])
    assert board.winning_moves(0) == [0]
    assert board.has_winning_move(0)


def test_winning_moves_double_threat() -> None:
    """先手が z=0 平面で L 字に並び、柱3 と 柱12 の両方が即勝ちになるダブルリーチ。

    先手 X: 柱0,1,2 (横ライン y=0,z=0) と 柱0,4,8 (縦ライン x=0,z=0)。
    柱3 で {0,1,2,3}、柱12 で {0,4,8,12} が完成する2柱同時脅威。
    後手 O は脅威柱 (3,12) を避けた無関係な柱に置く。
    """
    board = _play_sequence([0, 5, 1, 6, 2, 7, 4, 9, 8, 10])
    assert board.turn == 0
    assert sorted(board.winning_moves(0)) == [3, 12]
    assert board.has_winning_move(0)
