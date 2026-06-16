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

### 使い方（フラグ式）

```
python scripts\generate_book.py [out] --plies N --depth D --owner both --opp-width W [...]
```

| フラグ | 既定 | 意味 |
|--------|------|------|
| `out`（位置引数） | `data\opening_book.json` | 出力ファイル |
| `--plies` | 6 | 定石を作る手数（`--profile` 指定時は無視） |
| `--depth` | 10 | 各局面の探索深さ（`--profile` 指定時は無視） |
| `--owner` | both | `0`=先手 / `1`=後手 / `both`=両側生成して統合 |
| `--opp-width` | 4 | **相手手番**で展開する上位手数（robust。大きいほど網羅的） |
| `--ai-width` | 1 | **自分手番**で展開する上位手数（1=最善のみ） |
| `--profile` | なし | **フェーズ別**パラメータ（後述）。`until:depth:ai:opp` をカンマ区切り |
| `--cutoff` | なし | 局面の評価が **±N 以上**なら決着が見えたとみなしその変化を打ち切る |
| `--time-ms` | 0 | `>0` で固定時間/手（既定 0=固定深さ） |
| `--shared-tt` | off | 局面間で置換表を共有して**高速化**（下記の注意。生成が遅いとき向け） |

> 注: **強制手（即詰めの受け・ダブルリーチ阻止・合法手1つ）は `opp_width` に関わらず 1 本に
> 畳まれ**、負けが読み切れた手は展開されない。なので `opp_width` は「本当に選択肢がある所」での
> 枝数。

### まず小さく試す（速度の目安を掴む）

```powershell
python scripts\generate_book.py data\opening_book.json --plies 6 --depth 10 --opp-width 4 --owner both
```
ply ごとに `ply3: 18 entries (5s)` のように進捗が出る。所要時間の見当をつけてから手数や幅を上げる。

### フェーズ別に読む（序盤=広く浅く / 中盤=深く広く / 終盤=狭く深く）

序盤は手が広いので深く・多くは読めない、終盤は手が狭いので深く読める。`--profile` で
**手数ごとに `depth` と幅を変える**:

```powershell
# 0-8手: depth10/相手6手(広く浅く) / 9-16手: depth14/相手4手(深く広く) / 17-30手: depth18/相手2手(狭く深く)
python scripts\generate_book.py data\opening_book.json --profile 8:10:1:6,16:14:1:4,30:18:1:2 --owner both --cutoff 50
```
各区間は `until_ply:depth:ai_width:opp_width`。最大手数は profile の最後の `until_ply`。

### 高速化（`--shared-tt`）

`--shared-tt` を付けると、定石生成中に**局面間で置換表(TT)を共有**する。隣接する局面は
合流（transposition）で部分木が大きく重なるので、その読み直しを省いて**生成が速くなる**
（深いほど効く）。

> **注意（トレードオフ）**: 共有 TT は「要求より深いエントリ」も再利用するため、近傍局面が
> 先に深く読んだ所は**より深い値**で返りうる。結果のエントリは妥当（公称 depth 以上の探索結果）
> だが、**探索順に依存して fresh（既定）とビット一致しない**ことがある。生成順が固定なら同じ
> 引数の再生成は同じ book（反復可能）。**厳密な再現性を最優先するなら付けない**、生成時間を
> 縮めたいときに付ける、という使い分け。

### 評価打ち切り（`--cutoff`）

`--cutoff 50` のように指定すると、ある局面の評価値の**絶対値が指定値以上**（＝決着が見えた）に
なった変化はそこで**打ち切って記録**し、それ以上展開しない。決着済みの深掘りを避けて book を
締める（その先はエンジンが指せる）。厳密な読み切りではなく評価値ベースの早期打ち切り。

> **値の目安（重要）**: この評価は**チェスのセンチポーンとは桁が違い小さい**（`open-3=25` 等）。
> 実測では非詰み局面の評価は中央値 ~11・最大 ~86。**`100` 以上は非詰み局面では発火せず実質
> 無指定**（詰みは元々強制枝刈りで畳まれる）。入れるなら **30〜50** が目安（軽め=50、しっかり
> 締める=30）。評価は勝率に較正されていないので、安全側なら高めか、cutoff を使わず手数・幅で締める。

### 途中保存・再開（このガイドの肝）

**book ファイル自体がチェックポイント**。生成中は `out_path` へ周期的に**原子保存**される
（書き込み中に落ちてもファイルは壊れない）。別の管理ファイルや中間ファイルは作らない。

- **`Ctrl + C` で安全に中断できる。** 直近の保存以降に探索した局面だけがやり直しになる。
- **同じコマンドをもう一度実行すると、保存済みの局面を再利用して続きから生成する。**
- 長時間回すときは、Windows の電源設定でスリープ/休止を無効化し、ターミナルを閉じないこと。

### 追加編集・延長（「10手目まで作った後に 11手目以降を別パラメータで足す」はここ）

完走した book へ追記するときも**同じ `out` に再実行**するだけ。既存エントリは再利用される。

- **手数を伸ばす（同パラメータ）**: `--plies` を増やして再実行。既存手数は**再探索せず再利用**、
  増えた手数だけ探索する（進捗は既存 ply が一瞬で流れる）。
- **フェーズ別に接続して延長（推奨）**: profile の**早い区間を据え置き、後ろに深い手数の区間を
  足して**再実行する。早い手数は同 `depth` なので再利用され、**異なる depth/幅でも接続**する:
  ```powershell
  # 1回目: 10手まで (depth12/相手6手)
  python scripts\generate_book.py data\opening_book.json --profile 10:12:1:6 --owner both
  # 2回目: 11-20手を狭く深く(depth16/相手3手)で追加。早い区間 10:12:1:6 は据え置く
  python scripts\generate_book.py data\opening_book.json --profile 10:12:1:6,20:16:1:3 --owner both
  ```
  2回目は ply0..10 が再利用（一瞬）、ply11..20 だけ実探索される。
- **網羅を広げる**: `--opp-width`（または profile の `opp` 値）を上げて再実行すると、新たに増えた
  相手手の枝を追加探索する（既存枝は再利用）。
- **手を深くする（`depth` 増）**: 浅い既存エントリを深く探索し直す。ただし最善手・順位が変わると
  選択的木の形も変わり、**古い木にしか無い局面は古い depth のまま残る**（book は superset に）。
  完全にクリーンな作り直しが要るときは**別ファイルへ生成**する。
- 既存の別ファイルと統合したいときは Python から `merge_book(a, b)`（深い `depth` 優先）。

> **接続のコツ**: 早い手数の区間（`depth`・幅）を変えない限り、後ろの手数を別パラメータで何度
> 足しても整合する。早い区間を変えると木の形が変わり古いエントリが残る（無害だが superset）。

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

## 5. Web アプリに載せる（定石をブラウザで使う）

生成した定石を Web アプリ（`web/`）に載せると、**序盤は探索せず即・定石手**で応じ「定石」表示も出る。

```powershell
# 1) data/opening_book.json → web/book.json（Web 用の最小形）を書き出す
$env:PYTHONPATH = "src"
python scripts\export_web_book.py
# 2) (book API を含む) エンジンを WASM 化（既にビルド済みなら省略可）
bash scripts\build_wasm.sh        # Git Bash 等。または WSL / 既存の web/engine.wasm を使う
# 3) ローカル確認
cd web ; python -m http.server 8000   # → http://localhost:8000
```

- 起動すると worker が `web/book.json` を読み込み、コントロール部に「**定石 N局面 読込済**」と出る。
- 定石にある局面ではエンジンが**即応**（探索なし）、人間の番でも「**定石の手**」として推奨表示。
- デプロイ: `web/book.json`（と更新した `web/engine.wasm`）をコミットして GitHub Pages へ。
  book を作り直したら **手順 1 を再実行**して `web/book.json` を更新する。
- 大きい book はそのまま積むと重いので、Web 用は**薄め**（深すぎない／principal 寄り）が無難。

---

## 6. トラブルシューティング

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
