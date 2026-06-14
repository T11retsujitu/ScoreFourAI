# 実験計画: 幾何・解放関係評価（Geometric / Relational Evaluation）

> ユーザー仮説に基づく**評価関数の独立実験**の設計・計測・採否計画。元の指示書を現行
> リポジトリに合わせて再構成したもの。**実装はまだ行わず**、本書をレビュー成果物として残す。
> 既存ロードマップ（[`../roadmap.md`](../roadmap.md)）の再実装ではなく、新しい評価仮説を
> **既定オフのオプトイン実験**として加える。実装は本書承認後に Commit 1 から着手する。

最重要前提（[`../../CLAUDE.md`](../../CLAUDE.md) の原則と一致）:

- **人間を評価相手・教師・ラベル作成者にしない。** 採否は候補評価 vs 既定評価の**自動
  自己対局・固定時間・多シード・先後入れ替え**だけで決める。ユーザーは仮説の発案者であり、
  対局データの供給者ではない。
- **計測で勝ち越すまで `default_eval` を変えない。** 新評価は初期状態で `geo_enabled=0` /
  `geo_weights=0`。中立/悪化なら既定オフの資産として保持（Phase 2/5/8/df-PN と同じ扱い）。
- 既定評価は維持: `default_eval = open line weights (1,5,25) + parity ALL/weight -8`。

---

## 1. 現行実装との重複確認（レビュー）

このセッション時点の実装と本仮説の関係を確認した。**作り直さない**もの:

| 既存資産 | 場所 | 本実験での扱い |
|---|---|---|
| 76 ラインマスク・増分勝利判定・`winning_moves` | `board.py` / `board.rs` | 再利用（ライン交差・playable 判定の基盤） |
| α-β / TT / 脅威枝刈り / D4 / 反復深化 / PVS / 時間制御 | `search.py` / `search.rs` | 不変（評価だけ差し替え可能な構造を利用） |
| `EvalConfig`（`parity_weight, immediate, parity_mode, weights[3], learned, lw[NF]`） | `evaluate.rs` | **加算的に** `geo_enabled` / `geo_weights[GEO_NF]` を追加 |
| `features()` / `NF=6`（Phase 8: `[open1,open2,open3,parity,reach3,center]`） | `evaluate.py` / `evaluate.rs` | **変更しない**。幾何特徴は別 API として追加 |
| `learned_eval` / `zero_config()` | `evaluate.*` | 不変（`zero_config` は常に 0 を返すこと＝詰み探索の前提） |
| `play_match` / `play_match_learned` 自己対局基盤 | `search.rs` / `python_api.rs` | 再利用（別の対局ループを重複実装しない） |
| 詰み探索 `solve` / df-PN | `solve.py` / `dfpn.py` / `search.rs` | 不変（`zero_config` 経由なので geo の影響を受けない） |
| 自己対局 A/B・固定時間ベンチ | `selfplay.py` / `benchmark.py` / `benchmark_dfpn.py` | 計測手法を踏襲 |

**重複が起こりやすい既存物**:

- **Phase 8 の `center` 特徴は別物。** 既存 `center` = 中央 2×2 柱（柱 5,6,9,10）の**全 16
  セル**占有数。本実験の `INTERIOR` = 立方体内部の**8 セル**（x,y,z すべて内側）。
  **`center` の意味を黙って変えない**（別名 `INTERIOR` を新設する）。
- **ライン占有特徴（`open1/2/3`）がセル種類差を一部内包している。** 後述 §3 の検証で
  CORNER/INTERIOR は 7 本・EDGE/FACE は 4 本のラインに属する（実コードで確認済み）。
  生きたライン評価は石数で加点するので、**単純な占有セル種類差（`occ_*`）は既存評価と
  強く相関・冗長**になりうる → 必ず単独 A/B で寄与を切り分ける。

---

## 2. 仮説（実コードで数値検証済み）

セル座標 `index = z*16 + y*4 + x`、`boundary(c)=c∈{0,3}`。外側にある軸数でセルを 4 分類:

| 種類 | コード名 | 外側軸数 | セル数 | 通る勝利ライン数 |
|---|---|---:|---:|---:|
| 角 | `CORNER` | 3 | **8** | **7** |
| 辺 | `EDGE` | 2 | **24** | **4** |
| 面 | `FACE` | 1 | **24** | **4** |
| 中心 | `INTERIOR` | 0 | **8** | **7** |

実 `CELL_LINES` で検算済み（セル数 8/24/24/8、次数 7/4/4/7、次数総和 304 = 76×4）。

重力を含めると 16 柱は 3 クラス（実コードで柱パターンも確認済み）:

```
COLUMN_CORNER (4本): CORNER → EDGE → EDGE → CORNER
COLUMN_EDGE   (8本): EDGE   → FACE → FACE → EDGE
COLUMN_CENTER (4本): FACE   → INTERIOR → INTERIOR → FACE
```

作業仮説（**確立理論ではなく検証対象**）:

1. 石を置いたセルの価値だけでなく、**その手で相手に解放される次セルの種類**が重要。
2. 単独セル価値ではなく、セル種類 × 支持関係 × ライン交差の組合せに意味がありうる。
3. 角柱では CORNER、中央柱では INTERIOR、辺柱では中段 FACE が実戦上効く可能性。

**本実験の主眼は単純占有点ではなく「テンポ＝手番が次に触れる／相手へ解放するセル種類」。**

---

## 3. Stage 構成

| 段階 | 内容 | 着手条件 |
|---|---|---|
| **Stage A** | 解釈可能な線形・関係特徴（占有種類差＋着手可能種類） | 最初に実装 |
| **Stage A 拡張** | 着地点のライン交差（own/opp の live line・open2）をセル種類別に | Stage A が中立超のときのみ |
| **Stage B** | 柱 N-tuple パターンテーブル（`[3][31]`） | Stage A で正シグナル確認時のみ・**別 PR** |

一度に複数段階を実装しない。

---

## 4. Stage A 特徴定義

GEO_NF = 8。Phase 8 の `features()/NF=6` とは**別関数**として追加（既存データ形式・
`learned_config`・`zero_config` に影響させない）。**手番側視点で統一**して保持する
（占有差は先手0視点で求め手番側へ符号反転、着手可能種類は最初から手番側の機会＝
両者を手番側視点に揃えれば 1 回の内積で評価でき、既存 `learned_eval` と同形になる）。

```
geometric_features(board) -> [i64; 8]   # すべて手番側(side-to-move)視点
  [0] occ_corner    = (手番側の CORNER 占有数) - (相手の CORNER 占有数)
  [1] occ_edge      = 〃 EDGE
  [2] occ_face      = 〃 FACE
  [3] occ_interior  = 〃 INTERIOR        # 立方体内部8セル。center(16セル)とは別
  [4] play_corner   = 手番側が今 着手で落とせるセルのうち CORNER の数
  [5] play_edge     = 〃 EDGE
  [6] play_face     = 〃 FACE
  [7] play_interior = 〃 INTERIOR
```

- `[0..3] occ_*`: **診断用**。既存ライン評価との相関が高い見込み → 単独で必ず計測。
- `[4..7] play_*`: **本仮説の最重要部**。手番側のテンポ特徴。
  - 高価値セルへアクセスできる局面を加点できる。
  - ある手を指すと子局面で相手に高価値セルを解放 → 子局面は相手視点で高評価 →
    **negamax の符号反転により、親側では「相手に価値を解放する手」への自然なペナルティ**。
  - **着手履歴を評価に持ち込まない**（盤面のみ）→ TT キーが盤面だけの既存設計と無矛盾。

評価式（重みすべて 0 なら `default_eval` と完全一致）:

```
eval_geometric(board, w)  = Σ_t w[t] * geometric_features(board)[t]     # 手番側視点
candidate_eval(board, w)  = default_eval(board) + eval_geometric(board, w)
```

分離計測のため重みは同時最適化しない: **G1 = occ のみ / G2 = play のみ / G3 = occ+play**。

---

## 5. D4 不変性の根拠

対称性圧縮 TT の前提（評価は D4 不変必須）。本特徴が満たすことの論証:

- **CellType は D4 不変**: D4 は 4×4 盤の二面体対称＝(x,y) の置換で、各座標の「外側性」
  (`∈{0,3}`) を保ち（角→角・辺中→辺中）、z は不変。よって「外側軸数」が保たれセル種類は不変。
- **occ_* は D4 不変**: D4 は柱（と乗る石）を写すが種類を保ち、手番は不変。
- **play_* は D4 不変**: 着手可能な着地セルは高さで決まり、高さは D4 で柱と共に写る。
  着地セルの種類は不変、手番も不変。
- 値は (盤面, 手番) だけに依存 → 同一 D4 軌道で同値 → 対称性 TT と無矛盾。

検証は `test_symmetry.py` / `test_rust_search.py` の D4 不変テストに geo を追加して担保。

---

## 6. EvalConfig / API 拡張（加算的・互換維持）

```rust
pub const GEO_NF: usize = 8;
pub struct EvalConfig {
    // 既存フィールドは不変
    pub geo_enabled: u8,            // 0 = 既定（geo オフ）
    pub geo_weights: [i64; GEO_NF],
}
EvalConfig::default_plus_geometric(weights)  // {geo_enabled:1, geo_weights, ..default_config()}
```

要件:

- `default_config()` は `geo_enabled=0` / `geo_weights=[0;8]`。
- `zero_config()` は常に 0（geo 継承で 0 のまま）→ **詰み探索・solve 不変**。
- `learned_config()` の既存挙動を変えない。
- `cfg_from_tuple`（6 要素タプル）の公開 API は不変（`..default_config()` で吸収）。
- `eval_with`: `geo_enabled!=0` のとき `default(parity)経路の値 + Σ geo_weights·geometric_features`。
  既存 6 タプル経路（geo オフ）は完全不変。

Python 側にも同義の純粋関数（`cell_types` / `geometric_features` / `eval_geometric` /
`eval_default_plus_geometric`）を追加し、Rust と同値を契約テストで保証。

PyO3 API（最小）:

```
cell_types()                                  # CELL_TYPE[64] を返す（テスト用）
geometric_features(b0, b1)                     # [i64; 8]
eval_geometric(b0, b1, weights)                # i64（手番側視点）
play_match_geometric(weights, openings, depth, time_ms)   # 候補=default+geo vs 既定=default
```

`play_match_geometric` は既存 `play_match` 基盤を再利用する（対局ループを重複実装しない）。

---

## 7. テスト計画

**幾何分類**（Commit 1）: セル数 8/24/24/8・各種類のライン所属数 7/4/4/7・3 柱パターン・
D4 変換前後で種類一致（いずれも本書 §2 で実コード検算済み）。

**評価**（Commit 2/3）: geo 重み全 0 で `default_eval` と完全一致・Python==Rust の
`geometric_features` と評価値一致・D4 対称局面で評価一致・決定的・非破壊・終端処理不変。

**探索契約**（Commit 3）: 候補評価でも全幅 negamax と α-β が同値・Python/Rust `search` 一致・
play/undo 後の盤面完全復元・タイムアウトで盤面非破壊・**`solve()` と `zero_config()` の結果不変**。

**Web 回帰**（geo 既定オフのとき）: 既存 WASM API の結果不変・Web 既定手不変・`engine.wasm`
ビルド成功。候補の Web 公開は採用決定後でよい。

テスト追加先（新規ファイルは最小化）: `tests/test_evaluate.py`（純 Python 性質）・
`tests/test_symmetry.py`（D4）・`tests/test_rust_search.py`（Python/Rust 一致・契約。
※ 専用 `test_rust_evaluate.py` は存在しないのでここへ統合）。

---

## 8. 自動計測計画（人間対局なし）

スクリプト `scripts/benchmark_geometry_eval.py`、結果 `docs/benchmarks/geometry_eval.{json,md}`。

- **Stage 0 基準保存**: 既定評価で固定深さ nodes/NPS/completed depth と 50/100/200/300/1000ms・
  序中終盤・多シードを保存。
- **Stage 1 単独特徴スクリーニング**: 各特徴を 1 つずつ追加し既定と対戦（重み候補
  `-8,-4,-2,-1,0,1,2,4,8`）。順序: `play_*` を 1 つずつ → `occ_*` を 1 つずつ → 正シグナルの
  特徴だけ組合せ。小標本（例: 3 seeds × 40 openings × plies 6・先後入替）。**8 次元総当たりはしない**。
- **Stage 2 段階別**: 上位候補を opening plies 4/8/12 で確認（序盤限定か・中盤も効くか・終盤
  ノイズか・高さ分布への過学習）。
- **Stage 3 固定時間**: Web 用途重視で 50/100/200ms（確認 300/1000ms）・各 opening 先後入替。
- **Stage 4 ホールドアウト**: 重み探索に使っていない 5 新規シード × 100 openings・先後入替・
  可能なら 1000 局以上。

---

## 9. 採用基準と結果分類

**強さ**: 主要時間制御 100/200ms で候補勝率 > 0.5・多シードで方向一貫・ホールドアウトで
約 2 標準誤差以上の改善・単一シード勝ちでない・50ms で大幅悪化なし・300/1000ms でも改善
消失しない（または用途限定）。目安 `aggregate winrate ≥ 0.53 かつ主要時間制御に 0.49 未満なし`
（標本数・信頼区間を優先）。

**速度**: 評価 1 回の追加コスト・NPS 低下を記録。Stage A の NPS 低下は原則 10% 以内目標。
固定深さで強くても固定時間で負けるなら不採用。

**正しさ**: 全テスト緑・Rust/Python 一致・D4 不変・決定論・`zero_config` 不変・mate solver
不変・WASM ビルド成功。

**結果分類**（"直感的に正しい/自然" だけで ADOPTED にしない）:

```
ADOPTED      固定時間勝率が明確に向上 → 既定へ採用（別コミット）
CONDITIONAL  特定時間/段階のみ有効 → モード限定で保持
EXPERIMENTAL 中立または標本不足 → 既定オフで保持
REJECTED     固定時間で悪化 → 既定オフ/コード戻し、計測記録だけ残す
```

---

## 10. 実装コミット分割

1. **幾何分類のみ**: `CellType` / `CELL_TYPE[64]` / マスク / 個数・ライン所属・柱パターン・
   D4 不変テスト。**評価関数は未変更**。
2. **Stage A Python 参照**: `geometric_features` / `eval_geometric` / `default+geo` / 重み0同値・
   D4 テスト。
3. **Rust 実装と契約**: Rust 特徴抽出・評価・PyO3 API・Python/Rust 一致・探索契約。
4. **自動 A/B 計測**: 固定シード・先後入替・固定時間・JSON/Markdown 保存（人間対局なし）。
5. **採否記録**: `eval_measurements.md` へ追記・roadmap 状態更新・勝ち越し時のみ別コミットで
   既定採用、中立/悪化なら既定オフのまま。

Stage B（柱 N-tuple, `column_pattern_table[3][31]`, 教師は**勝敗ロジスティック/残差/座標探索**＝
深い探索スコアへの単純回帰を第一選択にしない）は Stage A 計測後、別 PR・別指示で。

---

## 11. 非目標

ユーザー対局／手動ラベル／AlphaZero・GPU・大型 NN／MCTS 全面移行／既存ロードマップ再実装／
Threat Quiescence 再発明／深い探索スコアへの無条件最小二乗回帰／全特徴の巨大グリッドサーチ／
計測前の `default_eval` 変更／Web UI 大規模改修／既存 `center` 特徴の無断意味変更。

---

## 12. 完了報告形式（実装後）

実装内容 / 変更ファイル / 幾何分類テスト / Python·Rust 契約テスト / D4 対称性テスト /
固定深さベンチ / 固定時間自己対局 / NPS への影響 / 多シード結果 / 採否 / 既知の制約 / 次の実験。

> この仮説は人間との対局で検証しない。候補評価と既定評価の自動自己対局・固定時間・多シード・
> 先後入れ替えだけで採否を決める。
