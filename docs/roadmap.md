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
| 3 | 着手順序強化 (killer / history) | ✅ | 下記（ノード −37〜50% / 同一時間で深さ +6〜10） |
| 4 | ホットループ最適化 (u16 mask ✅ / 差分評価 / D4 高速化) | ◑ | 下記（u16 mask: NPS +12〜15%） |
| 5 | TT 改善 (固定長 / 窓縮小 / aspiration) | ◑ | 下記（aspiration: 計測=悪化→不採用） |
| 6 | 定石改善 (選択的 Book / リッチエントリ / shared TT) | ⏳ | 下記 |
| 7 | 詰み探索・問題生成 (mate solver / 問題自動生成) | ◑ | `solve.py` / `problems.py` / `scripts/generate_problems.py` |
| 8 | 軽量学習評価 (深い αβ を教師) | 🧪 | 下記（計測=悪化→不採用） |
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

## Phase 3 — 着手順序強化 ✅

「TT手 → 中央寄り」に killer / history を追加。Python・Rust で**同一スコア式**にして
言語横断の (score, best_move) 一致を維持（90/90）。即勝ち/強制受け/ダブルリーチは
既存の脅威枝刈りが順序前に処理するため、ここでは TT手 → killer → history → 中央寄り の
スコア順とした（history が空の初回反復は従来の中央寄り順に一致＝無害）。

- killer: 各 depth で beta cutoff を起こした手を最大2件保存（重複登録なし）。
- history: cutoff 時に `history[player][col] += depth*depth`、CAP 超で全体半減。
- スコア定数は Python/Rust 共通: TT=4e9 > killer0=3e9 > killer1=2.9e9 > `history*16 + 中央`。

**結果（受け入れ §16 を満たす）**: minimax 値不変（`search` 値=全幅 negamax 値）・契約維持
（rs==py 90/90）・**同一深さでノード −37〜50%**（depth8/9/10）・**同一時間で完了深さ合計
+6〜+10**（50/100/300/1000ms）。序盤/中盤/終盤で確認、棚上げ無しで採用（既定オン）。

## Phase 4 — ホットループ最適化 ◑

1ノード当たりコストの削減。**必ずベンチで効果を確認し、複雑性に見合わなければ不採用**。

- ✅ **u16 move mask**: `Board::legal_mask`/`winning_mask`（`count_ones`/`trailing_zeros`）を
  追加し、探索ホットパスの `Vec` 確保をスタック配列 `[u8;16]` + マスクへ置換（Rust 内部のみ・
  結果不変）。**NPS +12〜15%**（depth9/10）、ノード数・契約は不変（rs==py）。既存 `Vec<u8>`
  API は互換のため残す。
- **差分評価**: 葉での 76 ライン走査を、着手で変化するラインのみの増分更新へ。
  パリティ含め既存評価と完全一致を契約テストで担保。
- **D4 正規形の高速化**: 8 対称ビットボードを盤に持ち play/undo で差分更新する案。
  盤コピーが多い場合は逆効果になりうるので NPS・メモリで判断。

## Phase 5 — Transposition Table 改善 ◑

現状 `HashMap<u128, TtEntry>`（決定的ハッシャ）。Web/WASM 向けに予測可能なメモリへ。

- 🧪 **Aspiration Window**（計測=悪化につき不採用）: 前回スコア中心の狭窓（delta=16〜1024、
  外れたら片側全開で再探索）を Python+Rust に実装し契約は維持（rs==py 84/84）したが、
  **同一深さでノード +24〜36%**（depth9/10/11）と悪化したため**採用せず（既定オフ＝未実装に
  戻した）**。本エンジンの評価は粗く反復間でスコアが ±delta 以上に揺れるため、狭窓が頻繁に
  外れ再探索コストが勝った。より滑らかな評価（Phase 8 学習評価）が入れば再評価の余地。
- ⏳ **固定長/クラスタ TT**: `key_lock + value + depth + flag + best_move + generation`。
  プロファイル: browser 16/32/64MB, server 128MB+。置換は 深さ優先→世代→浅い→EXACT 優先。
  **注意**: 容量制限で eviction が入ると Python 参照(無制限 dict)と best_move がずれ契約に
  影響する。Python 側も同一容量・同一 eviction にするか、契約の見直しが必要。
- ⏳ **TT 境界で窓縮小**: depth 十分時に EXACT は return、LOWER は alpha↑、UPPER は beta↓
  （fail-soft 維持）。best_move のタイ挙動が変わるため Python+Rust 同時実装で契約維持。

## Phase 6 — Opening Book 改善 ⏳

全列挙は ply 増で爆発。**選択的 Book Tree** へ（AI 手番=最善+準最善+上位数手、相手手番=
モード選択 exhaustive/principal/robust/human）。エントリを richにする（move/score/depth/
bound/pv/nodes/engine_version/generated_at、形式バージョン付き）。生成中は **Engine を
使い回し TT を共有**（`analyze_batch` / `clear_tt` / `new_generation`）。

## Phase 7 — 詰み探索・問題生成 ◑

通常 αβ とは別の**解析モード**として詰み探索を追加し、強制勝ちの証明・最短手数・
3/5/7 手詰めを扱う。詰み問題の自動生成（強制勝ち・指定手数・初手一意・全応手で勝ち
継続・D4 重複除去・難易度指標）。

- ◑ 済（`solve.py`）: **零評価 (D4 不変) を葉に挿した negamax** を詰み探索モードとして
  実装。零評価では地平線内の終端 (勝ち/負け/引分) だけが価値として伝播し、終端スコアの
  「速い勝ち=高／遅い負け=高」により **最善値＝最短強制勝ち／最長粘りの負け** になる。
  反復深化で最初に詰みを読み切った深さ＝最短詰み手数。`solve()` が status (win/loss/draw/
  unknown)・最短手数・詰み手順 (PV) を返す。既存の脅威ベース強制手枝刈りが探索木を詰みへ
  大きく絞る（実質的な Threat-Space 縮約）。**全幅 negamax＋零評価を参照に詰み手数を契約
  検証**（`test_solve.py`）。零評価 negamax は `test_search.py` で `negamax_full` と全 depth
  同値が固定済み。
- ◑ 済（`problems.py` / `scripts/generate_problems.py`）: ランダムプレイアウトで非終端局面を
  サンプリングし、**初手一意の強制勝ち（指定手数）**を収集。D4 正規化キーで重複除去、難易度
  指標（詰み手数×100＋おとり数）を付与。`verify_problem` が独立再探索で「初手一意・全応手で
  勝ち継続」を再検証。保存/読込 (`save_problems`/`load_problems`)。
- ◑ 済（Rust 移植 + WASM 公開）: 詰み探索を Rust へ移植（`search::solve`、零評価=
  `EvalConfig::zero_config()` の反復深化）。Python `solve.solve` と (status, plies, best_move,
  pv) が完全一致することを言語横断契約テスト（`test_rust_solve.py`）で固定。WASM C-ABI に
  `sf_solve` ＋ getter（status/plies/move/pv）を公開し、Web アプリの「詰み探索」ボタンで
  強制詰み（最短手数・詰み手順）を読み切って盤上に表示（Phase 9）。
- ⏳ 予定: **df-PN（depth-first proof-number）への置換**で深い戦術詰みを高速化（計測で効果を
  確認してから採用）。

## Phase 8 — 軽量学習評価 🧪（実装済み・計測で悪化につき不採用）

AlphaZero は使わない。**深い αβ を教師**に、CPU で高速推論できる小モデル（まず線形）。
推論側は **整数のみ** の D4 不変・決定的な実装（`evaluate.features` の 6 次元
`[open1,open2,open3,parity,reach3,center]` と `learned_eval`、Rust 同値を契約テストで保証）。
学習側は深さ8探索を教師に最小二乗フィット→整数量子化（浮動小数はオフライン学習のみ;
`learn.py` / `scripts/train_eval.py`）。`[1,5,25,-8,0,0]` が既定 `default_eval` と完全一致
する設計（学習評価は手書き評価の上位互換）。

**結果（受け入れ条件を満たさず不採用）**: 教師スコアへの当てはまりは学習 **R²=0.78** >
パリティ **R²=0.55** と良いのに、固定時間自己対戦では **学習 winrate 0.22〜0.32**
（50/100/200ms・3シード・各120局）と**全条件で明確に負け越し**。典型的な「fit ≠ strength」。
回帰は平均二乗誤差を最小化するが対局の強さとは別目的で、とくに **parity 符号が +5 と反転**
（既定の勝つように調整した -8 と逆）したのが効いた。詳細は
[`eval_measurements.md`](eval_measurements.md) 仮説5。**既定はパリティのまま**、実装は
特徴量・整数線形評価・量子化・教師ラベリング・A/B ハーネスごと**資産として保持**。
次の候補: 教師を**対局の勝敗**にしてロジスティック回帰（目的を「勝ち」に揃える）、または
parity を固定して残差のみ学習。いずれも計測で勝ち越して初めて採用。

## Phase 9 — Web アプリ対応 ◑

- ◑ 済: エンジンの WASM 化（素の C-ABI）、Web Worker 実行、3D 対局 UI、難易度=思考時間。
  **詰み探索（`sf_solve`）を WASM API に公開**し、Web の「詰み探索」ボタンで強制詰みの
  最短手数・詰み手順を表示（盤上に PV をハイライト）。
- ⏳ 予定: `score-four-core`（PyO3 非依存）/`-python`/`-wasm` への crate 分離、WASM API の
  さらなる拡充（analyze/multiPV/cancel/loadBook）、難易度プロファイルの整備。

---

## 進め方の順序

Phase 3（着手順序強化）・Phase 7（詰み探索, ◑）・Phase 8（学習評価, 計測で不採用）まで進行。
残るは **Phase 4/5**（差分評価、TT 固定長・窓縮小）、Phase 6（定石改善）、Phase 7 残り（df-PN /
Rust 化）、Phase 9 残り。いずれも「変更前にベンチ保存→1変更ごと計測→改善が無ければ不採用」で
進める。Phase 8 の次の派生（勝敗教師のロジスティック学習）も同じ規律で測ってから採否を決める。

各 Phase は独立コミットで進め、**変更前後で nodes/NPS/深さ/勝率を記録**し、**改善が
確認できない最適化は採用しない**（[`../CLAUDE.md`](../CLAUDE.md) の原則）。

## 関連ドキュメント

- [`design.md`](design.md) — 方針・アーキテクチャの全体像
- [`../CLAUDE.md`](../CLAUDE.md) — 規約・実装原則・非目標
- [`eval_measurements.md`](eval_measurements.md) — 評価関数の計測ログ
- [`benchmarks/`](benchmarks/) — 固定時間ベンチと Phase 別計測
