# 定石の下流活用 — 設計メモ

> 定石（opening book）を起点にした下流活用。**(1) Web ロードは実装済み**、**(2) 自己学習は
> 未実装（アイデア）**。着手時はそれぞれ独立コミット＋計測で進める（[`../CLAUDE.md`](../CLAUDE.md)）。
> 関連: 生成は [`opening_book_windows.md`](opening_book_windows.md) / Phase 6・8・9
> [`roadmap.md`](roadmap.md)。

book は **D4 正規化局面キー(u128) → (move, score, depth, ply)** の DAG（[`../src/score_four/book.py`](../src/score_four/book.py)）。
以下はその活用案。

---

## 1. Web アプリへの book ロード（✅ 実装済み）

**目的**: WASM Web アプリ（[`../web/`](../web/)）が序盤で book を参照し、**探索せず即応**＋「定石」表示。

**実装**（案 A を採用）:
- `scripts/export_web_book.py`: `data/opening_book.json` → `web/book.json`（`{key:[move,score]}` の最小形）。
- WASM C-ABI: `sf_book_clear` / `sf_book_add(key_lo,key_hi,mv,score)` / `sf_book_move(b0,b1)->i32` /
  `sf_book_score(b0,b1)->i64` / `sf_book_size`（`thread_local` の `HashMap`。照会は**エンジン内部の
  `canonical`＋`inv_col_perms`** で現局面の柱へ写すのでキー一致を保証）。
- `engine-worker.js`: 起動時に `book.json` を fetch して `sf_book_add` で取り込み、検索要求は
  **book を先に照会**（ヒットなら探索せず即応・`book:true`）。`app.js`: 「定石」バッジ／推奨手表示、
  読込局面数バッジ。Python `book_move` と node で同値確認済み（299 局面）。

以下は当初の設計検討（案の比較・記録）。

### 照会の所在（2 案）

- **(A) WASM 側で照会（推奨）**: エンジンに book をロードし、`sf_book_move(b0,b1)` が**エンジン内部の
  canonical 計算**で引く。book のキーと必ず一致する（JS に D4 正規化を再実装しなくてよい）。
  - 追加 C-ABI 案: `sf_book_load(ptr,len)`（コンパクト book を取り込む）、`sf_book_move(b0,b1)->i32`
    （無ければ -1）、必要なら `sf_book_score`。WASM はメモリに book を保持。
- **(B) JS 側で照会**: book JSON を配り、JS が canonical（`COL_PERMS`/`canonical` を JS へ移植）して引く。
  WASM 改変不要だが、**D4 正規化を JS で厳密に再現する必要**があり不一致リスク。

→ **(A) を推奨**（正規化ロジックの二重実装と不一致を避ける）。

### コンパクト web book

学習・解析用の大きな book（score/depth/ply 付き）とは別に、**Web 用は最小限**に:
- `canonical_key(u128) → best_move(u8)`（必要なら score も表示用に）。
- 形式案: パック binary（N×(16B key + 1B move) ≈ 17N バイト）または hex-key→move の JSON。gzip 可。
- 生成スクリプト案: `scripts/export_web_book.py` が `data/opening_book.json` → `web/book.bin`。
  深い book はサイズが大きいので、Web には **principal＋robust の薄い book** を別に書き出すのも手
  （巨大 training book をそのまま積まない）。

### UI / フロー

- 対局フロー（`choose_move` 相当）: 手番側が book にあれば即応、無ければ WASM 探索。
- 「**定石**」バッジ表示（book 由来の手）、任意で book の score/depth を併記。
- ビルド: Windows で book 生成 → export → `web/book.bin` をコミット → Pages デプロイ。

### 注意

- 照会は局面ベースで**手順非依存**（transposition でも当たる）。決定的。
- サイズ管理（深い book は MB 級 → lazy-load / 薄い web book / トリム）。
- 既存 WASM API（search/eval/solve）は不変のまま**加算的**に追加する。

---

## 2. book を正とした自己学習（🧪 Stage 1 診断＝no-signal）

**目的**: book（深い探索の最善手＋score）を**教師データ**に、CPU で高速・決定的に推論できる
小モデルを学習して**固定時間での棋力**を上げる。

### Stage 1 診断の結果（`scripts/learn_from_book.py`・人間対局なし）

エンジン統合の前に**安価で決定的な診断**を実施: book 局面（1221）を教師に「book の最善手 =
線形評価で選べるか」を測った（14 次元 = `features`6 + `geometric_features`8、D4 不変・整数を
train 統計で標準化し、構造化パーセプトロンで選好学習。ホールドアウト move 一致率を比較）。

| 1-ply 選択器 | top-1 (holdout) | top-3 |
|---|---:|---:|
| **learned**（book を教師に選好学習） | **0.357** | 0.598 |
| **default_eval**（既存評価で子を順位付け） | **0.426** | 0.676 |
| 中央寄り | 0.119 | — |
| ランダム期待 | ~0.062 | — |

**所見**: 学習した線形ポリシー（0.357）は **既存 `default_eval`（0.426）に届かない**（train 0.392→
holdout 0.357 で過学習気味＝この小データで線形は頭打ち）。しかも最良の 1-ply 予測器
（default_eval）でも 43% 止まりで、**深さ14/16 の book 最善手は 1-ply 線形では再現しきれない**
（数手先の戦術依存）。Phase 8（学習評価で負け）・Phase 10（幾何中立）と同じく、**調整済み
default_eval を線形モデルで上回れない**。

**判断**: **no-signal。** 着手順序バイアス／評価統合（A/C）・自己対局へは進めない（ポリシーが
default 未満なので改善は望み薄）。**book の価値は直接照会（Web ロード・実装済み §1）**にあり、
線形評価の教師データとしては限定的、と結論。診断スクリプトは資産として保持。

**もし再挑戦するなら**（計測で勝ち越して初めて採用）: (a) より深い／大きい book でデータ増、
(b) 案 B（勝敗教師のロジスティック）も同特徴では同様の頭打ちが予想される、(c) 非線形小モデル
（量子化 MLP/小 GBDT）は非目標寄りで Phase 8 の fit≠strength リスクも残る。**期待値は低い**。

> 余談（別軸の観測）: default_eval は中央寄り順（0.119）よりずっと良い手予測器（0.426）。これは
> **評価ベースの着手順序**が探索を速める可能性を示すが、book 自己学習とは別の最適化で、既存の
> killer/history もあるため別途計測が要る（今回は対象外）。

以下は当初の設計検討（候補の比較・記録）。

### Phase 8 の教訓を踏まえる（最重要）

Phase 8（深い αβ を教師に score を最小二乗回帰）は当てはまり良好でも自己対局で負けた
（**fit ≠ strength**、[`eval_measurements.md`](eval_measurements.md) 仮説5）。よって:
- **score の素朴な回帰はしない**（同じ罠）。
- book が与えるのは主に **(局面 → 最善手)**。強さに揃う目的は「**book の手を選べるか**」
  （move 一致 / ランキング）で、**採否は固定時間自己対局の勝率**で判断する。

### 学習の方向（候補）

- **A. ポリシー蒸留（move 一致）**: book の最善手（16 柱の分類）を D4 不変特徴から予測する小モデル。
  これを**着手順序のバイアス**に使う（より良い順序＝速いカット＝同時間で深く）。順序ヒントなので
  **正しさを壊さず低リスク**。指標: ノード削減＋自己対局。
- **B. 勝敗教師の評価学習**: book のラインをエンジンで終局まで打って **勝敗(win/loss)** をラベルに
  ロジスティック回帰で評価を学習（Phase 8 の「次の候補」）。目的が「勝ち」に揃う。→ A/B 自己対局。
- **C. 選好（margin）学習**: 各 book 局面で「book の手 ≧ 兄弟手＋margin」を満たすよう評価を学習
  （探索が最善と証明した手を最上位に）。score でなく **手の順位**を教師にする。指標: move 一致率＋自己対局。

### 共通方針（規律）

- **特徴量は既存資産を再利用**: Phase 8 の `features`(NF=6) / Phase 10 の `geometric_features`(GEO_NF=8)。
  D4 不変・整数で決定的。`depth` の高い book エントリ＝高品質として絞れる。
- **採用条件**（[`roadmap.md`](roadmap.md) Phase 8 と同じ）: 100/200ms 自己対局で勝ち越し・多シード再現・
  ホールドアウト・D4 不変・WASM 実行可・小サイズ・**浮動小数の非決定性回避**（学習は offline、推論は整数）。
- **既定は不変**: 勝ち越して初めて `default_eval` へ統合。中立/悪化なら既定オフの資産として保持。

### 注意 / リスク

- **循環性**: book はエンジン出力の派生物なので、それを真似ても「今のエンジンの再現」止まりになりうる。
  価値は「**浅い推論で深い book 品質を近似 → 固定時間で強い**」点にあり、これは必ず計測で確かめる。
- 非目標: AlphaZero / GPU / 大型 NN / score の無条件回帰 / 計測前の既定変更。

---

## 進め方（着手時）

1. **Web book ロード**: `export_web_book.py`（薄い web book）→ WASM `sf_book_*`（案 A）→ app.js 配線
   → 「定石」表示。既存 API 不変・加算的。
2. **book 自己学習**: A（順序バイアス）か B/C（勝率/選好）を 1 つずつ、特徴量を絞って計測 → 勝ち越せば採用。

どちらも独立 PR・計測駆動で進め、本メモを結果で更新する。
