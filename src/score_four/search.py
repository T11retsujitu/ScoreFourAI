"""探索: negamax + alpha-beta。

実装順: alpha-beta -> 置換表(Zobrist) -> 脅威ベースの強制手枝刈り
        -> 着手順序 -> 対称性圧縮(D4) -> 反復深化 + PVS。
"""
