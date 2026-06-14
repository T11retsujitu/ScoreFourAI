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
4. ✅ **Rust 高速化**（任意）：コア＋探索を移植、Python と同値を契約テストで保証（約50〜60倍）
5. ⏳ **定石**：根から深く読ませ最善手順（PV）を保存 → 自動生成（次の一歩）
6. （任意）AlphaZero（α-β が頭打ちになった後 or 学習目的のときのみ）

## プロジェクト構成

```
score-four-ai/
├── README.md
├── CLAUDE.md            # Claude Code 用のプロジェクト規約・文脈
├── pyproject.toml
├── docs/
│   ├── rules.md             # ゲームのルール
│   ├── design.md            # 設計メモ（方針の全体像）
│   └── eval_measurements.md # 評価関数の自己対戦計測ログ
├── src/score_four/
│   ├── board.py         # ビットボード／着手生成／勝利判定／winning_moves
│   ├── lines.py         # 76 ラインの生成
│   ├── symmetry.py      # D4 対称性（8 重）正規化
│   ├── evaluate.py      # 評価関数（line_potential / threat_eval / parity_eval / default_eval）
│   ├── search.py        # α-β＋TT＋脅威枝刈り＋対称性＋反復深化＋PVS＋時間制御
│   └── selfplay.py      # 自己対戦の計測ハーネス
├── rust/                # 高速版（PyO3 拡張 score_four_rs）
│   ├── Cargo.toml / pyproject.toml   # maturin ビルド設定
│   └── src/{lib,board,lines,symmetry,evaluate,search}.rs
└── tests/               # 参照実装・契約テスト（言語横断・D4不変性含む）
```

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
```

## 開発の前提（非交渉）

**コア（着手生成・勝利判定）のバグは下流（探索・定石）を静かに全部汚染する。**
契約テストでコアを固めてから探索へ進む「**センサー先行**」を徹底する。

## ステータス

検証済みコア（lines/board）＋ 探索一式（α-β・TT・脅威枝刈り・D4対称性・反復深化＋PVS・
時間制御）＋ 計測駆動の評価（多シード自己対戦・トーナメントでパリティ ALL/-8 を採用）まで
実装済み。Rust 移植はコア＋探索＋評価を完了し、Python 探索と同値を言語横断契約テストで保証
（探索は Python 比 約50〜60倍、評価のパラメータ化と高速トーナメントも実装）。**次は定石生成。**

## 参考

- qweral 氏の立体四目並べシリーズ（戦略・機械学習・最強 AI・AlphaZero）: https://note.com/qweral
