"""定石 (opening book) の生成・照会・対称性・入出力のテスト。

生成は決定的 (固定深さ)。テストでは小さな book をその場で生成して検証するので、
コミット済みの大きな book ファイルや Rust 拡張の有無に依存しない (Python/Rust の
探索は契約テストで同値)。
"""
import random
from pathlib import Path

import json

from score_four.board import Board
from score_four.book import (
    book_entry,
    book_move,
    choose_move,
    generate_book,
    generate_selective,
    load_book,
    merge_book,
    save_book,
)
from score_four.symmetry import COL_PERMS, canonical

# 小さく速い book (固定深さ)。Python/Rust いずれでも同一結果。
_TINY = dict(max_plies=2, depth=6)


def _image(seq: list[int], t: int) -> Board:
    """手順 seq に列置換 t を施して打ち直した対称像の局面。"""
    b = Board()
    for c in seq:
        b.play(COL_PERMS[t][c])
    return b


def test_generate_is_deterministic() -> None:
    assert generate_book(**_TINY) == generate_book(**_TINY)


def test_empty_position_has_a_legal_book_move() -> None:
    book = generate_book(**_TINY)
    move, _score = book_move(book, Board())
    assert move in Board().legal_moves()


def test_book_covers_positions_up_to_max_plies_only() -> None:
    book = generate_book(max_plies=2, depth=6)
    # 0,1,2 手の局面は book にあるが、3 手の局面は無い。
    b3 = Board()
    for c in (5, 6, 9):
        b3.play(c)
    assert book_move(book, b3) is None
    b1 = Board()
    b1.play(5)
    assert book_move(book, b1) is not None


def test_book_move_is_symmetry_consistent() -> None:
    """対称像の局面でも、book の手を指すと到達局面は同じ軌道・評価値も不変。

    自己対称な局面 (空盤など) では「手 = 手の変換」は成り立たない (固定部分群がある
    ため)。常に成り立つ頑健な不変条件として、book の手を指した後の正規化キーが全ての
    対称像で一致することを確認する。
    """
    from score_four.symmetry import canonical

    book = generate_book(**_TINY)
    rng = random.Random(0)
    for _ in range(20):
        seq: list[int] = []
        b = Board()
        for _ in range(rng.randint(0, 2)):
            c = rng.choice(b.legal_moves())
            b.play(c)
            seq.append(c)
        base = book_move(book, b)
        assert base is not None
        _base_move, base_score = base
        after_keys = set()
        for t in range(8):
            im = _image(seq, t)
            mv, sc = book_move(book, im)
            assert sc == base_score
            assert mv in im.legal_moves()
            im.play(mv)
            after_keys.add(canonical(im.bb[0], im.bb[1])[0])
        assert len(after_keys) == 1  # 全対称像で到達局面は同じ軌道


def test_book_move_matches_engine_at_book_depth() -> None:
    """book の手は、その局面を同じ深さで探索した最善手と一致する (book は探索の出力)。"""
    from score_four.search import search

    book = generate_book(max_plies=2, depth=6)
    b = Board()
    b.play(5)
    move, score = book_move(book, b)
    eng_score, eng_move = search(b, 6)
    assert (move, score) == (eng_move, eng_score)


def test_choose_move_uses_book_then_search() -> None:
    """book 内は book の手、book 外は探索の手を返す (同深さで一致)。"""
    from score_four.search import search

    book = generate_book(max_plies=2, depth=6)
    in_book = Board()
    in_book.play(5)
    assert choose_move(book, in_book, 6) == book_move(book, in_book)

    out_book = Board()  # 3 手 = book(max_plies=2) の外
    for c in (5, 6, 9):
        out_book.play(c)
    assert book_move(book, out_book) is None
    move, score = choose_move(book, out_book, 6)
    eng_score, eng_move = search(out_book, 6)
    assert (move, score) == (eng_move, eng_score)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    book = generate_book(**_TINY)
    path = tmp_path / "book.json"
    save_book(book, path)
    assert load_book(path) == book


def test_entries_carry_depth_and_book_entry(tmp_path: Path) -> None:
    """v2: エントリは (move, score, depth, ply)。book_entry が depth/ply を返す。"""
    book = generate_book(max_plies=2, depth=6)
    b = Board()
    b.play(5)
    move, score, depth, ply = book_entry(book, b)
    assert depth == 6 and ply == 1
    assert (move, score) == book_move(book, b)
    # 保存→読込でも 4 要素・depth 保持。
    save_book(book, tmp_path / "b.json")
    assert load_book(tmp_path / "b.json") == book


def test_loads_legacy_v1_format(tmp_path: Path) -> None:
    """旧 v1 形式 (move, score, ply) を読み込み、depth=0 に正規化する。"""
    key = canonical(0, 0)[0]
    v1 = {"format": "score-four-opening-book/1", "entries": {str(key): [5, 0, 0]}}
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1), encoding="utf-8")
    book = load_book(path)
    assert book[key] == (5, 0, 0, 0)  # depth が 0 (不明) で補われる
    assert book_move(book, Board()) is not None


def test_merge_prefers_deeper(tmp_path: Path) -> None:
    """merge_book は同一キーで深い depth を優先 (品質単調)。"""
    key = canonical(0, 0)[0]
    shallow = {key: (5, 10, 6, 0)}
    deep = {key: (6, 20, 12, 0)}
    assert merge_book(shallow, deep)[key] == (6, 20, 12, 0)  # 深い方を採用
    assert merge_book(deep, shallow)[key] == (6, 20, 12, 0)  # 浅い方は既存を上書きしない
    # 別キーは単純に統合。
    other = {key ^ 1: (3, 0, 8, 1)}
    merged = merge_book(shallow, other)
    assert len(merged) == 2


def test_atomic_save_no_leftover_tmp(tmp_path: Path) -> None:
    """save_book は一時ファイルを残さない (原子的差し替え)。"""
    book = generate_book(max_plies=1, depth=6)
    save_book(book, tmp_path / "b.json")
    assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())
    assert load_book(tmp_path / "b.json") == book


def test_selective_is_deterministic() -> None:
    kw = dict(max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2)
    assert generate_selective(**kw) == generate_selective(**kw)


def test_selective_is_smaller_than_full() -> None:
    """選択的 book は同 max_plies の全列挙より小さい (木を絞っている)。"""
    full = generate_book(max_plies=3, depth=6)
    sel = generate_selective(max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2)
    assert 0 < len(sel) < len(full)


def test_selective_entries_match_engine() -> None:
    """選択的 book の手も、その局面を同深さで探索した最善手と一致する。"""
    from score_four.search import search

    sel = generate_selective(max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2)
    # owner=0 の principal: 空盤 (owner の手番) の最善手は探索と一致。
    b = Board()
    move, score = book_move(sel, b)
    eng_score, eng_move = search(b, 6)
    assert (move, score) == (eng_move, eng_score)


def test_selective_principal_is_a_thin_line() -> None:
    """ai_width=1, opp_width=1 は principal 1 本道に近く、robust(2) より小さい。"""
    principal = generate_selective(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=1)
    robust = generate_selective(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2)
    assert 0 < len(principal) <= len(robust)


def test_selective_both_covers_both_sides() -> None:
    """owner='both' は先手・後手どちらの owner 単独より広く覆う (merge)。"""
    both = generate_selective(max_plies=3, depth=6, owner="both", ai_width=1, opp_width=2)
    one = generate_selective(max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2)
    assert len(both) >= len(one)
    # book の手は合法。
    move, _ = book_move(both, Board())
    assert move in Board().legal_moves()


def test_committed_book_loads_if_present() -> None:
    """コミット済み data/opening_book.json があれば、空局面に合法な手を返す。"""
    path = Path(__file__).resolve().parents[1] / "data" / "opening_book.json"
    if not path.exists():
        return  # 未生成ならスキップ (純粋な機能テストは上で済んでいる)
    book = load_book(path)
    assert len(book) > 0
    move, _score = book_move(book, Board())
    assert move in Board().legal_moves()
