# Windows（CPU）で定石を生成・利用するガイド

Windows の CPU 環境で、**環境構築 → 高速エンジン（Rust）導入 → 定石（opening book）生成 →
利用**までの手順。コマンドは **PowerShell** 前提（`cmd` の差分は各所に併記）。

> 定石生成は探索を大量に回すので、**Rust 拡張（`score_four_rs`）を入れて使うこと**を強く推奨。
> 純 Python でも動くが約 50〜60 倍遅く、深い定石は現実的でない。

---

## 0. 必要なもの

| ツール | 入手 | 備考 |
|--------|------|------|
| **Python 3.11+** | <https://www.python.org/downloads/> | インストール時「Add python.exe to PATH」にチェック |
| **Git** | <https://git-scm.com/download/win> | リポジトリ取得用 |
| **Rust（rustup）** | <https://rustup.rs/> （`rustup-init.exe`） | 既定の `stable-x86_64-pc-windows-msvc` でよい |
| **VS C++ Build Tools** | Visual Studio Installer →「C++ によるデスクトップ開発」 | Rust の MSVC リンクに必要（rustup が案内する） |

確認:
```powershell
py --version        # Python 3.11 以上
rustc --version     # rustup 導入後
```

---

## 1. リポジトリ取得と Python 仮想環境

```powershell
git clone https://github.com/T11retsujitu/ScoreFourAI.git
cd ScoreFourAI

py -m venv .venv
.\.venv\Scripts\Activate.ps1     # cmd の場合: .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install maturin pytest       # 拡張ビルドとテスト用
```

> PowerShell でスクリプト実行が拒否される場合は一度だけ:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## 2. 高速エンジン（Rust 拡張）をビルドして導入

`maturin develop` は **ビルドと仮想環境への取り込みを一括**で行う（wheel 名を気にしなくてよい）。
初回は pyo3 等のコンパイルで数分かかる。

```powershell
cd rust
maturin develop --release        # 仮想環境に score_four_rs を取り込む
cd ..
```

確認（`import` できて探索が返れば OK）:
```powershell
$env:PYTHONPATH = "src"           # cmd の場合: set PYTHONPATH=src
python -c "import score_four_rs as rs; from score_four.board import Board; b=Board();
[b.play(c) for c in (5,6,9,10)]; print(rs.search(b.bb[0], b.bb[1], 10))"
```

> 代替（wheel を作って配布したい場合）:
> `cd rust; maturin build --release` → `rust\target\wheels\score_four_rs-0.0.1-cp311-abi3-win_amd64.whl`
> を `pip install --force-reinstall --no-deps <そのファイル名>` で導入。

（任意）健全性チェック:
```powershell
python -m pytest -q               # pytest は src を自動で読む（PYTHONPATH 不要）
```

---

## 3. 定石を生成する

**重要**: スクリプトを動かす前に毎回（新しいターミナルごとに）`PYTHONPATH` を通す。
```powershell
$env:PYTHONPATH = "src"            # cmd の場合: set PYTHONPATH=src
```

### 使い方

```
python scripts\generate_book.py [max_plies] [depth] [out_path] [owner] [opp_width] [ai_width]
```

| 引数 | 既定 | 意味 |
|------|------|------|
| `max_plies` | 6 | 定石を作る手数（root からの ply 数）。大きいほど深く広い |
| `depth` | 10 | 各局面の探索深さ。大きいほど手が強いが遅い |
| `out_path` | `data\opening_book.json` | 出力ファイル |
| `owner` | `both` | `0`=先手 / `1`=後手 / `both`=両側生成して統合（Web でどちらも持てる） |
| `opp_width` | 4 | **相手手番**で展開する上位手数（大きいほど網羅的・ファイル大） |
| `ai_width` | 1 | **自分手番**で展開する上位手数（1=最善のみ＝principal） |

### まず小さく試す（速度の目安を掴む）

```powershell
python scripts\generate_book.py 6 10 data\opening_book.json both 4 1
```
ply ごとに `ply3: 18 entries (5s)` のように進捗が出る。これで所要時間の見当をつけてから
`max_plies` / `depth` / `opp_width` を上げる。

### 本生成の例（深め・網羅広め）

```powershell
python scripts\generate_book.py 10 12 data\opening_book.json both 6 1
```

### 途中保存・再開（このガイドの肝）

**book ファイル自体がチェックポイント**。生成中は `out_path` へ周期的に**原子保存**される
（書き込み中に落ちてもファイルは壊れない）。別の管理ファイルや中間ファイルは作らない。

- **`Ctrl + C` で安全に中断できる。** 直近の保存以降に探索した局面だけがやり直しになる。
- **同じコマンドをもう一度実行すると、保存済みの局面を再利用して続きから生成する。**
- 長時間回すときは、Windows の電源設定でスリープ/休止を無効化し、ターミナルを閉じないこと。

### 追加編集・延長（「14手目まで→15手目へ」はここ）

- **手数を伸ばす（plies 延長）**: 完走した book に対し、**同じ `depth`・同じ `owner`/幅で
  `max_plies` だけ増やして同じ `out_path` に再実行**する。既存の手数のエントリは**再探索せず
  再利用**し、増やした手数ぶんだけ探索する。例（14→15 手）:
  ```powershell
  python scripts\generate_book.py 14 12 data\opening_book.json both 6 1   # 1回目
  python scripts\generate_book.py 15 12 data\opening_book.json both 6 1   # 15手へ延長(再利用)
  ```
  進捗は ply0..14 が一瞬で流れ（再利用）、ply15 だけ実探索される。
- **網羅を広げる（`opp_width` 増）**: `opp_width` を上げて同じファイルに再実行すると、
  新しく増えた相手手の枝を追加探索する（既存枝は再利用）。
- **手を深くする（`depth` 増）**: `depth` を上げると浅い既存エントリを深く探索し直す。ただし
  最善手・順位が変わると選択的木の形も変わるため、**古い木にしか無い局面は古い depth のまま
  残る**（book は深い木を包含する superset になる）。完全にクリーンな作り直しが要るときは
  **別ファイルへ生成**する。
- 既存の別ファイルと統合したいときは Python から `merge_book(a, b)`（深い `depth` 優先）。

---

## 4. 生成した定石を使う

```powershell
$env:PYTHONPATH = "src"
python -c "from score_four.board import Board; from score_four.book import load_book, choose_move, book_entry;
book = load_book('data/opening_book.json');
b = Board();
print('book size:', len(book));
print('root best:', book_entry(book, b));   # (最善柱, score, depth, ply) or None
print('choose:', choose_move(book, b, depth=12))"  # book にあれば即応、無ければ探索
```

- `book_move(book, board)` → `(最善柱, score)` または `None`
- `book_entry(book, board)` → `(最善柱, score, depth, ply)` または `None`（解析・学習用）
- `choose_move(book, board, depth)` → book にあればその手、無ければ探索

---

## 5. トラブルシューティング

| 症状 | 対処 |
|------|------|
| `ModuleNotFoundError: score_four` | `$env:PYTHONPATH = "src"`（cmd: `set PYTHONPATH=src`）をそのターミナルで実行。リポジトリ直下で動かす |
| `import score_four_rs` できない / 遅い | 仮想環境を有効化し `cd rust; maturin develop --release` を実行。`import` できないと純 Python（低速）にフォールバックする |
| Rust ビルドで link エラー | VS の「C++ によるデスクトップ開発」（MSVC Build Tools）を入れる |
| 生成が遅すぎる | Rust 拡張が入っているか確認。`depth` / `max_plies` / `opp_width` を下げる。まず小さく試す |
| 中断したらどうなる？ | `out_path` は最後のチェックポイントで有効。同じコマンド再実行で続行 |

---

## 補足

- 定石は **エンジン出力の派生物**（固定深さ探索の最善手）。同じ引数なら**決定的に再現**する。
- 索引は D4 正規化キーなので、対称な序盤は 1 エントリを共有する（サイズが締まる）。
- ゆくゆくの目標（Web アプリへのロード、定石を正とした自己学習）は
  [`roadmap.md`](roadmap.md) Phase 6 / [`design.md`](design.md) を参照。
