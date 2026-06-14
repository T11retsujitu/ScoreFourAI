"""詰み問題生成 (problems.py) のテスト — Phase 7。

生成は決定的 (シード固定)。生成した各問題が条件 (強制勝ち・指定手数・初手一意・
全応手で勝ち継続・D4 一意) を満たすことを verify_problem と独立な再探索で確認する。
小さな max_attempts で速く回す。
"""
from pathlib import Path

from score_four.board import Board
from score_four.problems import (
    build_problem,
    generate_problems,
    grade_difficulty,
    load_problems,
    save_problems,
    verify_problem,
)
from score_four.solve import winning_moves_with_distance
from score_four.symmetry import COL_PERMS, canonical


def test_generate_is_deterministic() -> None:
    a = generate_problems(1, 4, seed=2, setup_max=18, max_attempts=3000)
    b = generate_problems(1, 4, seed=2, setup_max=18, max_attempts=3000)
    assert a == b


def test_generated_mate_in_one_problems_satisfy_all_conditions() -> None:
    probs = generate_problems(1, 5, seed=3, setup_max=18, max_attempts=4000)
    assert probs, "mate-in-1 問題が見つからない"
    keys = set()
    for p in probs:
        assert p.mate_in == 1
        assert verify_problem(p)
        # 初手一意: 強制勝ち手はちょうど 1 つ。
        board = Board()
        for c in p.setup:
            board.play(c)
        assert winning_moves_with_distance(board, 3) == [(p.solution, 1)]
        keys.add(p.key)
    assert len(keys) == len(probs)  # D4 重複なし


def test_generated_mate_in_three_problems_are_real_forced_wins() -> None:
    probs = generate_problems(3, 4, seed=5, setup_max=20, max_attempts=6000)
    assert probs, "mate-in-3 問題が見つからない"
    for p in probs:
        assert p.mate_in == 3
        assert verify_problem(p)


def test_difficulty_is_monotonic() -> None:
    assert grade_difficulty(3, 5) > grade_difficulty(1, 5)  # 手数が支配的
    assert grade_difficulty(3, 8) > grade_difficulty(3, 4)  # 同手数はおとり数で増


def test_build_problem_rejects_non_unique_first_move() -> None:
    """強制勝ち手が 2 つ以上ある局面は初手一意でないので None。"""
    # 先手 X が柱0 と柱5 の両方で即勝ちになる二重即勝ち局面を作る (12 手, X 手番)。
    seq = (0, 1, 0, 2, 0, 3, 5, 6, 5, 7, 5, 8)
    b = Board()  # X: 柱0/柱5 に 3 段ずつ、O: 他柱に 1 個ずつ (非勝ち)
    for c in seq:
        b.play(c)
    assert b.turn == 0  # X の手番
    assert b.winning_moves(0) == [0, 5]  # 0 と 5 の両方で即勝ち
    wins = winning_moves_with_distance(b, 3)
    assert len(wins) >= 2  # 強制勝ち手が複数 = 初手非一意
    assert build_problem(b, seq, 3) is None


def test_symmetric_images_share_one_canonical_key() -> None:
    """生成した問題の D4 対称像はすべて同じ正規化キーになる (重複除去の根拠)。"""
    probs = generate_problems(1, 1, seed=4, setup_max=16, max_attempts=4000)
    assert probs
    p = probs[0]
    for t in range(8):
        b = Board()
        for c in p.setup:
            b.play(COL_PERMS[t][c])
        assert canonical(b.bb[0], b.bb[1])[0] == p.key


def test_save_load_roundtrip(tmp_path: Path) -> None:
    probs = generate_problems(1, 3, seed=6, setup_max=16, max_attempts=4000)
    assert probs
    path = tmp_path / "problems.json"
    save_problems(probs, path)
    assert load_problems(path) == probs
