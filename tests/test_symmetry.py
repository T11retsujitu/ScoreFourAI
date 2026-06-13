"""D4 対称性圧縮の契約テスト。

検証する性質:
  - COL_PERMS が 16 柱の置換 8 個で、恒等を含み群をなす (合成で閉じる)。
  - INV_COL_PERMS が逆置換になっている。
  - 76 本の勝利ラインの集合が各変換で不変 (= 真のゲーム対称性。z 不変で重力も保つ)。
  - transform_bitboard が「同じ列置換を全手に施した対局」と一致する。
  - canonical が D4 軌道で不変 (8 変換すべて同じキー)。
  - line_potential が D4 対称不変 (対称性圧縮の健全性の前提)。
  - 探索スコアが対称像で一致し、一意な最善手が変換で正しく対応する。
"""
import random

from score_four.board import Board
from score_four.evaluate import line_potential
from score_four.lines import all_lines
from score_four.search import best_move, search
from score_four.symmetry import (
    COL_PERMS,
    INV_COL_PERMS,
    canonical,
    transform_bitboard,
)


def test_eight_column_permutations() -> None:
    assert len(COL_PERMS) == 8
    for perm in COL_PERMS:
        assert sorted(perm) == list(range(16))  # 各々が 16 柱の置換
    assert len(set(COL_PERMS)) == 8  # 相異なる
    assert COL_PERMS[0] == tuple(range(16))  # 先頭は恒等


def test_inverse_round_trips() -> None:
    for t in range(8):
        for c in range(16):
            assert INV_COL_PERMS[t][COL_PERMS[t][c]] == c
            assert COL_PERMS[t][INV_COL_PERMS[t][c]] == c


def test_permutations_form_a_group() -> None:
    """合成で閉じる: 任意の2変換の合成も COL_PERMS のどれか。"""
    perm_set = set(COL_PERMS)
    for a in COL_PERMS:
        for b in COL_PERMS:
            comp = tuple(a[b[c]] for c in range(16))
            assert comp in perm_set


def test_winning_lines_are_invariant() -> None:
    """76 ラインの集合が各変換で不変。立体対角線・段またぎ斜めも保たれる。"""
    lines = {frozenset(line) for line in all_lines()}

    def transform_cell(idx: int, t: int) -> int:
        z, rem = divmod(idx, 16)
        col = rem  # rem = y*4 + x = 柱番号
        return COL_PERMS[t][col] + z * 16

    for t in range(8):
        mapped = {frozenset(transform_cell(i, t) for i in line) for line in lines}
        assert mapped == lines


def _play(columns: list[int]) -> Board:
    board = Board()
    for col in columns:
        board.play(col)
    return board


def test_transform_bitboard_matches_replayed_game() -> None:
    """列置換を全手に施して打ち直した対局が、ビットボード変換と一致する。"""
    rng = random.Random(0)
    for _ in range(50):
        seq: list[int] = []
        board = Board()
        for _ in range(rng.randint(0, 20)):
            if board.is_terminal():
                break
            col = rng.choice(board.legal_moves())
            board.play(col)
            seq.append(col)
        for t in range(8):
            image = _play([COL_PERMS[t][c] for c in seq])
            assert image.bb[0] == transform_bitboard(board.bb[0], t)
            assert image.bb[1] == transform_bitboard(board.bb[1], t)


def test_canonical_is_orbit_invariant() -> None:
    """同じ D4 軌道 (8 変換) の局面はすべて同じ正規化キーになる。"""
    rng = random.Random(1)
    for _ in range(50):
        seq: list[int] = []
        board = Board()
        for _ in range(rng.randint(1, 24)):
            if board.is_terminal():
                break
            col = rng.choice(board.legal_moves())
            board.play(col)
            seq.append(col)
        keys = set()
        for t in range(8):
            image = _play([COL_PERMS[t][c] for c in seq])
            keys.add(canonical(image.bb[0], image.bb[1])[0])
        assert len(keys) == 1


def test_line_potential_is_symmetry_invariant() -> None:
    """評価関数が D4 不変 (対称性圧縮の前提)。軌道内で評価値が一定。"""
    rng = random.Random(2)
    for _ in range(60):
        seq: list[int] = []
        board = Board()
        for _ in range(rng.randint(1, 30)):
            if board.is_terminal():
                break
            col = rng.choice(board.legal_moves())
            board.play(col)
            seq.append(col)
        if board.is_terminal():
            continue
        base = line_potential(board)
        for t in range(8):
            image = _play([COL_PERMS[t][c] for c in seq])
            assert line_potential(image) == base


def test_search_score_invariant_under_symmetry() -> None:
    """探索スコアが対称像で一致する (既定の対称不変ヒューリスティック)。"""
    rng = random.Random(3)
    for _ in range(15):
        seq: list[int] = []
        board = Board()
        for _ in range(rng.randint(2, 16)):
            if board.is_terminal():
                break
            col = rng.choice(board.legal_moves())
            board.play(col)
            seq.append(col)
        if board.is_terminal():
            continue
        base_score, _ = search(board, 4)
        for t in range(8):
            image = _play([COL_PERMS[t][c] for c in seq])
            score, _ = search(image, 4)
            assert score == base_score


def test_unique_best_move_maps_under_symmetry() -> None:
    """一意な最善手 (唯一の即勝ち柱) が変換で正しく対応する。"""
    # X: 柱0 を z0,z1,z2 / O: 柱4 を z0,z1,z2。手番 X、柱0 の即勝ちが唯一。
    board = _play([0, 4, 0, 4, 0, 4])
    assert board.turn == 0
    assert board.winning_moves(0) == [0]
    base = best_move(board, 3)
    assert base == 0
    for t in range(8):
        image = _play([COL_PERMS[t][c] for c in [0, 4, 0, 4, 0, 4]])
        assert best_move(image, 3) == COL_PERMS[t][base]
