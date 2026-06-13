"""ビットボード表現・着手生成・勝利判定。

セルのインデックス規約 (このプロジェクト唯一の定義):
    index = z * 16 + y * 4 + x    # x,y in 0..3 (基盤), z in 0..3 (高さ)
着手は「柱(列) の選択」のみ。コマはその柱の最下段の空きに落ちる。
勝利判定は直前に置いたセルを通る線だけを見る増分判定にする。
"""


class Board:
    """4x4x4 Score Four の局面 (重力あり)。"""

    def __init__(self) -> None:
        raise NotImplementedError
