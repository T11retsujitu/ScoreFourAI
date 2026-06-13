"""探索: negamax + alpha-beta。

実装順: alpha-beta -> 置換表(Zobrist) -> 脅威ベースの強制手枝刈り
        -> 着手順序 -> 対称性圧縮(D4) -> 反復深化 + PVS。

現状の到達点 (この層):
    - 終端スコアリング (勝ち = 速いほど高評価 / 負け = 遅いほど高評価 / 引分 = 0)
    - 全幅 negamax (`negamax_full`): 枝刈りなしの **参照実装**。テストの基準値。
    - alpha-beta + 着手順序 + 置換表(Zobrist) (`negamax`): 実戦用。
      参照実装と同じ値を返すことを契約テストで保証する (センサー先行)。
    - 反復深化ドライバ (`search`) と公開 API (`best_move`)。

未実装 (次の層): 脅威ベースの強制手枝刈り / 対称性圧縮(D4) / PVS。

スコアの符号は常に **手番側 (board.turn) から見た値**。負けは負、勝ちは正。
勝ち/負けの絶対値は手数に依存し ``WIN`` 近傍になる (|score| > ``MATE_LO`` なら
強制決着が読み切れている合図)。
"""

from collections.abc import Callable

from .board import NUM_CELLS, Board
from .evaluate import line_potential

# 勝敗の基準値。max 手数(64) より十分大きく取り、評価値(ヒューリスティック)の
# 取りうる範囲とも重ならないようにする。
WIN = 1_000_000
INF = WIN * 2
# |score| がこれを超えていれば、地平線の評価値ではなく終端 (強制決着) 由来。
MATE_LO = WIN - NUM_CELLS - 1

Heuristic = Callable[[Board], int]

# 置換表エントリのフラグ。
EXACT, LOWER, UPPER = 0, 1, 2

# 着手順序: 中央寄りの柱を先に試すと枝刈りが効きやすい。
# 柱 col = y*4 + x。中心 (1.5, 1.5) への近さで並べる。
_CENTRALITY = {
    col: abs((col % 4) - 1.5) + abs((col // 4) - 1.5) for col in range(16)
}
COLUMN_ORDER: tuple[int, ...] = tuple(sorted(range(16), key=_CENTRALITY.__getitem__))
COLUMN_RANK: tuple[int, ...] = tuple(
    COLUMN_ORDER.index(col) for col in range(16)
)


def terminal_value(board: Board) -> int | None:
    """局面が終端なら手番側から見たスコア、そうでなければ None。

    勝敗が付いているとき、勝ったのは直前に着手した側 = 手番側の相手なので、
    手番側にとっては負け。負けが早い (手数が少ない) ほど悪い値にして「より長く
    粘る」「より速く決める」方向へ探索を誘導する。
    """
    if board.winner is not None:
        # 手番側は負け。num_moves が小さい(早い負け)ほど絶対値を大きく。
        return -(WIN - board.num_moves)
    if board.is_full():
        return 0  # 引分
    return None


def _ordered_moves(board: Board, tt_move: int) -> list[int]:
    """着手を試す順に並べる。置換表の手を先頭、残りは中央寄り順。"""
    moves = board.legal_moves()
    moves.sort(key=COLUMN_RANK.__getitem__)
    if tt_move >= 0 and tt_move in moves:
        moves.remove(tt_move)
        moves.insert(0, tt_move)
    return moves


def negamax_full(board: Board, depth: int, heuristic: Heuristic) -> int:
    """枝刈り・置換表なしの全幅 negamax (参照実装)。

    alpha-beta 版が返す値の **基準**。両者が同一局面・同一 depth・同一
    heuristic で必ず一致することを契約テストで保証する。
    """
    term = terminal_value(board)
    if term is not None:
        return term
    if depth == 0:
        return heuristic(board)

    best = -INF
    for col in board.legal_moves():
        board.play(col)
        value = -negamax_full(board, depth - 1, heuristic)
        board.undo()
        if value > best:
            best = value
    return best


def negamax(
    board: Board,
    depth: int,
    alpha: int,
    beta: int,
    tt: dict[int, tuple[int, int, int, int]],
    heuristic: Heuristic,
) -> int:
    """alpha-beta + 着手順序 + 置換表(Zobrist) の negamax。

    返り値は手番側視点のスコア (fail-soft)。フルウィンドウ
    (alpha=-INF, beta=INF) で根から呼べば真の minimax 値に一致する。

    置換表は ``board.key`` をキーに ``(depth, value, flag, best_move)`` を持つ。
    TT の値は depth が現在以上のときのみ early-return / cutoff に使い、窓の
    絞り込みには使わない (微妙なバグの温床を避ける安全形)。
    """
    term = terminal_value(board)
    if term is not None:
        return term
    if depth == 0:
        return heuristic(board)

    alpha_orig = alpha
    key = board.key
    tt_move = -1
    entry = tt.get(key)
    if entry is not None:
        e_depth, e_value, e_flag, e_move = entry
        tt_move = e_move
        if e_depth >= depth:
            if e_flag == EXACT:
                return e_value
            if e_flag == LOWER and e_value >= beta:
                return e_value
            if e_flag == UPPER and e_value <= alpha:
                return e_value

    best = -INF
    best_move = -1
    for col in _ordered_moves(board, tt_move):
        board.play(col)
        value = -negamax(board, depth - 1, -beta, -alpha, tt, heuristic)
        board.undo()
        if value > best:
            best = value
            best_move = col
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break  # beta カット

    if best <= alpha_orig:
        flag = UPPER  # fail-low: best は上界
    elif best >= beta:
        flag = LOWER  # fail-high: best は下界
    else:
        flag = EXACT
    tt[key] = (depth, best, flag, best_move)
    return best


def _search_root(
    board: Board,
    depth: int,
    tt: dict[int, tuple[int, int, int, int]],
    heuristic: Heuristic,
) -> tuple[int, int]:
    """根を 1 段だけ展開し ``(score, best_move)`` を返す (フルウィンドウ)。"""
    alpha = -INF
    best = -INF
    best_move = -1
    entry = tt.get(board.key)
    tt_move = entry[3] if entry is not None else -1
    for col in _ordered_moves(board, tt_move):
        board.play(col)
        value = -negamax(board, depth - 1, -INF, -alpha, tt, heuristic)
        board.undo()
        if value > best:
            best = value
            best_move = col
        if best > alpha:
            alpha = best
    tt[board.key] = (depth, best, EXACT, best_move)
    return best, best_move


def search(
    board: Board,
    max_depth: int,
    heuristic: Heuristic = line_potential,
    tt: dict[int, tuple[int, int, int, int]] | None = None,
) -> tuple[int, int]:
    """反復深化で ``(score, best_move)`` を返す (手番側視点)。

    1..max_depth と深めながら、前反復の置換表を着手順序に再利用する。
    強制決着 (|score| が ``MATE_LO`` 超) を読み切ったら早期終了する。
    決定的: 同一局面・同一引数なら常に同じ手を返す。
    """
    if board.is_terminal():
        raise ValueError("cannot search a terminal position")
    if tt is None:
        tt = {}
    score, move = -INF, -1
    for depth in range(1, max_depth + 1):
        score, move = _search_root(board, depth, tt, heuristic)
        if abs(score) > MATE_LO:
            break  # 勝ち負けを読み切った
    return score, move


def best_move(
    board: Board,
    max_depth: int,
    heuristic: Heuristic = line_potential,
) -> int:
    """``search`` の最善手だけを返す薄いラッパ。"""
    return search(board, max_depth, heuristic)[1]
