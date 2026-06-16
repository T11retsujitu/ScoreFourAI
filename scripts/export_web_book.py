"""data/opening_book.json から Web 用のコンパクト定石 web/book.json を書き出す。

Web book は照会に必要な最小限のみ: ``{key_str: [move_canonical, score]}``。
WASM が起動時に sf_book_add で取り込み、sf_book_move/_score で照会する。
score は手番側視点・D4 不変なので変換不要。move は正規形の最善柱（照会時に WASM 側で
inv_col_perms により現局面の柱へ写す）。

使い方:
    PYTHONPATH=src python scripts/export_web_book.py [in_path] [out_path]
"""
import json
import sys
from pathlib import Path

from score_four.book import load_book


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/opening_book.json")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("web/book.json")
    book = load_book(src)  # {key:int -> (move, score, depth, ply)}
    entries = {str(k): [v[0], v[1]] for k, v in book.items()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"format": "score-four-web-book/1", "entries": entries},
                   separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"exported {len(entries)} entries ({out.stat().st_size} bytes) "
          f"from {src} -> {out}")


if __name__ == "__main__":
    main()
