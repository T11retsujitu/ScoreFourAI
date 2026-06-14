"""Threat Quiescence Search のテスト (強化 Phase 2)。

§11 に沿って 正常系 / 健全性 / 比較 を確認する。quiescence は窓非依存の純粋関数で、
qdepth=0 のとき探索は従来どおり (静的評価) であることを前提に、qdepth>0 で深さ0でも
即勝ち・唯一の受け・ダブル即勝ち負け・フォーク生成を認識することを検証する。
"""
import random

from score_four.board import Board
from score_four.evaluate import default_eval
from score_four.search import (
    MATE_LO,
    fork_moves,
    quiescence,
    search,
)
from score_four.symmetry import COL_PERMS


def _play(cols: list[int]) -> Board:
    b = Board()
    for c in cols:
        b.play(c)
    return b


# --- 正常系 ----------------------------------------------------------------


def test_quiescence_recognizes_own_immediate_win() -> None:
    b = _play([0, 1, 0, 1, 0, 1])  # 先手 col0 リーチ、先手番 → col0 で即勝ち
    assert quiescence(b, 8, default_eval) > MATE_LO


def test_quiescence_recognizes_opponent_double_threat_as_loss() -> None:
    # 後手番で、先手が柱3と柱12の二重即勝ち脅威を持つ局面。
    b = _play([0, 5, 1, 6, 2, 7, 4, 9, 8])  # 先手 0,1,2,4,8 / 後手 5,6,7,9
    assert b.turn == 1
    assert len(b.winning_moves(0)) >= 2     # 先手のダブル即勝ち
    assert quiescence(b, 8, default_eval) < -MATE_LO


def test_quiescence_finds_fork_win() -> None:
    """深さ0の静穏化でフォーク (ダブルリーチ生成) を読み切る。"""
    b = _play([1, 2, 4, 8, 6, 11, 9, 14])  # 先手番、柱5でフォーク
    assert b.turn == 0
    assert 5 in fork_moves(b, 0)
    assert quiescence(b, 8, default_eval) > MATE_LO


def test_shallow_search_with_quiescence_finds_tactic() -> None:
    """深さ1探索でも quiescence 有りならフォーク勝ちを選ぶ (無しでは読めない先の戦術)。"""
    b = _play([1, 2, 4, 8, 6, 11, 9, 14])
    score_q, move_q = search(b, 1, qdepth=8)
    assert move_q == 5
    assert score_q > MATE_LO


# --- 健全性 ----------------------------------------------------------------


def test_static_position_matches_static_eval() -> None:
    """脅威もフォーク手も無い静穏局面では quiescence == 静的評価。"""
    rng = random.Random(0)
    checked = 0
    for _ in range(120):
        b = Board()
        for _ in range(rng.randint(0, 8)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if b.is_terminal():
            continue
        me = b.turn
        if b.has_winning_move(me) or b.winning_moves(me ^ 1) or fork_moves(b, me):
            continue  # 静穏でない
        assert quiescence(b, 8, default_eval) == default_eval(b)
        checked += 1
    assert checked > 0


def test_quiescence_restores_board() -> None:
    rng = random.Random(1)
    for _ in range(40):
        b = Board()
        for _ in range(rng.randint(2, 16)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if b.is_terminal():
            continue
        before = (b.bb[0], b.bb[1], b.turn, list(b.heights), b.num_moves)
        quiescence(b, 8, default_eval)
        after = (b.bb[0], b.bb[1], b.turn, list(b.heights), b.num_moves)
        assert before == after


def test_quiescence_is_d4_invariant() -> None:
    rng = random.Random(2)
    for _ in range(40):
        seq: list[int] = []
        b = Board()
        for _ in range(rng.randint(1, 24)):
            if b.is_terminal():
                break
            c = rng.choice(b.legal_moves())
            b.play(c)
            seq.append(c)
        if b.is_terminal():
            continue
        base = quiescence(b, 6, default_eval)
        for t in range(8):
            im = _play([COL_PERMS[t][c] for c in seq])
            assert quiescence(im, 6, default_eval) == base
