"""search.py の契約テスト (センサー先行)。

中核の不変条件: alpha-beta + 置換表版 `negamax` は、枝刈りなしの全幅参照
実装 `negamax_full` と **必ず同じ値** を返す。任意の決定的ヒューリスティック
について成り立つべき性質なので、局面に依存する擬似ヒューリスティックで
ランダム局面・各 depth を総当たり的に突き合わせる。

さらに即詰み (勝ち1手) を見つける・相手の即詰みを受ける、といった戦術的な
既知局面で best_move を検証する。
"""
import random

from score_four.board import Board
from score_four.search import (
    INF,
    MATE_LO,
    WIN,
    best_move,
    negamax,
    negamax_full,
    search,
    terminal_value,
)


def _pseudo_eval(board: Board) -> int:
    """局面から決まる決定的な擬似評価 (-100..100)。

    値が局面ごとにばらつくので、着手順序・枝刈り・置換表のいずれかが minimax
    値を変えてしまえば全幅参照との不一致として現れる。終端スコア(|WIN|)とは
    桁が違うため混同しない。

    D4 対称性圧縮の前提 (評価が対称不変であること) を満たすため、生の
    ``board.key`` ではなく **正規化キー** から導く。これにより同じ軌道の局面は
    同じ評価値になり、対称性 TT と矛盾しない (実エンジンの line_potential も
    対称不変)。
    """
    from score_four.symmetry import canonical

    ckey, _ = canonical(board.bb[0], board.bb[1])
    return (((ckey * 2654435761) >> 16) % 201) - 100


def _random_positions(seed: int, count: int, max_plies: int) -> list[Board]:
    """ランダムに数手進めた非終端局面を集める。"""
    rng = random.Random(seed)
    boards: list[Board] = []
    for _ in range(count):
        board = Board()
        plies = rng.randint(0, max_plies)
        for _ in range(plies):
            if board.is_terminal():
                break
            board.play(rng.choice(board.legal_moves()))
        if not board.is_terminal():
            boards.append(board)
    return boards


def test_alpha_beta_matches_full_width() -> None:
    """alpha-beta+TT が全幅 negamax と同じ値を返す (任意 depth・多数局面)。"""
    for board in _random_positions(seed=1, count=25, max_plies=20):
        for depth in range(1, 5):
            ref = negamax_full(board.copy(), depth, _pseudo_eval)
            got = negamax(board.copy(), depth, -INF, INF, {}, _pseudo_eval)
            assert got == ref, f"depth={depth} ref={ref} got={got}\n{board}"


def test_alpha_beta_with_default_heuristic_matches_full_width() -> None:
    """既定ヒューリスティック (line_potential) でも全幅と一致する。"""
    from score_four.evaluate import line_potential

    for board in _random_positions(seed=7, count=40, max_plies=24):
        for depth in range(1, 4):
            ref = negamax_full(board.copy(), depth, line_potential)
            got = negamax(board.copy(), depth, -INF, INF, {}, line_potential)
            assert got == ref


def test_threat_pruning_matches_full_width() -> None:
    """脅威枝刈り入りの negamax が、脅威が頻出する中盤〜終盤の局面でも全幅と一致。

    深い局面 (24..48 手) は即勝ち脅威・ダブルリーチを多く含むため、強制手枝刈り
    (depth>=2) の健全性を集中的に検証できる。depth は 1..5 を確認。
    """
    for board in _random_positions(seed=11, count=24, max_plies=52):
        if board.num_moves < 32:  # 空きが少ない局面ほど全幅参照が軽く脅威も豊富
            continue
        for depth in range(1, 6):
            ref = negamax_full(board.copy(), depth, _pseudo_eval)
            got = negamax(board.copy(), depth, -INF, INF, {}, _pseudo_eval)
            assert got == ref, (
                f"plies={board.num_moves} depth={depth} "
                f"ref={ref} got={got}\n{board}"
            )


def test_finds_double_threat_win() -> None:
    """フォーク (ダブルリーチを作る手) を選び、勝ちを読み切る。

    z=0 平面で先手 X は 柱1,4,6,9 を持つ (まだ即勝ちは無い)。柱5 に置くと
        - 横ライン y=1: {4,5,6,7} が X 3つ → 柱7 が脅威
        - 縦ライン x=1: {1,5,9,13} が X 3つ → 柱13 が脅威
    の二重脅威が生まれ、後手は両方を受けられず X 勝ち。
    後手 O は脅威柱 (5,7,13) を避けた無関係な柱に置く。
    """
    board = _play([1, 2, 4, 8, 6, 11, 9, 14])  # X:1,4,6,9 / O:2,8,11,14
    assert board.turn == 0
    assert board.winning_moves(0) == []  # この時点では即勝ちは無い
    score, move = search(board, 5)
    assert move == 5
    assert score > MATE_LO  # フォークによる強制勝ちを読み切っている


def test_search_is_deterministic() -> None:
    """同一局面・同一引数なら常に同じ (score, move) を返す。"""
    for board in _random_positions(seed=3, count=20, max_plies=16):
        a = search(board.copy(), 4, _pseudo_eval)
        b = search(board.copy(), 4, _pseudo_eval)
        assert a == b


# --- 反復深化 + 時間制御 -------------------------------------------------


def test_time_limit_returns_valid_move_and_preserves_board() -> None:
    """短い時間制御でも合法手を返し、入力盤面を破壊しない。"""
    import time

    board = _play([5, 6, 9, 10, 0])  # 適当な非終端局面
    snapshot = (list(board.bb), bytes(board.heights), board.turn, board.num_moves)
    start = time.monotonic()
    score, move = search(board, 64, time_limit=0.3)
    elapsed = time.monotonic() - start

    assert move in board.legal_moves()
    assert elapsed < 2.0  # 締切(0.3s)から大きく超過しない
    # コピー上で探索するので呼び出し側の盤面は不変。
    assert (list(board.bb), bytes(board.heights), board.turn, board.num_moves) == snapshot


def test_tiny_time_limit_still_returns_depth1_move() -> None:
    """極端に短い締切でも深さ1は完走し、合法手を返す。"""
    board = Board()
    score, move = search(board, 64, time_limit=1e-6)
    assert move in board.legal_moves()


def test_time_limit_not_binding_matches_unlimited() -> None:
    """十分な時間 + 浅い max_depth なら、時間制御なしと同じ結果になる。"""
    for board in _random_positions(seed=21, count=10, max_plies=14):
        ref = search(board.copy(), 4)
        timed = search(board.copy(), 4, time_limit=30.0)
        assert ref == timed


def test_immediate_win_ignores_time_limit() -> None:
    """即勝ちは深さ1 (時間制御外) で即決し、勝ちスコアを返す。"""
    board = _play([0, 1, 0, 1, 0, 1])  # 先手が柱0で即勝ち
    score, move = search(board, 64, time_limit=1e-6)
    assert move == 0
    assert score > MATE_LO


# --- 終端スコアリング ----------------------------------------------------


def test_terminal_value_none_for_open_position() -> None:
    assert terminal_value(Board()) is None


def test_terminal_value_loss_for_side_to_move() -> None:
    """勝敗が付いた局面では、手番側 (= 負けた側) に負のスコア。"""
    board = Board()
    for col in [0, 1, 0, 1, 0, 1, 0]:  # 先手が柱0に縦4
        board.play(col)
    assert board.winner == 0
    # 手番は敗者(後手=1)。負の終端値。
    assert board.turn == 1
    value = terminal_value(board)
    assert value is not None and value < -MATE_LO


# --- 戦術的な既知局面 ----------------------------------------------------


def _play(columns: list[int]) -> Board:
    board = Board()
    for col in columns:
        board.play(col)
    return board


def test_finds_immediate_vertical_win() -> None:
    """先手が柱0に3つ。手番の先手は柱0で即勝ちを選ぶ。"""
    board = _play([0, 1, 0, 1, 0, 1])  # p0: 柱0 z0..z2 / p1: 柱1 z0..z2
    assert board.turn == 0
    score, move = search(board, 2)
    assert move == 0
    assert score > MATE_LO  # 勝ちを読み切っている


def test_blocks_opponent_immediate_win() -> None:
    """相手(先手)が柱0に3つでリーチ。手番の後手は柱0を受けるしかない。"""
    board = _play([0, 1, 0, 1, 0])  # p0: 柱0 z0..z2 (リーチ) / p1: 柱1 z0..z1
    assert board.turn == 1
    move = best_move(board, 4)
    assert move == 0


def test_finds_horizontal_win_in_one() -> None:
    """z=0 平面で先手が柱0,1,2。柱3で即勝ち。"""
    board = _play([0, 4, 1, 5, 2, 6])  # p0: 柱0,1,2(z0) / p1: 柱4,5,6(z0)
    assert board.turn == 0
    score, move = search(board, 2)
    assert move == 3
    assert score > MATE_LO


def test_win_score_prefers_faster_mate() -> None:
    """即勝ち局面のスコアは WIN 近傍 (手数で目減りした分だけ WIN 未満)。"""
    board = _play([0, 1, 0, 1, 0, 1])
    score, _ = search(board, 2)
    # 1手で詰むので num_moves=7 で勝ち -> WIN - 7。
    assert score == WIN - 7
