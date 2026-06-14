"""着手順序強化 (killer / history) のテスト (強化 Phase 3)。

killer/history は **minimax 値を変えない**（順序だけ変える）。値不変と、順序ヘルパの
優先順位・cutoff 更新の正しさを確認する。言語横断の (score,best_move) 一致は
test_rust_search.py が担保する。
"""
import random

from score_four.board import Board
from score_four.evaluate import default_eval
from score_four.search import (
    INF,
    _new_ordering_state,
    _ordered_moves,
    _update_cutoff,
    negamax_full,
    search,
)


def test_ordering_priority_tt_killer_history_center() -> None:
    """TT手 → killer0 → killer1 → history → 中央寄り の優先順位。"""
    b = Board()  # 全16柱が合法
    killers_d = [3, 7]
    history_p = [0] * 16
    history_p[5] = 100  # 柱5 を history で持ち上げる
    order = _ordered_moves(b, tt_move=10, killers_d=killers_d, history_p=history_p)
    assert order[:4] == [10, 3, 7, 5]
    assert sorted(order) == list(range(16))


def test_ordering_empty_state_matches_center_with_tt() -> None:
    """history/killer が空なら従来 (TT先頭 + 中央寄り) と一致する。"""
    b = Board()
    killers_d = [-1, -1]
    history_p = [0] * 16
    with_state = _ordered_moves(b, 10, killers_d, history_p)
    legacy = _ordered_moves(b, 10)  # killers_d=None → 従来
    assert with_state == legacy


def test_update_cutoff_killer_shift_and_history() -> None:
    killers, history = _new_ordering_state(8)
    kd = killers[3]
    _update_cutoff(kd, history, player=0, col=5, depth=3)
    assert kd == [5, -1]
    assert history[0][5] == 9  # depth*depth
    _update_cutoff(kd, history, player=0, col=6, depth=3)
    assert kd == [6, 5]        # シフト
    _update_cutoff(kd, history, player=0, col=6, depth=2)
    assert kd == [6, 5]        # 同一手は重複登録しない
    assert history[0][6] == 9 + 4


def test_history_decay_on_cap() -> None:
    killers, history = _new_ordering_state(8)
    history[0][5] = (1 << 20)  # CAP 直下
    _update_cutoff(killers[1], history, 0, 5, 1)  # +1 で超える → 全体半減
    assert history[0][5] == ((1 << 20) + 1) >> 1


def test_search_value_unchanged_by_ordering() -> None:
    """search の値は、順序なし全幅 negamax の minimax 値に一致する (順序で値は変わらない)。"""
    rng = random.Random(3)
    for _ in range(20):
        b = Board()
        for _ in range(rng.randint(0, 16)):
            if b.is_terminal():
                break
            b.play(rng.choice(b.legal_moves()))
        if b.is_terminal():
            continue
        for depth in (3, 4):
            s, _ = search(b.copy(), depth)
            ref = negamax_full(b.copy(), depth, default_eval)
            assert s == ref, f"depth={depth} search={s} full={ref}\n{b}"
        assert INF > 0  # 定数の健全性 (import 利用)
