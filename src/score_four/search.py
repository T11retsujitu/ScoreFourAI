"""探索: negamax + alpha-beta。

実装順 (すべて実装済み):
    alpha-beta -> 置換表(Zobrist) -> 脅威ベースの強制手枝刈り
    -> 着手順序 -> 対称性圧縮(D4) -> 反復深化 + PVS。

構成要素:
    - 終端スコアリング (勝ち = 速いほど高評価 / 負け = 遅いほど高評価 / 引分 = 0)
    - 全幅 negamax (`negamax_full`): 枝刈りなしの **参照実装**。テストの基準値。
    - alpha-beta + 着手順序 + 置換表 + 脅威枝刈り + D4対称性 + PVS (`negamax`)。
      参照実装と同じ値を返すことを契約テストで保証する (センサー先行)。
    - 反復深化 + 時間制御ドライバ (`search`) と公開 API (`best_move`)。

PVS (Principal Variation Search): 第1手のみ全幅で探索し PV を確定、以降の手は
幅 0 のヌルウィンドウ (scout) で「PV を超えないこと」だけ確かめる。超えたら
全幅で再探索する。前反復の PV 手 (置換表に正規化キーで保存) が先頭に来るほど
scout が外れず探索木が小さくなる。

時間制御: `search` は反復深化の各反復間で締切を確認し、反復の途中でも締切を
超えたら中断して **その反復を破棄し直前に完了した反復の結果** を返す。深さ1は
必ず完走させ最低限の手を保証する。盤面を壊さないよう探索はコピー上で行う。

スコアの符号は常に **手番側 (board.turn) から見た値**。負けは負、勝ちは正。
勝ち/負けの絶対値は手数に依存し ``WIN`` 近傍になる (|score| > ``MATE_LO`` なら
強制決着が読み切れている合図)。
"""

import time
from collections.abc import Callable

from .board import NUM_CELLS, Board
from .evaluate import default_eval
from .symmetry import COL_PERMS, INV_COL_PERMS, canonical

# 勝敗の基準値。max 手数(64) より十分大きく取り、評価値(ヒューリスティック)の
# 取りうる範囲とも重ならないようにする。
WIN = 1_000_000
INF = WIN * 2
# |score| がこれを超えていれば、地平線の評価値ではなく終端 (強制決着) 由来。
MATE_LO = WIN - NUM_CELLS - 1

Heuristic = Callable[[Board], int]

# 置換表エントリのフラグ。
EXACT, LOWER, UPPER = 0, 1, 2


class _Timeout(Exception):
    """探索の締切超過。反復深化ドライバが捕捉し、その反復を破棄する。"""


class _Clock:
    """締切までの探索打ち切り用。一定ノードごとにだけ時刻を確認する (軽量)。"""

    __slots__ = ("deadline", "n")
    _CHECK_MASK = 0x7FF  # 2048 ノードに 1 回だけ time.monotonic を呼ぶ

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.n = 0

    def tick(self) -> None:
        """ノード訪問を数え、締切を過ぎていれば _Timeout を送出する。"""
        self.n += 1
        if not (self.n & self._CHECK_MASK) and time.monotonic() >= self.deadline:
            raise _Timeout

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
    clock: "_Clock | None" = None,
) -> int:
    """alpha-beta + 着手順序 + 置換表 + 脅威枝刈り + D4対称性 + PVS の negamax。

    返り値は手番側視点のスコア (fail-soft)。フルウィンドウ
    (alpha=-INF, beta=INF) で根から呼べば真の minimax 値に一致する。

    置換表は **D4 対称性で正規化したキー** に ``(depth, value, flag, best_move)``
    を持つ。同じ軌道の局面が同一キーに集約され実効状態空間が約 1/8 になる。
    値・境界は対称不変だが best_move は正規形の座標系なので、保存時は現局面 ->
    正規形 (COL_PERMS)、読み出し時は正規形 -> 現局面 (INV_COL_PERMS) に列を写す。
    TT の値は depth が現在以上のときのみ early-return / cutoff に使い、窓の
    絞り込みには使わない (微妙なバグの温床を避ける安全形)。

    前提: 対称性圧縮が健全なのは **heuristic が D4 対称不変** のときだけ
    (同じ軌道の局面に同じ評価値を返す)。既定の default_eval (パリティ付き) は
    76 ライン・高さ・パリティのみに依存し D4 不変なので満たす。非対称な評価を
    渡すと正規化 TT と矛盾する。

    脅威ベースの強制手枝刈り (健全・ゲーム値を変えない exact な枝刈り):
        - 自分に即勝ち手 → 最速勝ちを即返す (depth>=1 で全幅と一致)。
        - 相手の即勝ち脅威が2柱以上 → 受け切れず負け確定を返す (depth>=2)。
        - 相手の即勝ち脅威が1柱 → その柱で受ける1手だけに分岐を絞る (depth>=2)。
      depth>=2 のゲートは必須: 浅い地平線では全幅探索も2手先の決着を見ず
      評価値を返すため、ゲートを外すと参照実装と値がずれる。

    PVS: 第1手は全幅、以降はヌルウィンドウ [alpha, alpha+1] で探索し、alpha を
    超えた手だけ全幅で再探索する。clock を渡すと締切超過時に _Timeout を送出する。
    """
    term = terminal_value(board)
    if term is not None:
        return term
    if depth == 0:
        return heuristic(board)
    if clock is not None:
        clock.tick()

    alpha_orig = alpha
    key, sym = canonical(board.bb[0], board.bb[1])
    tt_move = -1
    entry = tt.get(key)
    if entry is not None:
        e_depth, e_value, e_flag, e_move = entry
        if e_move >= 0:
            tt_move = INV_COL_PERMS[sym][e_move]  # 正規形 -> 現局面
        if e_depth >= depth:
            if e_flag == EXACT:
                return e_value
            if e_flag == LOWER and e_value >= beta:
                return e_value
            if e_flag == UPPER and e_value <= alpha:
                return e_value

    me = board.turn
    # 自分の即勝ち: 最速勝ちが最善 (これ以上の値はない)。
    if board.has_winning_move(me):
        return WIN - (board.num_moves + 1)

    # 相手の即勝ち脅威による強制手 (depth>=2 のときだけ健全)。
    forced: list[int] | None = None
    if depth >= 2:
        threats = board.winning_moves(me ^ 1)
        if len(threats) >= 2:
            # ダブルリーチ: 自分が1手受けても相手が次手で勝つ。
            return -(WIN - (board.num_moves + 2))
        if threats:
            forced = threats  # 唯一の脅威柱を受ける1手に限定。

    moves = forced if forced is not None else _ordered_moves(board, tt_move)
    best = -INF
    best_move = -1
    first = True
    for col in moves:
        board.play(col)
        if first:
            value = -negamax(board, depth - 1, -beta, -alpha, tt, heuristic, clock)
        else:
            # scout: 幅0のヌルウィンドウで「alpha を超えるか」だけ確かめる。
            value = -negamax(board, depth - 1, -alpha - 1, -alpha, tt, heuristic, clock)
            if alpha < value < beta:
                # PV を更新しうる手。正確な値を得るため全幅で再探索。
                value = -negamax(board, depth - 1, -beta, -alpha, tt, heuristic, clock)
        board.undo()
        if value > best:
            best = value
            best_move = col
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break  # beta カット
        first = False

    if best <= alpha_orig:
        flag = UPPER  # fail-low: best は上界
    elif best >= beta:
        flag = LOWER  # fail-high: best は下界
    else:
        flag = EXACT
    store_move = COL_PERMS[sym][best_move] if best_move >= 0 else -1  # 現局面 -> 正規形
    tt[key] = (depth, best, flag, store_move)
    return best


def _search_root(
    board: Board,
    depth: int,
    tt: dict[int, tuple[int, int, int, int]],
    heuristic: Heuristic,
    clock: "_Clock | None" = None,
) -> tuple[int, int]:
    """根を 1 段だけ PVS 展開し ``(score, best_move)`` を返す (フルウィンドウ)。"""
    me = board.turn
    wins = board.winning_moves(me)
    if wins:
        # 即勝ち手があればそれが最善 (最速勝ち)。先頭の柱を返す。
        return WIN - (board.num_moves + 1), wins[0]

    alpha = -INF
    best = -INF
    best_move = -1
    key, sym = canonical(board.bb[0], board.bb[1])
    entry = tt.get(key)
    tt_move = INV_COL_PERMS[sym][entry[3]] if entry is not None and entry[3] >= 0 else -1
    first = True
    for col in _ordered_moves(board, tt_move):
        board.play(col)
        if first:
            value = -negamax(board, depth - 1, -INF, -alpha, tt, heuristic, clock)
        else:
            value = -negamax(board, depth - 1, -alpha - 1, -alpha, tt, heuristic, clock)
            if value > alpha:  # 根では beta=INF なので上限ガードは不要。
                value = -negamax(board, depth - 1, -INF, -alpha, tt, heuristic, clock)
        board.undo()
        if value > best:
            best = value
            best_move = col
        if best > alpha:
            alpha = best
        first = False
    store_move = COL_PERMS[sym][best_move] if best_move >= 0 else -1
    tt[key] = (depth, best, EXACT, store_move)
    return best, best_move


def search(
    board: Board,
    max_depth: int,
    heuristic: Heuristic = default_eval,
    tt: dict[int, tuple[int, int, int, int]] | None = None,
    time_limit: float | None = None,
) -> tuple[int, int]:
    """反復深化 + 時間制御で ``(score, best_move)`` を返す (手番側視点)。

    1..max_depth と深めながら、前反復の置換表を着手順序 (PV) に再利用する。
    強制決着 (|score| が ``MATE_LO`` 超) を読み切ったら早期終了する。

    time_limit (秒) を渡すと、各反復の前後・途中で締切を確認し、超過したら
    その反復を破棄して **直前に完了した反復の結果** を返す。深さ1は必ず完走
    させるので、どれだけ締切が短くても最低限の手は返る。盤面は破壊しないよう
    コピー上で探索する。

    決定的: time_limit=None なら同一局面・同一引数で常に同じ手を返す。
    """
    if board.is_terminal():
        raise ValueError("cannot search a terminal position")
    if tt is None:
        tt = {}

    work = board.copy()  # 締切で中断しても呼び出し側の盤面を壊さない
    deadline = time.monotonic() + time_limit if time_limit is not None else None

    # 深さ1は無条件に完走 (最低限の手を保証)。
    score, move = _search_root(work, 1, tt, heuristic)
    if abs(score) > MATE_LO:
        return score, move

    for depth in range(2, max_depth + 1):
        if deadline is not None and time.monotonic() >= deadline:
            break
        clock = _Clock(deadline) if deadline is not None else None
        try:
            score, move = _search_root(work, depth, tt, heuristic, clock)
        except _Timeout:
            break  # 途中の反復は破棄し、直前に完了した結果を返す
        if abs(score) > MATE_LO:
            break  # 勝ち負けを読み切った
    return score, move


def best_move(
    board: Board,
    max_depth: int,
    heuristic: Heuristic = default_eval,
    time_limit: float | None = None,
) -> int:
    """``search`` の最善手だけを返す薄いラッパ。"""
    return search(board, max_depth, heuristic, time_limit=time_limit)[1]
