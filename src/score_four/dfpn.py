"""df-PN (depth-first proof-number) 詰み探索 — Phase 7 の高速化候補。

`solve.py` の零評価 αβ とは別アルゴリズムで「手番側が max_plies 手以内に強制勝ちか」を
証明/反証する。AND/OR 木の proof number / disproof number を深さ優先で更新する df-PN
(Nagai 2002) を使う。**採否は計測で決める** (CLAUDE.md): まず Python で正しく作り、零評価
αβ `solve` と同じ勝ち判定を返すことを契約テストで固めてから、ノード数で速さを比較する。

設計上の要点:

  * **明示的 AND/OR (negamax にしない)**: 「手番側が勝つ」は勝ち/それ以外 (負け/引分/地平線)
    の二値だが、引分・地平線があると negamax 対称性 (相手が勝てない = 自分が勝つ) が崩れる。
    そこで証明者 (ME = 根の手番) を固定し、OR ノード (ME の手番) は子の1つが証明できれば
    証明、AND ノード (相手の手番) は全子が証明できて初めて証明、とする。
  * **Score Four は GHI フリー**: 局面値は (b0,b1) だけで決まり (手番は駒数の偶奇で一意)、
    手順に依存しない (重力で一手ごとに駒が増える DAG・反復なし)。よって **D4 正規化キーの
    置換表が健全** (同じ局面は同じ証明数)。地平線 L は根からの絶対手数 num_moves で測るので、
    転置した局面の残り深さも一意。
  * **脅威ベースの強制手narrowing を αβ と同形に内蔵**: 即勝ち・ダブルリーチ負け・唯一の
    受け を leaf/子生成に入れ、`solve` の αβ と同じ枝を辿る (公平な比較・高速化)。

葉の評価は手番側視点ではなく **ME 視点固定** (proof = ME の強制勝ち)。
"""

from __future__ import annotations

from .board import Board
from .symmetry import canonical

# proof/disproof number の無限大。盤は 64 マスなので分岐 × 深さ はこれより十分小さい。
INF = 1 << 30

# 葉の分類。
_PROVEN = 0  # ME の強制勝ちが確定
_DISPROVEN = 1  # ME は勝てない (負け/引分/地平線)
_INTERIOR = 2  # 内部ノード (展開が必要)


def _ssum(values: list[int]) -> int:
    """proof/disproof number の総和 (INF 飽和)。"""
    s = 0
    for v in values:
        if v >= INF:
            return INF
        s += v
    return s if s < INF else INF - 1


class _Dfpn:
    """1 回の df-PN 探索の状態 (置換表・ノード数・証明者 ME・絶対地平線 L)。"""

    def __init__(self, root: Board, max_plies: int) -> None:
        self.me = root.turn  # 証明者 = 根の手番 (固定)
        self.limit = root.num_moves + max_plies  # 絶対手数の地平線
        self.tt: dict[int, tuple[int, int]] = {}  # canonical key -> (pn, dn)
        self.nodes = 0  # MID 呼び出し回数 (計測用)

    def _key(self, board: Board) -> int:
        return canonical(board.bb[0], board.bb[1])[0]

    def _classify(self, board: Board) -> tuple[int, int | None]:
        """葉分類と (内部なら) 強制手を返す。proof = ME の強制勝ち。

        αβ (solve.py / search) と同形の脅威判定: 即勝ち → ダブルリーチ負け → 唯一の受け。
        返り値: (_PROVEN/_DISPROVEN, None) か (_INTERIOR, forced_col_or_None)。
        """
        if board.winner is not None:
            return (_PROVEN if board.winner == self.me else _DISPROVEN), None
        if board.is_full():
            return _DISPROVEN, None  # 引分は ME の勝ちではない
        if board.num_moves >= self.limit:
            return _DISPROVEN, None  # 地平線内に勝ちを示せない
        side = board.turn
        if board.has_winning_move(side):
            # 手番側が即勝ちできる。
            return (_PROVEN if side == self.me else _DISPROVEN), None
        opp = side ^ 1
        threats = board.winning_moves(opp)
        if len(threats) >= 2:
            # 手番側は両受けできず負け (勝者は opp)。
            return (_PROVEN if opp == self.me else _DISPROVEN), None
        forced = threats[0] if len(threats) == 1 else None
        return _INTERIOR, forced

    def _child_pn_dn(self, board: Board) -> tuple[int, int]:
        """子局面 (現在の board) の (pn, dn) を TT か葉評価から返す。"""
        key = self._key(board)
        cached = self.tt.get(key)
        if cached is not None:
            return cached
        cls, _ = self._classify(board)
        if cls == _PROVEN:
            return 0, INF
        if cls == _DISPROVEN:
            return INF, 0
        return 1, 1  # 未展開の内部ノード

    def _children(self, board: Board, forced: int | None) -> list[int]:
        return [forced] if forced is not None else board.legal_moves()

    def mid(self, board: Board, th_pn: int, th_dn: int) -> None:
        """しきい値 (th_pn, th_dn) を超えるまで board を深さ優先で展開し TT を更新。"""
        self.nodes += 1
        key = self._key(board)
        cls, forced = self._classify(board)
        if cls == _PROVEN:
            self.tt[key] = (0, INF)
            return
        if cls == _DISPROVEN:
            self.tt[key] = (INF, 0)
            return

        is_or = board.turn == self.me
        moves = self._children(board, forced)

        while True:
            # 子の (pn, dn) を集計。
            pns: list[int] = []
            dns: list[int] = []
            for mv in moves:
                board.play(mv)
                cp, cd = self._child_pn_dn(board)
                board.undo()
                pns.append(cp)
                dns.append(cd)
            if is_or:
                pn, dn = min(pns), _ssum(dns)
            else:
                pn, dn = _ssum(pns), min(dns)

            if pn == 0 or dn == 0 or pn >= th_pn or dn >= th_dn:
                self.tt[key] = (pn, dn)
                return

            # 展開する子と、その子のしきい値を決める。
            if is_or:
                i = _argmin(pns)
                pn2 = _second_min(pns, i)
                ch_th_pn = min(th_pn, pn2 + 1)
                ch_th_dn = th_dn - (dn - dns[i])  # th_dn - Σ_{j≠i} dn_j
            else:
                i = _argmin(dns)
                dn2 = _second_min(dns, i)
                ch_th_dn = min(th_dn, dn2 + 1)
                ch_th_pn = th_pn - (pn - pns[i])  # th_pn - Σ_{j≠i} pn_j

            board.play(moves[i])
            self.mid(board, ch_th_pn, ch_th_dn)
            board.undo()

    def prove(self, board: Board) -> bool:
        """根を完全に解決し、ME に強制勝ちがあれば True。"""
        self.mid(board, INF, INF)
        pn, _ = self.tt[self._key(board)]
        return pn == 0


def _argmin(xs: list[int]) -> int:
    best, bi = xs[0], 0
    for i in range(1, len(xs)):
        if xs[i] < best:
            best, bi = xs[i], i
    return bi


def _second_min(xs: list[int], skip: int) -> int:
    """index skip を除いた最小値 (無ければ INF)。"""
    best = INF
    for i, v in enumerate(xs):
        if i != skip and v < best:
            best = v
    return best


def prove_win(board: Board, max_plies: int) -> bool:
    """手番側が max_plies 手以内に強制勝ちできるなら True (board は非破壊)。

    `solve(board, max_plies).status == "win"` と一致する (契約テストで保証)。
    """
    return _Dfpn(board, max_plies).prove(board.copy())


def prove_win_stats(board: Board, max_plies: int) -> tuple[bool, int]:
    """`prove_win` の結果と探索ノード数 (MID 呼び出し回数) を返す (計測用)。"""
    solver = _Dfpn(board, max_plies)
    won = solver.prove(board.copy())
    return won, solver.nodes
