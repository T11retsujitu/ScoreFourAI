"""Rust 探索 (score_four_rs) と Python 探索の言語横断契約テスト (センサー先行)。

段階2: symmetry / evaluate / search を Rust 化した。Rust は Python と同一アルゴリズム・
同一着手順序・同一 TT 意味論・同一 PVS なので、各層が **完全一致** することを保証する:
  - canonical (D4 正規化キー)
  - eval_default (既定評価値)
  - negamax_value (全幅 negamax 値)
  - search の (score, best_move)

拡張未ビルドなら skip (純 Python のスイートは独立に緑)。
"""
import random

import pytest

from score_four.board import Board
from score_four.evaluate import default_eval
from score_four.search import INF
from score_four.search import negamax as py_negamax
from score_four.search import search as py_search
from score_four.symmetry import canonical as py_canonical

rs = pytest.importorskip("score_four_rs", reason="Rust 拡張が未ビルド")


def _random_nonterminal(seed: int, count: int, max_plies: int) -> list[Board]:
    rng = random.Random(seed)
    boards: list[Board] = []
    for _ in range(count):
        b = Board()
        for _ in range(rng.randint(0, max_plies)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if not b.is_terminal():
            boards.append(b)
    return boards


def test_canonical_matches_python() -> None:
    for b in _random_nonterminal(1, 80, 30):
        assert rs.canonical(b.bb[0], b.bb[1]) == py_canonical(b.bb[0], b.bb[1])


def test_eval_default_matches_python() -> None:
    for b in _random_nonterminal(2, 80, 32):
        assert rs.eval_default(b.bb[0], b.bb[1]) == default_eval(b)


def test_features_match_python() -> None:
    """Phase 8: D4 不変整数特徴量が Rust/Python で完全一致 (教師データ生成の前提)。"""
    from score_four.evaluate import features

    for b in _random_nonterminal(21, 120, 34):
        assert list(rs.features(b.bb[0], b.bb[1])) == features(b)


def test_learned_eval_matches_python() -> None:
    """Phase 8: 学習線形評価が Rust/Python で一致し、既定重みは default_eval に一致する。"""
    from score_four.evaluate import learned_eval

    weights = [
        [1, 5, 25, -8, 0, 0],  # default_eval と等価な健全性ケース
        [3, -2, 7, -8, 4, 1],
        [0, 0, 0, 0, 0, 0],
        [10, -10, 100, 16, -4, 2],
    ]
    for b in _random_nonterminal(22, 100, 34):
        for w in weights:
            ru = rs.eval_learned(b.bb[0], b.bb[1], w)
            assert ru == learned_eval(b, w)
        # 既定重みは default_eval と完全一致 (パリティ式の線形分解の健全性)。
        assert rs.eval_learned(b.bb[0], b.bb[1], [1, 5, 25, -8, 0, 0]) == default_eval(b)


def test_geometric_features_match_python() -> None:
    """Phase 10: 幾何・解放特徴 8 次元が Rust/Python で完全一致。"""
    from score_four.evaluate import geometric_features

    for b in _random_nonterminal(31, 120, 34):
        assert list(rs.geometric_features(b.bb[0], b.bb[1])) == geometric_features(b)


def test_eval_geometric_match_python() -> None:
    """Phase 10: 幾何加点が Rust/Python で一致。重み 0 で 0。"""
    from score_four.evaluate import eval_geometric

    weights = [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [2, -1, 3, -4, 5, -2, 6, -3],
        [10, 0, 0, -5, 0, 8, 0, 0],
    ]
    for b in _random_nonterminal(32, 80, 34):
        for w in weights:
            assert rs.eval_geometric(b.bb[0], b.bb[1], w) == eval_geometric(b, w)
        assert rs.eval_geometric(b.bb[0], b.bb[1], [0] * 8) == 0


def test_geometric_search_contract() -> None:
    """Phase 10: 候補評価 (default+geo) で Rust αβ == Python αβ・全幅==αβ (浅め)。"""
    from score_four.evaluate import eval_default_plus_geometric
    from score_four.search import negamax_full
    from score_four.search import search as py_search

    w = [3, -2, 4, -6, 5, -1, 7, -3]

    def heur(bd):
        return eval_default_plus_geometric(bd, w)

    # Rust αβ == Python αβ (fresh TT) — 候補評価でも一致。
    for b in _random_nonterminal(33, 30, 22):
        for depth in range(1, 6):
            ab = py_negamax(b.copy(), depth, -INF, INF, {}, heur)
            rs_val = rs.negamax_value_geometric(b.bb[0], b.bb[1], depth, w)
            assert rs_val == ab, f"rs!=py depth={depth} rs={rs_val} py={ab}\n{b}"
    # 全幅 == αβ (候補評価): 全幅は重いので浅い depth(<=3, 16^3 程度) に限定。
    for b in _random_nonterminal(36, 20, 30):
        for depth in range(1, 4):
            full = negamax_full(b.copy(), depth, heur)
            ab = py_negamax(b.copy(), depth, -INF, INF, {}, heur)
            assert full == ab, f"全幅!=αβ depth={depth}\n{b}"
    # 反復深化 search の (score, best_move) も Python/Rust 一致。
    for b in _random_nonterminal(34, 25, 24):
        for depth in range(1, 7):
            ps, pm = py_search(b.copy(), depth, heur)
            rsc, rsm = rs.search_geometric(b.bb[0], b.bb[1], depth, w)
            assert (ps, pm) == (rsc, rsm), f"depth={depth} py={(ps, pm)} rs={(rsc, rsm)}\n{b}"


def test_geometric_off_keeps_default_eval() -> None:
    """Phase 10: geo 既定オフのとき eval_default は不変 (zero_config/solve も無影響)。"""
    for b in _random_nonterminal(35, 60, 32):
        assert rs.eval_default(b.bb[0], b.bb[1]) == default_eval(b)


def test_negamax_value_matches_python() -> None:
    """全幅 negamax 値 (fresh TT) が depth 1..5 で一致する。"""
    for b in _random_nonterminal(3, 30, 22):
        for depth in range(1, 6):
            py = py_negamax(b.copy(), depth, -INF, INF, {}, default_eval)
            ru = rs.negamax_value(b.bb[0], b.bb[1], depth)
            assert py == ru, f"depth={depth} py={py} rs={ru}\n{b}"


def test_search_matches_python() -> None:
    """反復深化 search の (score, best_move) が depth 1..6 で一致する。"""
    for b in _random_nonterminal(4, 30, 24):
        for depth in range(1, 7):
            ps, pm = py_search(b.copy(), depth)
            rsc, rsm = rs.search(b.bb[0], b.bb[1], depth)
            assert (ps, pm) == (rsc, rsm), f"depth={depth} py={(ps, pm)} rs={(rsc, rsm)}\n{b}"


def test_quiescence_matches_python() -> None:
    """脅威静穏化 (qdepth>0) でも Rust と Python が一致する (Phase 2 契約)。

    Python 側 quiescence は遅いので浅い depth・少数局面で確認する。
    """
    from score_four.search import INF
    from score_four.search import negamax as py_negamax

    for b in _random_nonterminal(7, 12, 18):
        for qd in (2, 4):
            # negamax 値 (全幅, fresh TT) の一致
            rv = rs.negamax_value(b.bb[0], b.bb[1], 4, qd)
            pv = py_negamax(b.copy(), 4, -INF, INF, {}, default_eval, None, qd)
            assert rv == pv, f"negamax qd={qd} rs={rv} py={pv}\n{b}"
            # 反復深化 search の (score, best_move) の一致
            rsc, rsm = rs.search(b.bb[0], b.bb[1], 5, None, -8, 0, 0, 1, 5, 25, qd)
            ps, pm = py_search(b.copy(), 5, qdepth=qd)
            assert (rsc, rsm) == (ps, pm), f"search qd={qd}\n{b}"


def _play(columns: list[int]) -> Board:
    b = Board()
    for col in columns:
        b.play(col)
    return b


def test_finds_immediate_win() -> None:
    b = _play([0, 1, 0, 1, 0, 1])  # 先手が柱0で即勝ち
    score, move = rs.search(b.bb[0], b.bb[1], 2)
    assert move == 0
    assert score > rs_mate_lo()


def test_finds_fork() -> None:
    b = _play([1, 2, 4, 8, 6, 11, 9, 14])  # 柱5でダブルリーチ
    score, move = rs.search(b.bb[0], b.bb[1], 5)
    assert move == 5
    assert score > rs_mate_lo()


def test_time_limit_returns_legal_move() -> None:
    b = _play([5, 6, 9, 10, 0])
    score, move = rs.search(b.bb[0], b.bb[1], 64, 0.2)
    assert move in b.legal_moves()


def rs_mate_lo() -> int:
    # search.rs の MATE_LO = WIN - 64 - 1
    return 1_000_000 - 64 - 1


# --- 精緻化パリティ特徴 (実験用) の D4 不変性とハーネス整合 -----------------

# (parity_weight, immediate, parity_mode, w1, w2, w3)
# mode 0=ALL, 1=LOWEST, 2=REACHABLE。w1,w2,w3 は基本ライン重み。
_EVAL_CONFIGS = [
    (0, 0, 0, 1, 5, 25),    # ベースライン (line_potential)
    (-8, 0, 0, 1, 5, 25),   # ALL (既定)
    (-8, 0, 1, 1, 5, 25),   # LOWEST
    (-8, 0, 2, 1, 5, 25),   # REACHABLE
    (-8, 12, 0, 1, 5, 25),  # ALL + 即時脅威
    (-6, 0, 0, 1, 4, 16),   # 別の基本重み + パリティ
]


def test_all_eval_modes_are_d4_invariant() -> None:
    """新しいパリティモード・基本重みを含む全評価が D4 不変 (対称性 TT の前提)。"""
    from score_four.symmetry import COL_PERMS

    def image(seq: list[int], t: int) -> Board:
        b = Board()
        for c in seq:
            b.play(COL_PERMS[t][c])
        return b

    rng = random.Random(9)
    for _ in range(40):
        seq: list[int] = []
        b = Board()
        for _ in range(rng.randint(1, 30)):
            if b.is_terminal():
                break
            c = rng.choice(b.legal_moves())
            b.play(c)
            seq.append(c)
        if b.is_terminal():
            continue
        for cfg in _EVAL_CONFIGS:
            base = rs.eval_cfg(b.bb[0], b.bb[1], *cfg)
            for t in range(8):
                im = image(seq, t)
                assert rs.eval_cfg(im.bb[0], im.bb[1], *cfg) == base


def test_play_match_consistency() -> None:
    """同一評価同士は左右対称で勝ち数一致。総局数 = openings*2。"""
    from score_four.selfplay import random_openings

    cfg = (-8, 0, 0, 1, 5, 25)
    openings = [list(o) for o in random_openings(12, 6, seed=5)]
    aw, bw, dr = rs.play_match(cfg, cfg, openings, 3)
    assert aw == bw  # 同一評価なので先後入替で対称
    assert aw + bw + dr == len(openings) * 2
