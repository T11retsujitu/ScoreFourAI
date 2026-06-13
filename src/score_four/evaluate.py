"""評価関数: 脅威カウント (+ 実験的な奇偶パリティ)。

探索が終端まで届く局面では呼ばれないため、優先度は探索より後。ここに置くのは
反復深化の地平線 (depth 0) で使うヒューリスティック。

**重要な制約 (探索との契約)**: 評価は **D4 対称不変** でなければならない。探索は
D4 正規化キーで置換表を共有する (symmetry.py) ため、同じ軌道の局面に違う評価値を
返すと TT が矛盾する。z (高さ) は D4 で不変なので、ライン占有数・空きマスの高さ・
着手可能性・パリティはいずれも D4 不変に作れる。すべての評価関数はこの不変性を
test_symmetry.py で検証する。

設計メモ (docs/design.md 4.7): 奇偶パリティ理論は Score Four では **未確立の仮説**。
Connect Four の奇/偶脅威理論をそのまま移植できる保証はない。よってパリティは
既定では使わず (重み 0)、自己対戦 (selfplay.py) で効果を測ってから採否・重みを
決める。確立した本質と断定しないこと。

評価関数の系譜 (単純 → 強化):
    line_potential  : ライン占有数だけの最小ヒューリスティック (ベースライン)。
    threat_eval     : 上に「即時脅威 (今すぐ着手で4が揃う3並び)」の加点を足した版。
    parity_eval     : threat_eval に実験的なパリティ項を足した版 (重みは要計測)。
"""

from .board import LINE_MASKS, Board

# あと何個で 4 並びかに応じたライン価値。占有 1/2/3 個を脅威として重み付け。
# 0 個 (空ライン) は両者に等価値なので 0。4 個は勝利で終端側が扱うため評価に来ない。
_WEIGHT = (0, 1, 5, 25, 0)

# 即時脅威 (3並びで、残り1マスが今すぐ着手できる柱の着地点) への加点。
# 計測の結果ベースラインを頑健には改善しなかったため、既定の探索評価には使わない。
_IMMEDIATE = 40

# パリティ項の既定重み。自己対戦で検証済み (docs/eval_measurements.md):
# 負の重み = 「偶数段(0,2)の脅威が先手有利 / 奇数段(1,3)が後手有利」が depth3/4 で
# 一貫してベースラインに勝つ (depth4 で winrate 0.57)。-8 を採用。
_PARITY = -8


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


def threat_eval(board: Board, immediate: int = _IMMEDIATE) -> int:
    """ライン potential に「即時脅威」の加点を足した手番側視点の評価。

    占有数による基本価値 (line_potential と同じ) に加え、3 並びでかつ残り 1 マスが
    **今すぐ着手できる** (その柱の現在の着地点である) 場合に immediate を加点する。
    即時脅威は相手に受けを強制する、という直感に基づく。

    ただし自己対戦の計測ではこの加点はベースライン (immediate=0 = line_potential)
    より弱かった (docs の計測メモ参照)。探索が depth>=2 で即時の戦術を脅威枝刈りで
    正確に解決するため、地平線評価で即時脅威を重く見ると静的局面の判断を歪めると
    思われる。よって既定では search に採用しない。immediate を可変にして掃引できる。

    純粋関数。終端局面では呼ばない前提。D4 不変 (高さ・着手可能性は D4 で保たれる)。
    """
    p0, p1 = board.bb
    heights = board.heights
    score = 0
    for mask in LINE_MASKS:
        a = p0 & mask
        b = p1 & mask
        if a:
            if b:
                continue  # 両者混在 = 死んだライン
            ca = a.bit_count()
            score += _WEIGHT[ca]
            if ca == 3 and immediate:
                e = (mask ^ a).bit_length() - 1  # 残り1マスのセル index
                if e >> 4 == heights[e & 15]:    # z == その柱の着地点 → 即着手可
                    score += immediate
        elif b:
            cb = b.bit_count()
            score -= _WEIGHT[cb]
            if cb == 3 and immediate:
                e = (mask ^ b).bit_length() - 1
                if e >> 4 == heights[e & 15]:
                    score -= immediate
    return score if board.turn == 0 else -score


def parity_eval(
    board: Board, parity_weight: int = _PARITY, immediate: int = 0
) -> int:
    """line_potential に **実験的な** 奇偶パリティ項 (と任意で即時脅威) を足した版。

    作業仮説 (docs/design.md 4.7): 3 並びの「残り 1 マスが完成する高さ z」の偶奇が
    終盤の手番の押し付け (ツークツワンク) に効きうる。ここでは各プレイヤーの未完成
    3 並びについて、完成セルの z が奇数なら +1 / 偶数なら -1 を数え、先手 - 後手の差を
    parity_weight 倍して先手視点スコアへ加える。正の重みは「奇数段の脅威が先手に
    有利」という Connect Four 流の向き、負の重みは逆向きを表す。**どちらが正しいかも
    含め未確立**なので、計測では両符号を掃引する。

    パリティ効果を ベースライン (line_potential) 上で純粋に測れるよう、即時脅威の
    加点は既定で 0 (= 切る)。immediate を指定すれば threat_eval 相当の加点も乗る。
    parity_weight=0, immediate=0 なら line_potential と完全一致する。
    D4 不変 (z は D4 で不変)。
    """
    p0, p1 = board.bb
    heights = board.heights
    score = 0
    parity = 0  # 先手(0)視点: (先手の奇-偶脅威) - (後手の奇-偶脅威) を集計
    for mask in LINE_MASKS:
        a = p0 & mask
        b = p1 & mask
        if a:
            if b:
                continue
            ca = a.bit_count()
            score += _WEIGHT[ca]
            if ca == 3:
                e = (mask ^ a).bit_length() - 1
                if immediate and e >> 4 == heights[e & 15]:
                    score += immediate
                parity += 1 if (e >> 4) & 1 else -1
        elif b:
            cb = b.bit_count()
            score -= _WEIGHT[cb]
            if cb == 3:
                e = (mask ^ b).bit_length() - 1
                if immediate and e >> 4 == heights[e & 15]:
                    score -= immediate
                parity -= 1 if (e >> 4) & 1 else -1
    score += parity_weight * parity
    return score if board.turn == 0 else -score


def default_eval(board: Board) -> int:
    """探索が既定で使う評価。検証済みパリティ項付き (= parity_eval, 重み _PARITY)。

    自己対戦でベースライン line_potential に一貫して勝った構成 (docs 参照)。
    D4 不変なので探索の対称性圧縮 TT と矛盾しない。
    """
    return parity_eval(board)
