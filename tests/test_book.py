"""定石 (opening book) の生成・照会・対称性・入出力のテスト。

生成は決定的 (固定深さ)。テストでは小さな book をその場で生成して検証するので、
コミット済みの大きな book ファイルや Rust 拡張の有無に依存しない (Python/Rust の
探索は契約テストで同値)。
"""
import random
from pathlib import Path

from score_four.board import Board
from score_four.book import (
    book_move,
    choose_move,
    generate_book,
    load_book,
    save_book,
)
from score_four.symmetry import COL_PERMS

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


def test_committed_book_loads_if_present() -> None:
    """コミット済み data/opening_book.json があれば、空局面に合法な手を返す。"""
    path = Path(__file__).resolve().parents[1] / "data" / "opening_book.json"
    if not path.exists():
        return  # 未生成ならスキップ (純粋な機能テストは上で済んでいる)
    book = load_book(path)
    assert len(book) > 0
    move, _score = book_move(book, Board())
    assert move in Board().legal_moves()
