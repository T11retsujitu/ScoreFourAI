"""詰み探索 (mate solver) — Phase 7 の解析モード。

通常の評価ベース α-β とは別の **「強制勝ちの証明」専用モード**。ある局面で手番側が
強制勝ち (どんな応手でも 4 を揃えて勝てる) かどうかを判定し、**最短詰み手数**と
**詰み手順 (PV)** を返す。3/5/7 手詰めの判定・問題生成 (`problems.py`) の土台。

設計判断 (CLAUDE.md「正しさが全ての土台」「計測せず複雑性を足さない」に従う):

  詰み探索は AND/OR 木の解法で、df-PN / Threat-Space Search などの専用アルゴリズムが
  知られる。しかし本プロジェクトは **検証済みの α-β コアを再利用** することで、別個の
  未検証アルゴリズムを足さずに「正しい詰み探索」を最小労力で得る方針を取る:

    * 葉評価を **恒等的に 0 (D4 不変)** にした negamax は、地平線 D 以内の game value を
      そのまま返す。終端のスコアは「速い勝ち=高 / 遅い負け=高」(search.terminal_value)
      なので、**最善値 = 最短強制勝ち / 最長粘りの負け** に一致する。
    * その negamax は `negamax_full` (全幅参照) と全 depth で同値であることが
      `test_search.py` の契約で固められている。したがって零評価 negamax の返す詰み手数は
      参照実装と一致する (本モジュールの `test_solve.py` でも独立に再確認)。
    * 反復深化 (`search`) は |score|>MATE_LO を読み切った時点で打ち切るので、最初に
      詰みが出た深さ = 最短詰み手数。零評価では詰みでない局面の値は 0 のままなので、
      max_plies まで掘って 0 なら「その地平線内に強制勝ちなし」。

  既存の脅威ベース強制手枝刈り (相手の即勝ち柱への受けを強制 / ダブルリーチで負け確定)
  が探索木を詰みに向けて大きく絞る = 実質的な Threat-Space 的縮約を既に備えている。
  より速い df-PN への置換は将来の最適化として roadmap に残す (計測で効果を確認してから)。

スコアの符号は search と同じく **手番側 (board.turn) 視点**。
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import Board
from .search import MATE_LO, WIN, search

# 強制勝ち証明に使う D4 不変な零評価器。地平線の葉では常に 0 を返すので、negamax は
# 「地平線内の終端 (勝ち/負け/引分) のみ」を価値として伝播する = 純粋な詰み探索になる。
# 探索の対称性 TT は評価が D4 不変であることを要求する (symmetry.py); 定数 0 は自明に満たす。


def zero_eval(_board: Board) -> int:
    """常に 0 を返す D4 不変な評価器 (詰み探索用の葉評価)。"""
    return 0


# 詰み探索の最大手数の既定。盤は 64 マスなので、ここまで掘れば必ず終端に届く。
MAX_PLIES = 64


@dataclass(frozen=True)
class MateResult:
    """詰み探索の結果 (手番側視点)。

    status:
        "win"     : 手番側に強制勝ちがある (plies 手で勝てる)。
        "loss"    : 相手が手番側を強制的に詰ます (plies 手で負ける)。
        "draw"    : 双方最善で引分に終わる (地平線が残り全マスを覆い切った場合)。
        "unknown" : max_plies の地平線内では勝敗を読み切れなかった。
    plies   : 詰みまでの手数 (status が win/loss のときのみ非 None)。手番側・相手の手を
              合わせた総手数で、勝ち手 (4 が揃う着手) を打つまでの ply 数。
    best_move : 最善の柱 (現局面の座標系)。win なら詰ます手、loss なら最も粘る受け。
    pv      : 主手順 (双方最善の詰み手順)。pv[0] == best_move。
    """

    status: str
    plies: int | None
    best_move: int
    pv: tuple[int, ...]


def _solve_value(board: Board, max_plies: int) -> tuple[int, int]:
    """零評価 negamax で (score, best_move) を返す薄いラッパ (手番側視点)。"""
    return search(board, max_plies, heuristic=zero_eval)


def solve(board: Board, max_plies: int = MAX_PLIES) -> MateResult:
    """局面の詰み探索を行い MateResult を返す (手番側視点・決定的)。

    強制勝ち/負けを読み切ったら最短/最長手数と詰み手順 (PV) を、読み切れなければ
    status="unknown" (地平線内に決着なし) を返す。盤面は破壊しない。

    終端局面は探索できないので、勝敗が付いていれば status を直接決める (winner は
    直前に着手した側 = 手番側の相手なので手番側にとっては loss / plies 0)。
    """
    if board.winner is not None:
        # 直前の着手で勝負あり。手番側は (受ける手番すら無く) 負け。
        return MateResult("loss", 0, -1, ())
    if board.is_full():
        return MateResult("draw", None, -1, ())

    score, move = _solve_value(board, max_plies)
    if score > MATE_LO:
        plies = (WIN - score) - board.num_moves
        pv = _principal_variation(board, max_plies)
        return MateResult("win", plies, move, pv)
    if score < -MATE_LO:
        plies = (WIN + score) - board.num_moves
        pv = _principal_variation(board, max_plies)
        return MateResult("loss", plies, move, pv)
    # 決着なし。地平線が残り全マスを覆っていれば引分確定、そうでなければ未確定。
    if max_plies >= 64 - board.num_moves:
        return MateResult("draw", None, move, ())
    return MateResult("unknown", None, move, ())


def _principal_variation(board: Board, max_plies: int) -> tuple[int, ...]:
    """強制勝ち/負けの主手順を双方最善で復元する。

    各 ply で零評価探索の最善手を打ち、終端に届くまで辿る。勝ち側は最短で詰ます手を、
    負け側は最も粘る手を選ぶ (terminal_value の符号がそれを保証する)。盤面は復元する。
    """
    line: list[int] = []
    probe = board.copy()
    remaining = max_plies
    while not probe.is_terminal() and remaining > 0:
        score, move = _solve_value(probe, remaining)
        if abs(score) <= MATE_LO:
            break  # この先は強制決着でない (理論上、勝ち手順では起きない)
        if move < 0 or move not in probe.legal_moves():
            break
        probe.play(move)
        line.append(move)
        remaining -= 1
    return tuple(line)


def is_forced_win(board: Board, max_plies: int = MAX_PLIES) -> bool:
    """手番側に max_plies 手以内の強制勝ちがあれば True。"""
    return solve(board, max_plies).status == "win"


def winning_moves_with_distance(
    board: Board, max_plies: int = MAX_PLIES
) -> list[tuple[int, int]]:
    """手番側の「強制勝ちになる着手」を ``(柱, 詰み手数)`` で全列挙する (昇順)。

    各合法手を 1 手打ち、相手番の局面が強制負け (= こちらの強制勝ち) なら採用する。
    即勝ち手は手数 1。詰み問題生成の「初手一意」「最短手数」判定に使う。盤面は復元する。
    """
    if board.is_terminal():
        return []
    res: list[tuple[int, int]] = []
    for col in board.legal_moves():
        probe = board.copy()
        if probe.play(col):
            res.append((col, 1))  # 即勝ち = 1 手詰み
            continue
        child = solve(probe, max_plies - 1)
        if child.status == "loss":
            # 相手番が plies 手で負ける ⇒ この着手で plies+1 手詰み。
            res.append((col, (child.plies or 0) + 1))
    res.sort(key=lambda cd: (cd[1], cd[0]))
    return res
