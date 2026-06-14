# 強化ロードマップ

CPU のみで高速・強力に動く Score Four 解析/対戦エンジンへ向けた強化計画と進捗。
方針の全体像は [`design.md`](design.md)、規約・原則は [`../CLAUDE.md`](../CLAUDE.md)。

> 重視するもの: **短時間制御での棋力 / 低メモリ / 決定論 / WASM 移植性 /
> サーバ GPU 不要 / 解析の説明可能性 / 定石・詰みの事前計算資産化**。
> AlphaZero・大型 NN・GPU 学習は現時点で非目標（[`../CLAUDE.md`](../CLAUDE.md) 参照）。

## 状態一覧

凡例: ✅ 完了 / ◑ 一部 / ⏳ 予定 / 🧪 実装済みだが計測で棚上げ

| Phase | 内容 | 状態 | 参照 |
|------:|------|:----:|------|
| 1 | 計測基盤 (analyze + 統計 + PV, 固定時間ベンチ) | ✅ | `search.analyze` / `scripts/benchmark.py` / `benchmarks/baseline.json` |
| 2 | Threat Quiescence + ダブルリーチ直接検出 | 🧪 | [`benchmarks/quiescence.md`](benchmarks/quiescence.md)（計測=中立→既定オフ） |
| 3 | 着手順序強化 (killer / history) | ⏳ | 下記 |
| 4 | ホットループ最適化 (u16 mask / 差分評価 / D4 高速化) | ⏳ | 下記 |
| 5 | TT 改善 (固定長 / 窓縮小 / aspiration) | ⏳ | 下記 |
| 6 | 定石改善 (選択的 Book / リッチエントリ / shared TT) | ⏳ | 下記 |
| 7 | 詰み探索・問題生成 (df-PN / Threat-Space) | ⏳ | 下記 |
| 8 | 軽量学習評価 (深い αβ を教師) | ⏳ | 下記 |
| 9 | Web アプリ対応 (crate 分離 / WASM API / 難易度) | ◑ | `web/` / `rust/` |

---

## Phase 1 — 計測基盤 ✅

`analyze()` が探索統計 (nodes / qnodes / tt_hits / tt_cutoffs / beta_cutoffs /
elapsed_ms) と PV を返す。`scripts/benchmark.py` が分類済み局面 (序盤/中盤/終盤/即勝ち/
強制受け/ダブルリーチ/強制手順/静穏/地平線) を {50,100,300,1000}ms で計測し JSON 保存。
既存契約は不変（加算的）。ベースラインは `docs/benchmarks/baseline.json`。

## Phase 2 — Threat Quiescence 🧪（実装済み・既定オフ）

depth==0 の地平線で強制手（即勝ち/唯一の受け/ダブル即勝ち負け/ダブルリーチ生成）だけを
`qdepth` まで延長。**窓非依存の純粋な葉評価器**にして全幅・言語横断契約を維持
（Rust==Python を qdepth∈{0,4,8} で確認）。**固定時間の自己対戦では中立**（50ms 0.507 /
100ms 0.467）だったため**既定 qdepth=0（オフ）**。実装は解析用途・長い持ち時間での再評価
資産として保持。詳細 [`benchmarks/quiescence.md`](benchmarks/quiescence.md)。

## Phase 3 — 着手順序強化 ⏳

現状は「TT手 → 中央寄り」。これに killer / history を加える。

- 推奨順: TT手 → 即勝ち → 唯一の受け → ダブルリーチ生成 → 相手フォーク防止 → killer →
  history → 中央寄り。16 列なので固定長スコア配列で軽量に。
- killer: 各 ply で beta cutoff を起こした非戦術手を最大2件保存。
- history: cutoff 時に `history[player][col] += depth*depth`、上限で減衰。
- **受け入れ**: minimax 値不変・契約維持・同一深さでノード減・同一時間で完了深さ増を、
  序盤/中盤/終盤に分けて中央値で確認（単一局面・単一シードで判断しない）。

## Phase 4 — ホットループ最適化 ⏳

1ノード当たりコストの削減。**必ずベンチで効果を確認し、複雑性に見合わなければ不採用**。

- **u16 move mask**: 合法手・即勝ち手を `u16` で表現（`count_ones`/`trailing_zeros`）。
  ヒープ確保削減。既存 `Vec<u8>` API は互換のため残す。
- **差分評価**: 葉での 76 ライン走査を、着手で変化するラインのみの増分更新へ。
  パリティ含め既存評価と完全一致を契約テストで担保。
- **D4 正規形の高速化**: 8 対称ビットボードを盤に持ち play/undo で差分更新する案。
  盤コピーが多い場合は逆効果になりうるので NPS・メモリで判断。

## Phase 5 — Transposition Table 改善 ⏳

現状 `HashMap<u128, TtEntry>`（決定的ハッシャ）。Web/WASM 向けに予測可能なメモリへ。

- **固定長/クラスタ TT**: `key_lock + value + depth + flag + best_move + generation`。
  プロファイル: browser 16/32/64MB, server 128MB+。置換は 深さ優先→世代→浅い→EXACT 優先。
- **TT 境界で窓縮小**: depth 十分時に EXACT は return、LOWER は alpha↑、UPPER は beta↓
  （fail-soft 維持）。
- **Aspiration Window**: 前回スコア中心の狭窓（delta=16、外れたら倍々再探索、MATE 近傍は
  フルウィンドウ）。

## Phase 6 — Opening Book 改善 ⏳

全列挙は ply 増で爆発。**選択的 Book Tree** へ（AI 手番=最善+準最善+上位数手、相手手番=
モード選択 exhaustive/principal/robust/human）。エントリを richにする（move/score/depth/
bound/pv/nodes/engine_version/generated_at、形式バージョン付き）。生成中は **Engine を
使い回し TT を共有**（`analyze_batch` / `clear_tt` / `new_generation`）。

## Phase 7 — 詰み探索・問題生成 ⏳

通常 αβ とは別の**解析モード**として df-PN / Threat-Space Search を追加し、強制勝ちの
証明・最短手数・3/5/7 手詰めを扱う。詰み問題の自動生成（強制勝ち・指定手数・初手一意・
全応手で勝ち継続・D4 重複除去・難易度指標）。

## Phase 8 — 軽量学習評価 ⏳

AlphaZero は使わない。**深い αβ を教師**に、CPU で高速推論できる小モデル（線形/ロジ/小
GBDT/量子化 MLP）。特徴量は ライン占有・open2/3・高さ別脅威・即勝ち手数・フォーク生成可
数・中央支配 等。**採用条件**: 100/300/1000ms 自己対戦で勝ち越し・多シード再現・D4 不変・
WASM 実行可・小サイズ・浮動小数の非決定性回避。

## Phase 9 — Web アプリ対応 ◑

- ◑ 済: エンジンの WASM 化（素の C-ABI）、Web Worker 実行、3D 対局 UI、難易度=思考時間。
- ⏳ 予定: `score-four-core`（PyO3 非依存）/`-python`/`-wasm` への crate 分離、WASM API の
  拡充（analyze/multiPV/solve/cancel/loadBook）、難易度プロファイルの整備。

---

## 進め方の順序

最優先は **Phase 3（着手順序強化）**。minimax 値を変えず同一時間で深さを上げる純粋な
高速化で、契約を壊さず効果を測りやすい。次いで Phase 4/5（ノードコスト削減・TT 改善・
aspiration）。その後 Phase 6/7（定石・詰み）、Phase 8（学習評価）、Phase 9 残り。

各 Phase は独立コミットで進め、**変更前後で nodes/NPS/深さ/勝率を記録**し、**改善が
確認できない最適化は採用しない**（[`../CLAUDE.md`](../CLAUDE.md) の原則）。

## 関連ドキュメント

- [`design.md`](design.md) — 方針・アーキテクチャの全体像
- [`../CLAUDE.md`](../CLAUDE.md) — 規約・実装原則・非目標
- [`eval_measurements.md`](eval_measurements.md) — 評価関数の計測ログ
- [`benchmarks/`](benchmarks/) — 固定時間ベンチと Phase 別計測
