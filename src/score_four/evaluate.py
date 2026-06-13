"""評価関数: 脅威カウント + 奇偶(パリティ)理論。

探索が終端まで届く局面では呼ばれないため、優先度は探索より後。
ここに置くのは反復深化の地平線 (depth 0) で使う **第一次のヒューリスティック**。

設計メモ (docs/design.md 4.7) の通り、奇偶パリティ理論は Score Four では
未確立の仮説であり、ここではまだ取り込まない。まずは決定的で安価な
「ライン potential (脅威カウント)」だけを実装し、自己対戦で効果を測ってから
重み付け・パリティへ進む。確立した本質と断定しないこと。
"""

from .board import LINE_MASKS, Board

# あと何個で 4 並びかに応じたライン価値。占有 1/2/3 個を脅威として重み付け。
# 0 個 (空ライン) は両者に等価値なので 0。4 個は勝利で終端側が扱うため評価に来ない。
_WEIGHT = (0, 1, 5, 25, 0)


def line_potential(board: Board) -> int:
    """手番側から見たライン potential (脅威カウント) を返す。

    各勝利ラインについて、片方の色だけが占有していれば (相手に潰されていなければ)
    その色の「生きた脅威」とみなし、占有数に応じて加点する。両者が混在する
    ラインは死んでいるので 0。先手(0) 視点のスコアを最後に手番側へ符号変換する。

    純粋関数 (board を変更しない)。終端局面では呼ばない前提。
    """
    p0, p1 = board.bb
    score = 0
    for mask in LINE_MASKS:
        a = p0 & mask
        b = p1 & mask
        if a:
            if b:
                continue  # 両者混在 = 死んだライン
            score += _WEIGHT[a.bit_count()]
        elif b:
            score -= _WEIGHT[b.bit_count()]
    return score if board.turn == 0 else -score
