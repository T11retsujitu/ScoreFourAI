"""定石 (opening book) の生成・保存・照会。

設計 (docs/design.md 5.3 / CLAUDE.md / docs/roadmap.md Phase 6): 序盤の各局面で深い探索の
最善手と評価値を保存し、既知局面は即座に着手できるようにする。**強いエンジンの出力として
抽出される派生物**であり、手で書くものではない。

索引は **D4 正規化キー** (symmetry.canonical)。同じ軌道の局面は 1 エントリを共有し、
保存する最善手は正規形の柱番号にしておく。照会時は現局面 -> 正規形の変換 t で逆写像し、
現局面の柱へ戻す (探索の置換表と同じ流儀)。

エントリ (形式 v2・lean): ``book[canonical_key] = (best_move_canonical, score, depth, ply)``
  best_move_canonical: 正規形での最善柱 (0..15)
  score: 手番側視点の評価値 (探索の返り値)
  depth: その手を求めた探索深さ (品質指標。追加編集で深い探索に上書きするときの単調性に使う)
  ply : その局面の手数 (= 正規化キーから一意に決まる)

旧形式 v1 のエントリ ``(move, score, ply)`` も読み込める (depth は 0 = 不明として正規化する)。
追加編集・再開可能生成・選択的生成・自己学習 (book を教師) を見据えた lean な 4 要素。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from .board import Board
from .symmetry import COL_PERMS, INV_COL_PERMS, canonical

# book の型: 正規化キー(int) -> (正規形の最善柱, score, depth, ply)
Entry = tuple[int, int, int, int]
Book = dict[int, Entry]


def _make_engine() -> object | None:
    """局面間で TT を共有する永続エンジンを作る (無ければ None)。

    定石生成で合流 (transposition) する部分木の読み直しを省いて高速化する用。
    Rust 拡張が未ビルドなら None (純 Python 探索にフォールバック)。
    """
    try:
        import score_four_rs as rs

        return rs.Engine()
    except (ImportError, AttributeError):  # 拡張なし / 旧ビルドで Engine 無し
        return None


def _engine_search(
    board: Board, depth: int, time_limit: float | None, engine: object | None = None
) -> tuple[int, int]:
    """(score, best_move) を返す。engine があれば共有 TT で探索、無ければ fresh 探索。

    どちらも既定評価 (検証済みパリティ ALL/-8)。engine 経由は近傍局面と TT を共有して速い
    (探索順に依存し fresh とビット一致しない場合あり)。fresh 経路は Rust 拡張があれば使い、
    無ければ純 Python 探索。
    """
    if engine is not None:
        return engine.search(board.bb[0], board.bb[1], depth, time_limit)
    try:
        import score_four_rs as rs

        return rs.search(board.bb[0], board.bb[1], depth, time_limit)
    except ImportError:
        from .search import search as py_search

        return py_search(board, depth, time_limit=time_limit)


def generate_book(
    max_plies: int,
    depth: int,
    time_limit: float | None = None,
    on_ply: "Callable[[int, int, int], None] | None" = None,
    shared_tt: bool = False,
) -> Book:
    """root から max_plies 手までの全局面を D4 正規化で列挙し、各局面の最善手を保存。

    各局面で固定深さ (depth) の反復深化探索を行い、最善手と評価値を記録する。
    非終端局面のみ保存 (終端には着手が無い)。決定的。``on_ply(ply, n_positions,
    total)`` を渡すと各 ply 完了時に進捗を通知する。``shared_tt=True`` で局面間 TT を共有し
    高速化 (結果は fresh とビット一致しない場合あり)。
    """
    engine = _make_engine() if shared_tt else None
    book: Book = {}
    seen: set[int] = set()
    # frontier は各 ply の正規化ユニークな代表局面。
    frontier: list[Board] = [Board()]
    seen.add(canonical(0, 0)[0])

    for ply in range(max_plies + 1):
        # 現 frontier の各局面を探索して保存。
        for board in frontier:
            key, t = canonical(board.bb[0], board.bb[1])
            if board.is_terminal():
                continue
            _score, move = _engine_search(board, depth, time_limit, engine)
            book[key] = (COL_PERMS[t][move], _score, depth, ply)
        if on_ply is not None:
            on_ply(ply, len(frontier), len(book))

        if ply == max_plies:
            break

        # 次の ply の正規化ユニークな子局面を作る。
        next_frontier: list[Board] = []
        for board in frontier:
            if board.is_terminal():
                continue
            for col in board.legal_moves():
                child = board.copy()
                child.play(col)
                ckey = canonical(child.bb[0], child.bb[1])[0]
                if ckey not in seen:
                    seen.add(ckey)
                    next_frontier.append(child)
        frontier = next_frontier

    return book


def _rank_children(
    board: Board, depth: int, time_limit: float | None, engine: object | None = None
) -> list[tuple[int, int]]:
    """board の合法手を「手番側にとって良い順」に (柱, 値) で並べて返す (決定的)。

    各子局面を depth-1 で探索し、手番側視点の値 (-子の手番側スコア) で降順ソート。即勝ちは
    最上位、引分は中庸。値の絶対値が MATE_LO 超なら勝ち/負けを読み切った意味になり、
    敗北手 (値 <= -MATE_LO) の枝刈りに使う。選択的生成で展開する子を選ぶために使う。
    """
    from .search import WIN

    scored: list[tuple[int, int]] = []
    for col in board.legal_moves():
        child = board.copy()
        won = child.play(col)
        if won:
            cs = WIN  # 即勝ち = 手番側に最善
        elif child.is_terminal():
            cs = 0  # 引分
        else:
            s, _ = _engine_search(child, max(1, depth - 1), time_limit, engine)
            cs = -s  # 親 (手番側) 視点
        scored.append((cs, col))
    scored.sort(key=lambda x: (-x[0], x[1]))  # 値降順、同点は柱昇順 (決定的)
    return [(c, cs) for cs, c in scored]


def _children_to_expand(
    board: Board, best: int, width: int, depth: int,
    time_limit: float | None, engine: object | None = None
) -> list[int]:
    """手番側視点で展開する子柱を返す (best を先頭に必ず含む)。

    **敗北が読み切れた手 (値 <= -MATE_LO) は展開しない** → 真に強制な局面 (即詰めの受け・
    ダブルリーチ阻止・合法手1つ) は自動的に 1 本に畳まれる。負けない手が複数あれば
    (受ける／反撃してから受ける等) 上位 width 本を残す。探索駆動なので深いフォークも捕まる。
    """
    from .search import MATE_LO

    legal = board.legal_moves()
    if len(legal) == 1:
        return legal  # 合法手が1つ = オンリームーブ
    if width <= 1:
        return [best]  # principal (最善のみ)。ランキング不要。

    ranked = _rank_children(board, depth, time_limit, engine)  # [(柱, 値)] 良い順
    pool = [c for c, v in ranked if v > -MATE_LO]  # 敗北が確定した手は捨てる
    if best in pool:
        pool = [best, *(c for c in pool if c != best)]  # best を先頭へ
    else:
        pool = [best, *pool]  # 局面自体が負け or 近似差: best (最善の粘り) を必ず含める
    return pool[:width]


def generate_selective(
    max_plies: int,
    depth: int,
    owner: int | str = "both",
    ai_width: int = 1,
    opp_width: int = 2,
    time_limit: float | None = None,
    on_ply: "Callable[[int, int, int], None] | None" = None,
    shared_tt: bool = False,
) -> Book:
    """**選択的** 定石を D4 正規化で生成する (全列挙より木を絞る)。

    各局面で固定深さ探索の最善手を保存しつつ、展開する子は手番で絞る:
      - **自分 (owner) の手番**: 上位 ``ai_width`` 手だけ展開 (既定 1 = principal)。
      - **相手の手番**: 上位 ``opp_width`` 手を展開 (既定 2 = robust。大きいほど exhaustive)。
    ``owner`` は book を使う側 (0=先手 / 1=後手 / "both"=両側ぶんを生成して merge)。Web で
    エンジンがどちらを持っても応手できるよう、既定は "both"。決定的。エントリは v2 lean。

    全列挙 (generate_book) と違い ply 増でも木が緩やかにしか増えない。``on_ply`` で進捗通知。
    """
    if owner == "both":
        kw = dict(time_limit=time_limit, on_ply=on_ply, shared_tt=shared_tt)
        b0 = generate_selective(max_plies, depth, 0, ai_width, opp_width, **kw)
        b1 = generate_selective(max_plies, depth, 1, ai_width, opp_width, **kw)
        return merge_book(b0, b1)

    engine = _make_engine() if shared_tt else None
    book: Book = {}
    seen: set[int] = {canonical(0, 0)[0]}
    frontier: list[Board] = [Board()]

    for ply in range(max_plies + 1):
        next_frontier: list[Board] = []
        for board in frontier:
            if board.is_terminal():
                continue
            key, t = canonical(board.bb[0], board.bb[1])
            score, best = _engine_search(board, depth, time_limit, engine)
            book[key] = (COL_PERMS[t][best], score, depth, ply)
            if ply == max_plies:
                continue
            width = ai_width if board.turn == owner else opp_width
            for col in _children_to_expand(board, best, width, depth, time_limit, engine):
                child = board.copy()
                child.play(col)
                ckey = canonical(child.bb[0], child.bb[1])[0]
                if ckey not in seen:
                    seen.add(ckey)
                    next_frontier.append(child)
        if on_ply is not None:
            on_ply(ply, len(frontier), len(book))
        frontier = next_frontier

    return book


CKPT_FORMAT = "score-four-book-ckpt/1"

# フェーズ別パラメータ: (この ply まで, depth, ai_width, opp_width) の区間リスト。
# 例 [(8,10,1,6),(16,14,1,4),(30,18,1,2)] = 序盤 0-8 は depth10/相手6手、中盤 9-16 は
# depth14/4手、終盤 17-30 は depth18/2手。区間は until_ply 昇順。
Profile = list[tuple[int, int, int, int]]


def _ckpt_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.name + ".ckpt.json")


def _params_at(
    profile: Profile | None, ply: int, defaults: tuple[int, int, int]
) -> tuple[int, int, int]:
    """ply の (depth, ai_width, opp_width) を返す。profile が None なら defaults。"""
    if profile is None:
        return defaults
    for until, d, aw, ow in profile:
        if ply <= until:
            return (d, aw, ow)
    last = profile[-1]
    return (last[1], last[2], last[3])  # 最終区間を超えた ply は最終区間を使う


def generate_book_resumable(
    out_path: str | Path,
    max_plies: int,
    depth: int,
    owner: int = 0,
    ai_width: int = 1,
    opp_width: int = 2,
    time_limit: float | None = None,
    checkpoint_every: int = 200,
    on_progress: "Callable[[int, int], None] | None" = None,
    profile: Profile | None = None,
    cutoff: int | None = None,
    shared_tt: bool = False,
) -> Book:
    """**途中保存・再開・追加延長・フェーズ別**の選択的定石生成 (owner は 0 か 1)。

    **book ファイル自体がチェックポイント**。out_path を読み込み、root から max_plies まで
    D4 正規化で再列挙しながら、**既に十分な depth で探索済みの局面は再利用**し、未探索・浅い
    局面だけを探索する。checkpoint_every 局ごと＋各 ply 境界で原子保存。

    1 つの呼び出しで次がすべて成り立つ:
      - **中断後の再開**: 同じ引数で再実行すると途中保存された book から続きを生成。
      - **追加延長**: max_plies を増やして再実行すると既存を再利用し新しい手数だけ探索。
      - **フェーズ別パラメータ (`profile`)**: ply ごとに (depth, ai_width, opp_width) を変えられる
        (序盤=広く浅く / 中盤=深く広く / 終盤=狭く深く)。**早い手数の区間を変えなければ、後から
        深い手数を別パラメータで追加しても接続する** (早い手数は同 depth なので再利用される)。
      - **評価打ち切り (`cutoff`)**: 局面の評価値の絶対値が `cutoff` 以上なら勝敗が見えたとみなし
        **その変化を展開せず打ち切る** (記録はする)。決着済みの深掘りを避け book を締める。

    完走 book は in-memory の ``generate_selective(..., owner)`` と一致 (同 depth・cutoff なし)。
    owner="both" は owner=0/1 を **同じ out_path** へ順に生成 (共有局面再利用で和集合)。
    """
    out_path = Path(out_path)
    engine = _make_engine() if shared_tt else None
    book: Book = load_book(out_path) if out_path.exists() else {}
    seen: set[int] = {canonical(0, 0)[0]}
    frontier: list[Board] = [Board()]
    since = 0
    defaults = (depth, ai_width, opp_width)

    for ply in range(max_plies + 1):
        d, aw, ow = _params_at(profile, ply, defaults)
        next_frontier: list[Board] = []
        for board in frontier:
            if board.is_terminal():
                continue
            key, t = canonical(board.bb[0], board.bb[1])
            cur = book.get(key)
            if cur is not None and cur[2] >= d:
                best, score = INV_COL_PERMS[t][cur[0]], cur[1]  # 十分な深さの既存を再利用
            else:
                score, best = _engine_search(board, d, time_limit, engine)
                book[key] = (COL_PERMS[t][best], score, d, ply)
                since += 1
                if since >= checkpoint_every:
                    save_book(book, out_path)
                    since = 0
            if cutoff is not None and abs(score) >= cutoff:
                continue  # 評価が ±cutoff 以上 = 決着が見えた → この変化は打ち切り
            if ply < max_plies:
                width = aw if board.turn == owner else ow
                for col in _children_to_expand(board, best, width, d, time_limit, engine):
                    child = board.copy()
                    child.play(col)
                    ckey = canonical(child.bb[0], child.bb[1])[0]
                    if ckey not in seen:
                        seen.add(ckey)
                        next_frontier.append(child)
        if on_progress is not None:
            on_progress(ply, len(book))
        frontier = next_frontier
        save_book(book, out_path)  # ply 境界で保存

    save_book(book, out_path)
    _ckpt_path(out_path).unlink(missing_ok=True)  # 旧版の ckpt が残っていれば掃除
    return book


def book_move(book: Book, board: Board) -> tuple[int, int] | None:
    """book に board の手があれば (現局面の最善柱, score)、無ければ None。"""
    key, t = canonical(board.bb[0], board.bb[1])
    entry = book.get(key)
    if entry is None:
        return None
    move_canonical, score = entry[0], entry[1]
    return INV_COL_PERMS[t][move_canonical], score


def book_entry(book: Book, board: Board) -> tuple[int, int, int, int] | None:
    """book に board があれば (現局面の最善柱, score, depth, ply)、無ければ None。

    book_move のリッチ版。depth/ply も返すので解析・自己学習 (book を教師) で使える。
    """
    key, t = canonical(board.bb[0], board.bb[1])
    entry = book.get(key)
    if entry is None:
        return None
    move_canonical, score, depth, ply = entry
    return INV_COL_PERMS[t][move_canonical], score, depth, ply


def choose_move(
    book: Book,
    board: Board,
    depth: int,
    time_limit: float | None = None,
) -> tuple[int, int]:
    """book にあれば即座にその手、無ければ探索して (best_move, score) を返す。

    対戦・解析の入口。既知の序盤は探索せず book で即応し、book を抜けたら探索する。
    """
    hit = book_move(book, board)
    if hit is not None:
        return hit
    score, move = _engine_search(board, depth, time_limit)
    return move, score


FORMAT_V2 = "score-four-opening-book/2"


def _normalize_entry(value: list[int]) -> Entry:
    """v1 (move, score, ply) / v2 (move, score, depth, ply) を内部 4 要素へ正規化。

    v1 には深さ情報が無いので depth=0 (不明) とする。0 は追加編集の深さ単調更新で
    「どんな実深さよりも古い」とみなされ、再生成時に上書きされる。
    """
    if len(value) == 4:
        return (value[0], value[1], value[2], value[3])
    if len(value) == 3:  # v1: (move, score, ply)
        return (value[0], value[1], 0, value[2])
    raise ValueError(f"unrecognised book entry: {value!r}")


def _atomic_write(path: Path, text: str) -> None:
    """text を path へ原子的に書く (一時ファイル→fsync→os.replace)。

    書き込み中にプロセスが死んでも既存ファイルは壊れない (途中保存・Windows 耐性)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_book(book: Book, path: str | Path) -> None:
    """book を JSON で保存する (形式 v2・128bit キーは文字列化・原子的差し替え)。"""
    data = {
        "format": FORMAT_V2,
        "entries": {str(key): list(value) for key, value in book.items()},
    }
    _atomic_write(Path(path), json.dumps(data, separators=(",", ":")))


def load_book(path: str | Path) -> Book:
    """save_book で書いた JSON を読み込む (v1 / v2 とも可。内部 4 要素へ正規化)。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(key): _normalize_entry(value) for key, value in data["entries"].items()}


def merge_book(base: Book, extra: Book) -> Book:
    """2 つの book を統合する (新しい base を返す。引数は破壊しない)。

    同一キーは **より深い depth を優先** (品質単調)。depth 同値なら extra を採用
    (後から足したものを優先)。追加編集・選択的 book の合成・再開時の統合に使う。
    """
    merged: Book = dict(base)
    for key, entry in extra.items():
        cur = merged.get(key)
        if cur is None or entry[2] >= cur[2]:  # entry の depth が同等以上なら採用
            merged[key] = entry
    return merged
