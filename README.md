# score-four-ai

立体4目並べ（**Score Four / 重力あり立体四目並べ**）の **対戦・解析エンジン** と **定石** を作るプロジェクト。

> 最優先ゴール：**最小労力で最強の解析エンジン**。手法は **α-β 探索中心**。

---

## 対象ゲーム

- **Score Four**（4×4×4・重力あり）。自由配置版の **Qubic とは別物**。
- コマは選んだ柱の最下段に落ちる（高さは選べない）。
- 縦・横・斜めいずれかの直線に同色 4 つで勝ち。勝利ラインは全 **76 本**（軸 48・平面の斜め 24・立体対角線 4）。
- 探索特性：分岐 ≤16、深さ ≤64、D4 対称（8 重）、**ゲームとしては未解決**。
- 詳細は [`docs/rules.md`](docs/rules.md)。

## 方針（なぜ α-β か）

分岐 ≤16・深さ ≤64 と、確率的近似（AlphaZero）が本領を発揮する囲碁等に比べれば探索が効きやすい規模。だが「α-β なら確実に最強」という意味ではない：**脅威ベースの強制手枝刈り（下記アーキテクチャ 3）が効いて中盤で局面が終端まで解けて初めて**、決定的に深く読める α-β が AlphaZero より実質的に強く・軽くなる、という前提付きの判断。枝刈りの効きが弱ければ深さは頭打ちになりうる。AlphaZero は α-β が頭打ちになった後 or 学習目的のときのみ検討。
根拠と前提の全体像は [`docs/design.md`](docs/design.md) を参照（README 単体の結論で楽観しないこと）。

## アーキテクチャ（費用対効果の高い順）

1. ビットボード ＋ 76 ラインのマスク（勝利判定は増分）
2. 置換表（Zobrist hash） ← 効果最大
3. 脅威ベースの強制手枝刈り ← 実戦的強さを最も伸ばす
4. 着手順序（TT手 → 勝ち手 → 中央 → killer/history）
5. 対称性圧縮（D4・8 重）
6. 反復深化 ＋ PVS（＋時間制御）
7. 評価関数（脅威カウント ＋ 奇偶パリティ）※下記の「※」参照

> ※ 奇偶（パリティ）は **確立した理論ではなく経験的ヒューリスティック**。Connect Four の奇/偶脅威理論は 2D・7 列・先手が奇数段という構造に依存し、Score Four へそのまま移植できる保証はない。本プロジェクトでは**自己対戦で計測**し、多シード集計で頑健に勝ち越す設定（mode=ALL, weight=-8）を `default_eval` として採用した（depth4 集計 winrate ≈ 0.59）。精緻化案（最下段のみ／即着手可能のみ）はトーナメントで棄却。計測の全経緯は [`docs/eval_measurements.md`](docs/eval_measurements.md)。

## ビルド順（依存）と進捗

1. ✅ **コア**：ビットボード＋着手生成＋勝利判定 → 総当たり参照実装でテスト
2. ✅ **α-β エンジン**：置換表＋脅威枝刈り＋対称性圧縮＋反復深化＋PVS（対戦・解析 AI 成立）
3. ✅ **評価**：自己対戦で計測しパリティ採用
4. ✅ **Rust 高速化**：コア＋探索＋評価を移植、Python と同値を契約テストで保証（約50〜60倍）
5. ✅ **定石**：根から深く読ませ最善手順（PV）を保存 → 自動生成（`book.py`）
6. ✅ **Web 対局アプリ**：エンジンを WASM 化した静的 3D アプリ（対局＋解析＋詰み探索）
7. ✅ **詰み探索・詰み問題生成**（`solve.py` / `problems.py`、Phase 7）。Rust 移植＋WASM 公開済み
8. （任意）AlphaZero／学習評価：α-β が頭打ちになった後 or 学習目的のときのみ。線形学習評価は
   Phase 8 で試作・計測したが対局で勝てず不採用（[`docs/roadmap.md`](docs/roadmap.md)）

> 強化フェーズ（着手順序強化・u16 mask・詰み探索・学習評価・df-PN 等）の状態と計測は
> [`docs/roadmap.md`](docs/roadmap.md)。**改善が計測で確認できない最適化は採用せず資産として保持**
> する方針（Threat Quiescence / Aspiration Window / 学習評価 / df-PN がこれに該当）。

## プロジェクト構成

```
score-four-ai/
├── README.md
├── CLAUDE.md            # Claude Code 用のプロジェクト規約・文脈
├── pyproject.toml
├── docs/
│   ├── rules.md             # ゲームのルール
│   ├── design.md            # 設計メモ（方針の全体像）
│   ├── roadmap.md           # 強化ロードマップ（Phase別の状態・計画）
│   ├── opening_book_windows.md # Windows(CPU)での環境構築〜定石生成ガイド
│   ├── eval_measurements.md # 評価関数の自己対戦計測ログ
│   └── benchmarks/          # 固定時間ベンチ・Phase別計測
├── src/score_four/
│   ├── board.py         # ビットボード／着手生成／勝利判定／winning_moves／from_bitboards
│   ├── lines.py         # 76 ラインの生成
│   ├── symmetry.py      # D4 対称性（8 重）正規化
│   ├── evaluate.py      # 評価（line_potential/threat/parity/default_eval、features/learned_eval）
│   ├── search.py        # α-β＋TT＋脅威枝刈り＋対称性＋反復深化＋PVS＋時間制御
│   ├── selfplay.py      # 自己対戦の計測ハーネス
│   ├── book.py          # 定石の生成・照会・保存（D4 正規化キー）
│   ├── solve.py         # 詰み探索（強制勝ちの証明・最短手数・詰み手順／零評価 αβ）
│   ├── problems.py      # 詰み問題の自動生成・検証・保存（初手一意・D4 重複除去）
│   ├── dfpn.py          # df-PN 詰み探索（Phase 7・計測で条件付き不採用＝資産保持）
│   └── learn.py         # 軽量学習評価のオフライン学習（Phase 8・計測で不採用＝資産保持）
├── rust/                # 高速版（PyO3 拡張 score_four_rs＋WASM）
│   ├── Cargo.toml / pyproject.toml   # maturin / wasm ビルド設定
│   └── src/{lib,board,lines,symmetry,evaluate,search}.rs  # コア＋探索＋評価
│       + python_api.rs（PyO3）/ wasm_api.rs（素の C-ABI：sf_search/sf_eval/sf_solve…）
├── scripts/generate_book.py      # 定石生成スクリプト
├── scripts/generate_problems.py  # 詰み問題生成スクリプト
├── scripts/train_eval.py         # 学習評価の訓練＋自己対戦 A/B 計測（Phase 8）
├── scripts/benchmark.py / benchmark_dfpn.py  # 固定時間ベンチ / df-PN ベンチ
├── scripts/build_wasm.sh         # エンジンを WASM 化して web/ へ配置
├── data/opening_book.json    # 生成済み定石（再生成可能）
├── web/                 # 3D 対局 Web アプリ（静的・WASM エンジン）
│   ├── index.html / app.js / engine-worker.js  # 対局＋解析＋「詰み探索」UI
│   └── engine.wasm      # ビルド済みエンジン（scripts/build_wasm.sh で再生成）
└── tests/               # 参照実装・契約テスト（言語横断・D4不変性含む）
```

## Web アプリ（3D 対局）

`web/` は **エンジンと対局できる静的 Web アプリ**。検証済みの Rust エンジンを
WebAssembly 化してブラウザ内で動かす（サーバ不要）。回せる3D盤＋4段スライス、
柱クリックで着手、エンジンが Web Worker で応手、評価値・推奨手・脅威を表示する。
**「詰み探索」ボタン**で現局面の強制詰み（最短手数・詰み手順）を読み切り、PV を盤上に
ハイライトする（`sf_solve`／Phase 7・9）。公開先は GitHub Pages（`.github/workflows/pages.yml`）。

```sh
# エンジンを WASM にビルド（rustup target add wasm32-unknown-unknown が必要）
./scripts/build_wasm.sh
# ローカルで起動（fetch のため http 経由で開く）
cd web && python3 -m http.server 8000   # → http://localhost:8000
```

デプロイ: `web/` を任意の静的ホスト（Netlify/Vercel 等）に置くだけ。GitHub Pages は
`.github/workflows/pages.yml` で自動デプロイできる（初回のみ設定 > Pages > Source を
"GitHub Actions" にする）。`engine.wasm` はコミット済みなのでビルド不要。

### Rust 高速版（任意・速度用）

ホットループ（コア＋探索＋評価）を Rust へ移植済み（設計 §6）。Python と**同一アルゴリズム**で、
言語横断契約テストにより結果一致を保証する。**拡張が無くても純 Python のスイートは独立に緑**
（Rust 契約テストは `importorskip` で skip）。

```sh
cd rust
maturin build --release
pip install --force-reinstall --no-deps target/wheels/score_four_rs-*.whl
# 以後 `import score_four_rs` が使え、tests/test_rust_*.py が Python 参照との一致を検証する。
```

## 使い方

```sh
# テスト（src レイアウト）
PYTHONPATH=src pytest -q

# Python から探索（手番側視点の (score, best_move) を返す）
PYTHONPATH=src python -c "
from score_four.board import Board
from score_four.search import search
b = Board()
for c in [5, 6, 9, 10]: b.play(c)
print(search(b, max_depth=8))            # 反復深化。time_limit=秒 も指定可
"

# 高速版（Rust）。bb=(先手, 後手) のビットボードを渡す
PYTHONPATH=src python -c "
import score_four_rs as rs
from score_four.board import Board
b = Board()
for c in [5, 6, 9, 10]: b.play(c)
print(rs.search(b.bb[0], b.bb[1], 10))   # Python 探索と同値・約50〜60倍速
"

# 定石（生成 → 照会）。既知の序盤は探索せず即応する。選択的・途中保存・再開可能
#   引数: max_plies depth out owner(0/1/both) opp_width ai_width（中断後は同コマンド再実行で続行）
# Windows(CPU) での環境構築〜生成は docs/opening_book_windows.md を参照
PYTHONPATH=src python scripts/generate_book.py 6 10 data/opening_book.json both 4 1
PYTHONPATH=src python -c "
from score_four.board import Board
from score_four.book import load_book, choose_move
book = load_book('data/opening_book.json')
print(choose_move(book, Board(), depth=12))   # 序盤は book、抜けたら探索
"

# 詰み探索（強制勝ちの証明・最短手数・詰み手順）
PYTHONPATH=src python -c "
from score_four.board import Board
from score_four.solve import solve
b = Board()
for c in [0, 1, 0, 2, 0, 3]: b.play(c)   # 先手が柱0で即詰み
print(solve(b))   # MateResult(status='win', plies=1, best_move=0, pv=(0,))
"

# 詰み問題の自動生成（mate-in-3 を 20 問、初手一意・D4 重複除去）
PYTHONPATH=src python scripts/generate_problems.py 3 20 data/mate_problems.json
```

## 開発の前提（非交渉）

**コア（着手生成・勝利判定）のバグは下流（探索・定石）を静かに全部汚染する。**
契約テストでコアを固めてから探索へ進む「**センサー先行**」を徹底する。

## ステータス

検証済みコア（lines/board）＋ 探索一式（α-β・TT・脅威枝刈り・**着手順序強化(killer/history)**・
D4対称性・反復深化＋PVS・時間制御）＋ 計測駆動の評価（多シード自己対戦・トーナメントでパリティ
ALL/-8 を採用）＋ **定石生成（`book.py`、D4 正規化・エンジン出力の派生物）**まで実装済み。
Rust 移植はコア＋探索＋評価を完了し、Python 探索と同値を言語横断契約テストで保証（探索は
Python 比 約50〜60倍、さらに killer/history でノード −37〜50%・u16 move mask で NPS +12〜15%）。
**設計の主要成果物（②対戦・解析 AI と ①定石）が揃い、Web 対局アプリも公開済み。**

**詰み探索・詰み問題生成（`solve.py` / `problems.py`、Phase 7）** を追加。全幅 negamax＋零評価を
参照に詰み手数を契約検証し、**Rust 移植（`search::solve`）＋ WASM 公開（`sf_solve`）＋ Web の
「詰み探索」UI**（Phase 9）まで通している。

**計測で不採用＝資産として保持**：Threat Quiescence（中立）、Aspiration Window（悪化）、
**軽量学習評価（Phase 8。教師への当てはまりは良いが対局で勝てず＝fit≠strength）**、
**df-PN 詰み探索（Phase 7。詰み証明は最大~300倍速だが詰みなし反証で劣り最短手数/PV を返さず
ドロップイン置換にならない）**。各 Phase の状態・計測は [`docs/roadmap.md`](docs/roadmap.md)、
評価の計測は [`docs/eval_measurements.md`](docs/eval_measurements.md)、ベンチは
[`docs/benchmarks/`](docs/benchmarks/)。

## 参考

- qweral 氏の立体四目並べシリーズ（戦略・機械学習・最強 AI・AlphaZero）: https://note.com/qweral
