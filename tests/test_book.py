"""定石 (opening book) の生成・照会・対称性・入出力のテスト。

生成は決定的 (固定深さ)。テストでは小さな book をその場で生成して検証するので、
コミット済みの大きな book ファイルや Rust 拡張の有無に依存しない (Python/Rust の
探索は契約テストで同値)。
"""
import json
import random
from pathlib import Path

import score_four.book as book_mod
from score_four.board import Board
from score_four.book import (
    book_entry,
    book_move,
    choose_move,
    generate_book,
    generate_book_resumable,
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


def test_resumable_matches_in_memory(tmp_path: Path) -> None:
    """完走した再開可能生成は in-memory の generate_selective(owner) と完全一致。"""
    out = tmp_path / "book.json"
    kw = dict(max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2)
    res = generate_book_resumable(out, **kw)
    mem = generate_selective(**kw)
    assert res == mem == load_book(out)


def test_resume_after_simulated_crash(tmp_path: Path) -> None:
    """途中で落ちても、同一引数で再呼び出しすると最後まで完走し全量一致する。"""
    out = tmp_path / "book.json"
    kw = dict(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2, checkpoint_every=2)
    full = generate_selective(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2)

    orig = book_mod._engine_search
    calls = {"n": 0}

    def crashing(board, depth, time_limit, engine=None):
        calls["n"] += 1
        if calls["n"] > 5:
            raise RuntimeError("simulated crash")
        return orig(board, depth, time_limit)

    book_mod._engine_search = crashing
    try:
        try:
            generate_book_resumable(out, **kw)
        except RuntimeError:
            pass
        assert out.exists()  # 途中保存されている (book ファイル自体がチェックポイント)
    finally:
        book_mod._engine_search = orig

    resumed = generate_book_resumable(out, **kw)  # 再開 → 完走し全量一致
    assert resumed == full


def test_extend_to_more_plies_reuses_existing(tmp_path: Path) -> None:
    """完走 book を max_plies を増やして再実行すると、延長され既存手数は再探索しない。"""
    out = tmp_path / "book.json"
    kw = dict(depth=6, owner=0, ai_width=1, opp_width=2)
    small = dict(generate_book_resumable(out, max_plies=3, **kw))  # 3 手まで完走

    # 4 手へ延長。既存 (3 手まで) は再探索されず、新規の局面だけ探索される。
    orig = book_mod._engine_search
    calls = {"node": 0}

    def counting(board, d, tl, engine=None):
        calls["node"] += 1
        return orig(board, d, tl)

    book_mod._engine_search = counting
    try:
        big = generate_book_resumable(out, max_plies=4, **kw)
    finally:
        book_mod._engine_search = orig

    # 延長結果は最初から 4 手で作った選択的 book と一致 (再利用しても等価)。
    assert big == generate_selective(max_plies=4, **kw)
    # 既存 3 手のエントリは保持され、4 手 book はそれを包含する。
    assert set(small).issubset(set(big)) and len(big) > len(small)
    # フル再生成より探索回数が少ない (既存ノードを再探索していない)。
    fresh_calls = {"n": 0}

    def counting2(board, d, tl, engine=None):
        fresh_calls["n"] += 1
        return orig(board, d, tl)

    book_mod._engine_search = counting2
    try:
        generate_book_resumable(tmp_path / "fresh.json", max_plies=4, **kw)
    finally:
        book_mod._engine_search = orig
    assert calls["node"] < fresh_calls["n"]


def test_deepen_upgrades_visited_entries(tmp_path: Path) -> None:
    """depth を増やして再実行すると、深い探索木の各局面が depth8 へ更新される。

    注: depth を変えると最善手・順位が変わり選択的木の形が変わりうるので、浅い木にしか
    無かった局面は古い depth のまま残る (book は深い木を包含する superset になる)。
    クリーンに作り直したいときは別ファイルへ生成する。
    """
    out = tmp_path / "book.json"
    generate_book_resumable(out, max_plies=2, depth=4, owner=0, ai_width=1, opp_width=2)
    deep = generate_book_resumable(out, max_plies=2, depth=8, owner=0, ai_width=1, opp_width=2)
    sel8 = generate_selective(max_plies=2, depth=8, owner=0, ai_width=1, opp_width=2)
    # depth8 の木の各エントリは深く更新されて book に存在する。
    assert all(deep[k] == sel8[k] for k in sel8)
    assert set(sel8).issubset(set(deep))


def test_both_into_same_file_equals_selective_both(tmp_path: Path) -> None:
    """同じ out へ owner=0→owner=1 を生成すると generate_selective('both') と一致。"""
    out = tmp_path / "book.json"
    kw = dict(max_plies=3, depth=6, ai_width=1, opp_width=2)
    generate_book_resumable(out, owner=0, **kw)
    both = generate_book_resumable(out, owner=1, **kw)
    assert both == generate_selective(owner="both", **kw)


def test_profile_single_segment_equals_scalar(tmp_path: Path) -> None:
    """全 ply を覆う 1 区間の profile は scalar 指定と一致 (サニティ)。"""
    a = generate_book_resumable(
        tmp_path / "a.json", max_plies=3, depth=6, owner=0, ai_width=1, opp_width=2
    )
    b = generate_book_resumable(
        tmp_path / "b.json", max_plies=3, depth=6, owner=0, profile=[(3, 6, 1, 2)]
    )
    assert a == b


def test_profile_phase_connect_on_extend(tmp_path: Path) -> None:
    """早い区間を変えずに深い区間を足して延長すると、一括生成と一致し早い手数は再利用される。"""
    out = tmp_path / "book.json"
    early = [(3, 6, 1, 2)]               # 0-3手: depth6/相手2手
    full = [(3, 6, 1, 2), (5, 4, 1, 1)]  # +4-5手: depth4/相手1手 (浅く狭く)
    small = dict(generate_book_resumable(out, max_plies=3, depth=6, owner=0, profile=early))
    big = generate_book_resumable(out, max_plies=5, depth=6, owner=0, profile=full)
    # 一括生成 (profile=full) と一致 = 異なるパラメータでも接続する。
    fresh = generate_book_resumable(tmp_path / "fresh.json", max_plies=5, depth=6, owner=0, profile=full)
    assert big == fresh
    # 早い手数 (0-3, depth6) のエントリはそのまま保持される。
    assert all(big[k] == small[k] for k in small)


def test_cutoff_truncates_decided_lines(tmp_path: Path) -> None:
    """cutoff で評価が ±N 以上の変化を打ち切ると book が小さくなる。巨大 cutoff は無効化と同じ。"""
    kw = dict(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2)
    full = generate_book_resumable(tmp_path / "full.json", **kw)
    huge = generate_book_resumable(tmp_path / "huge.json", cutoff=10**9, **kw)
    assert huge == full  # 決して発火しない cutoff は無指定と同じ
    cut = generate_book_resumable(tmp_path / "cut.json", cutoff=1, **kw)
    assert set(cut).issubset(set(full))  # 打ち切りで訪れる局面は減る
    assert len(cut) < len(full)


def test_shared_tt_generation_is_repeatable_and_valid() -> None:
    """shared_tt=True の生成は反復可能 (同順序で同結果) で、合法手のみの妥当な book。

    共有 TT は fresh とビット一致しない場合があるが、生成順が固定なので同一引数の再生成は
    同じ book になる (決定的)。Rust 拡張が無ければ fresh にフォールバックするだけ。
    """
    kw = dict(max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2, shared_tt=True)
    a = generate_selective(**kw)
    b = generate_selective(**kw)
    assert a == b and len(a) > 0  # 反復可能・非空
    move, _ = book_move(a, Board())
    assert move in Board().legal_moves()  # 妥当 (合法手)


def test_shared_tt_resumable_runs(tmp_path: Path) -> None:
    """shared_tt=True で再開可能生成が走り、妥当な book を出力する。"""
    out = tmp_path / "book.json"
    book = generate_book_resumable(
        out, max_plies=4, depth=6, owner=0, ai_width=1, opp_width=2, shared_tt=True
    )
    assert len(book) > 0 and book == load_book(out)
    assert book_move(book, Board())[0] in Board().legal_moves()


def test_expansion_collapses_forced_block() -> None:
    """即詰めの受けが強制な局面は opp_width>1 でも受け1本だけ展開する。"""
    from score_four.book import _children_to_expand
    from score_four.search import search

    b = Board()
    for c in (0, 4, 1, 5, 2):  # 先手0 が a1,b1,c1。次に col3(d1)で勝てる。手番=後手
        b.play(c)
    _score, best = search(b, 6)
    assert best == 3  # 後手は col3 で受けるしかない
    # opp_width=3 でも、受けない手は即負けなので 1 本に畳まれる。
    assert _children_to_expand(b, best, width=3, depth=6, time_limit=None) == [3]


def test_expansion_keeps_choices_when_not_forced() -> None:
    """強制でない局面 (選択肢あり) は上位 width 本を残す。"""
    from score_four.book import _children_to_expand
    from score_four.search import search

    b = Board()
    b.play(5)  # 1手だけ。応手に強制はなく負けない手が複数ある。
    _score, best = search(b, 6)
    got = _children_to_expand(b, best, width=3, depth=6, time_limit=None)
    assert len(got) == 3 and best in got  # 選択肢があるので畳まれない


def test_committed_book_loads_if_present() -> None:
    """コミット済み data/opening_book.json があれば、空局面に合法な手を返す。"""
    path = Path(__file__).resolve().parents[1] / "data" / "opening_book.json"
    if not path.exists():
        return  # 未生成ならスキップ (純粋な機能テストは上で済んでいる)
    book = load_book(path)
    assert len(book) > 0
    move, _score = book_move(book, Board())
    assert move in Board().legal_moves()
