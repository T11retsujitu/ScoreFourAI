//! 探索 (search.py の Rust 移植)。
//!
//! negamax / α-β / 置換表 / 脅威枝刈り / D4対称性 / 反復深化 / PVS / 時間制御。
//! Python と同一アルゴリズム・同一着手順序・同一 TT 意味論・同一 PVS にして
//! (score, best_move) を一致させる (言語横断契約テスト)。

use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use crate::board::Board;
use crate::evaluate::{eval_with, EvalConfig};
use crate::symmetry::{canonical, col_perms, inv_col_perms};

/// 置換表用の決定的ハッシャ。正規化キー(u128)は既に分散が良いので軽量な混合で十分。
///
/// std 既定の RandomState は OS 乱数で種を取るため wasm32-unknown-unknown では使えない
/// (エントロピー源が無い)。固定混合にすることで wasm でも動き、プラットフォーム非依存で
/// 決定的、かつ通常ビルドより高速になる。
#[derive(Default)]
pub(crate) struct KeyHasher(u64);

impl Hasher for KeyHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0 ^ b as u64).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    fn write_u128(&mut self, i: u128) {
        let lo = i as u64;
        let hi = (i >> 64) as u64;
        self.0 = lo.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ hi.wrapping_mul(0xC2B2_AE3D_27D4_EB4F);
    }
}

pub(crate) type Tt = HashMap<u128, TtEntry, BuildHasherDefault<KeyHasher>>;

/// 空の置換表を作る (永続エンジンが保持する共有 TT 用)。
pub fn new_tt() -> Tt {
    Tt::default()
}

pub const WIN: i64 = 1_000_000;
pub const INF: i64 = WIN * 2;
pub const MATE_LO: i64 = WIN - 64 - 1;

const EXACT: u8 = 0;
const LOWER: u8 = 1;
const UPPER: u8 = 2;

// 着手順序スコアの定数 (Python と完全一致)。
const ORD_TT: i64 = 4_000_000_000;
const ORD_K0: i64 = 3_000_000_000;
const ORD_K1: i64 = 2_900_000_000;
const ORD_HIST_MULT: i64 = 16;
const HISTORY_CAP: i64 = 1 << 20;
const MAX_PLY: usize = 66; // killers のインデックス上限 (depth <= 64)

/// 着手順序: 中央寄りの柱を先に。centrality = |2x-3| + |2y-3| (Python の整数化)。
fn centrality(c: usize) -> i32 {
    let x = (c % 4) as i32;
    let y = (c / 4) as i32;
    (2 * x - 3).abs() + (2 * y - 3).abs()
}

fn column_rank() -> &'static [usize; 16] {
    static R: OnceLock<[usize; 16]> = OnceLock::new();
    R.get_or_init(|| {
        let mut order: Vec<usize> = (0..16).collect();
        order.sort_by_key(|&c| centrality(c)); // 安定ソート、同値は昇順 index
        let mut rank = [0usize; 16];
        for (i, &c) in order.iter().enumerate() {
            rank[c] = i;
        }
        rank
    })
}

/// 局面が終端なら手番側視点のスコア。勝敗が付けば手番側は負け。
fn terminal_value(board: &Board) -> Option<i64> {
    if board.winner.is_some() {
        return Some(-(WIN - board.num_moves() as i64));
    }
    if board.is_full() {
        return Some(0);
    }
    None
}

/// 締切超過の標識。
struct Timeout;

/// 置換表エントリ: (depth, value, flag, best_move(正規形の柱) or -1)。
pub(crate) type TtEntry = (u8, i64, u8, i8);

struct Searcher {
    tt: Tt,
    deadline: Option<Instant>,
    nodes: u64,
    qnodes: u64,
    tt_hits: u64,
    tt_cutoffs: u64,
    beta_cutoffs: u64,
    cfg: EvalConfig,
    qdepth: u8,
    killers: Vec<[i32; 2]>,  // killers[depth] = [k0, k1] (柱 or -1)
    history: [[i64; 16]; 2], // history[player][col]
}

impl Searcher {
    fn new(deadline: Option<Instant>, cfg: EvalConfig, qdepth: u8) -> Self {
        Searcher {
            tt: Tt::default(),
            deadline,
            nodes: 0,
            qnodes: 0,
            tt_hits: 0,
            tt_cutoffs: 0,
            beta_cutoffs: 0,
            cfg,
            qdepth,
            killers: vec![[-1, -1]; MAX_PLY],
            history: [[0; 16]; 2],
        }
    }

    /// killer/history を使った着手順序を、スタック配列 ([u8;16], 個数) で返す。
    /// Python _ordered_moves と同一スコア。history が空の初回は中央寄り順に一致。
    /// ヒープ確保を避けるため u16 マスクから固定長配列へ展開してソートする。
    fn ordered_moves_ki(&self, board: &Board, tt_move: i32, depth: u8) -> ([u8; 16], usize) {
        let kd = self.killers[depth as usize];
        let hp = &self.history[board.turn as usize];
        let rank = column_rank();
        let score = |c: u8| -> i64 {
            let ci = c as i32;
            if ci == tt_move {
                return ORD_TT;
            }
            if ci == kd[0] {
                return ORD_K0;
            }
            if ci == kd[1] {
                return ORD_K1;
            }
            hp[c as usize] * ORD_HIST_MULT + (15 - rank[c as usize] as i64)
        };
        let mut buf = [0u8; 16];
        let mut n = 0usize;
        let mut m = board.legal_mask();
        while m != 0 {
            let c = m.trailing_zeros() as u8;
            buf[n] = c;
            n += 1;
            m &= m - 1;
        }
        buf[..n].sort_by_key(|&c| (-score(c), c)); // -score 昇順 = score 降順, 同点は柱昇順
        (buf, n)
    }

    /// beta cutoff を起こした手 col で killer/history を更新する。
    fn update_cutoff(&mut self, depth: u8, player: usize, col: u8) {
        let kd = &mut self.killers[depth as usize];
        if col as i32 != kd[0] {
            kd[1] = kd[0];
            kd[0] = col as i32;
        }
        let c = col as usize;
        self.history[player][c] += (depth as i64) * (depth as i64);
        if self.history[player][c] > HISTORY_CAP {
            for p in 0..2 {
                for cc in 0..16 {
                    self.history[p][cc] >>= 1;
                }
            }
        }
    }

    /// player のダブルリーチ生成手 (Python fork_moves と同一)。
    fn fork_moves(board: &mut Board, player: usize) -> Vec<u8> {
        let opp = player ^ 1;
        let mut res = Vec::new();
        for col in board.legal_moves() {
            board.play(col as usize).unwrap();
            if board.winner.is_none()
                && board.winning_moves(opp).is_empty()
                && board.winning_moves(player).len() >= 2
            {
                res.push(col);
            }
            board.undo();
        }
        res
    }

    /// 脅威の静穏化探索 (Python quiescence と同一・窓非依存・純粋)。
    fn quiescence(&mut self, board: &mut Board, qd: u8) -> i64 {
        self.qnodes += 1;
        if let Some(t) = terminal_value(board) {
            return t;
        }
        let me = board.turn as usize;
        if board.has_winning_move(me) {
            return WIN - (board.num_moves() as i64 + 1);
        }
        let opp_threats = board.winning_moves(me ^ 1);
        if opp_threats.len() >= 2 {
            return -(WIN - (board.num_moves() as i64 + 2));
        }
        if opp_threats.len() == 1 {
            if qd == 0 {
                return eval_with(board, &self.cfg);
            }
            board.play(opp_threats[0] as usize).unwrap();
            let v = -self.quiescence(board, qd - 1);
            board.undo();
            return v;
        }
        let stand_pat = eval_with(board, &self.cfg);
        if qd == 0 {
            return stand_pat;
        }
        let mut best = stand_pat;
        for col in Self::fork_moves(board, me) {
            board.play(col as usize).unwrap();
            let v = -self.quiescence(board, qd - 1);
            board.undo();
            if v > best {
                best = v;
            }
        }
        best
    }

    /// depth==0 の葉評価。qdepth>0 なら脅威静穏化、0 なら静的評価。
    fn leaf(&mut self, board: &mut Board) -> i64 {
        if self.qdepth > 0 {
            self.quiescence(board, self.qdepth)
        } else {
            eval_with(board, &self.cfg)
        }
    }

    fn check(&mut self) -> Result<(), Timeout> {
        self.nodes += 1;
        if let Some(d) = self.deadline {
            if self.nodes & 0x7FF == 0 && Instant::now() >= d {
                return Err(Timeout);
            }
        }
        Ok(())
    }

    fn negamax(
        &mut self,
        board: &mut Board,
        depth: u8,
        mut alpha: i64,
        beta: i64,
    ) -> Result<i64, Timeout> {
        if let Some(t) = terminal_value(board) {
            return Ok(t);
        }
        if depth == 0 {
            return Ok(self.leaf(board));
        }
        self.check()?;

        let alpha_orig = alpha;
        let (key, sym) = canonical(board.bb[0], board.bb[1]);
        let mut tt_move: i32 = -1;
        if let Some(&(e_depth, e_value, e_flag, e_move)) = self.tt.get(&key) {
            self.tt_hits += 1;
            if e_move >= 0 {
                tt_move = inv_col_perms()[sym][e_move as usize] as i32; // 正規形 -> 現局面
            }
            if e_depth >= depth {
                if e_flag == EXACT {
                    self.tt_cutoffs += 1;
                    return Ok(e_value);
                }
                if e_flag == LOWER && e_value >= beta {
                    self.tt_cutoffs += 1;
                    return Ok(e_value);
                }
                if e_flag == UPPER && e_value <= alpha {
                    self.tt_cutoffs += 1;
                    return Ok(e_value);
                }
            }
        }

        let me = board.turn as usize;
        // 自分の即勝ち: 最速勝ちが最善。
        if board.has_winning_move(me) {
            return Ok(WIN - (board.num_moves() as i64 + 1));
        }

        // 相手の即勝ち脅威による強制手 (depth>=2 のときだけ健全)。
        let mut forced: Option<u8> = None;
        if depth >= 2 {
            let tmask = board.winning_mask(me ^ 1);
            let tcount = tmask.count_ones();
            if tcount >= 2 {
                return Ok(-(WIN - (board.num_moves() as i64 + 2)));
            }
            if tcount == 1 {
                forced = Some(tmask.trailing_zeros() as u8); // 最小柱 = winning_moves[0] と一致
            }
        }

        let is_forced = forced.is_some();
        let (moves, nmoves) = match forced {
            Some(c) => ([c; 16], 1),
            None => self.ordered_moves_ki(board, tt_move, depth),
        };

        let mut best = -INF;
        let mut best_move: i32 = -1;
        let mut first = true;
        for &col in &moves[..nmoves] {
            board.play(col as usize).unwrap();
            // PVS: 第1手は全幅、以降はヌルウィンドウ scout、超えたら全幅再探索。
            // undo を必ず通すため ? は undo 後に適用する。
            let result: Result<i64, Timeout> = if first {
                self.negamax(board, depth - 1, -beta, -alpha).map(|s| -s)
            } else {
                match self.negamax(board, depth - 1, -alpha - 1, -alpha) {
                    Err(e) => Err(e),
                    Ok(s) => {
                        let v = -s;
                        if alpha < v && v < beta {
                            self.negamax(board, depth - 1, -beta, -alpha).map(|s2| -s2)
                        } else {
                            Ok(v)
                        }
                    }
                }
            };
            board.undo();
            let value = result?;
            if value > best {
                best = value;
                best_move = col as i32;
            }
            if best > alpha {
                alpha = best;
            }
            if alpha >= beta {
                self.beta_cutoffs += 1;
                if !is_forced {
                    self.update_cutoff(depth, me, col);
                }
                break; // beta カット
            }
            first = false;
        }

        let flag = if best <= alpha_orig {
            UPPER
        } else if best >= beta {
            LOWER
        } else {
            EXACT
        };
        let store_move: i8 = if best_move >= 0 {
            col_perms()[sym][best_move as usize] as i8 // 現局面 -> 正規形
        } else {
            -1
        };
        self.tt.insert(key, (depth, best, flag, store_move));
        Ok(best)
    }

    /// 根を 1 段 PVS 展開し (score, best_move) を返す (フルウィンドウ)。
    fn search_root(&mut self, board: &mut Board, depth: u8) -> Result<(i64, i32), Timeout> {
        let me = board.turn as usize;
        let wins = board.winning_moves(me);
        if !wins.is_empty() {
            return Ok((WIN - (board.num_moves() as i64 + 1), wins[0] as i32));
        }

        let mut alpha = -INF;
        let mut best = -INF;
        let mut best_move: i32 = -1;
        let (key, sym) = canonical(board.bb[0], board.bb[1]);
        let mut tt_move: i32 = -1;
        if let Some(&(_, _, _, e_move)) = self.tt.get(&key) {
            if e_move >= 0 {
                tt_move = inv_col_perms()[sym][e_move as usize] as i32;
            }
        }

        let (moves, nmoves) = self.ordered_moves_ki(board, tt_move, depth);
        let mut first = true;
        for &col in &moves[..nmoves] {
            board.play(col as usize).unwrap();
            let result: Result<i64, Timeout> = if first {
                self.negamax(board, depth - 1, -INF, -alpha).map(|s| -s)
            } else {
                match self.negamax(board, depth - 1, -alpha - 1, -alpha) {
                    Err(e) => Err(e),
                    Ok(s) => {
                        let v = -s;
                        if v > alpha {
                            self.negamax(board, depth - 1, -INF, -alpha).map(|s2| -s2)
                        } else {
                            Ok(v)
                        }
                    }
                }
            };
            board.undo();
            let value = result?;
            if value > best {
                best = value;
                best_move = col as i32;
            }
            if best > alpha {
                alpha = best;
            }
            first = false;
        }

        let store_move: i8 = if best_move >= 0 {
            col_perms()[sym][best_move as usize] as i8
        } else {
            -1
        };
        self.tt.insert(key, (depth, best, EXACT, store_move));
        Ok((best, best_move))
    }
}

/// 全幅ウィンドウの negamax 値 (fresh TT, 時間制御なし, 既定評価)。Python negamax の契約用。
pub fn negamax_value(b0: u64, b1: u64, depth: u8, qdepth: u8) -> i64 {
    negamax_value_cfg(b0, b1, depth, qdepth, EvalConfig::default_config())
}

/// 全幅ウィンドウの negamax 値 (fresh TT, 評価設定 cfg 指定)。任意評価の契約テスト用。
pub fn negamax_value_cfg(b0: u64, b1: u64, depth: u8, qdepth: u8, cfg: EvalConfig) -> i64 {
    let mut board = Board::from_bitboards(b0, b1);
    let mut searcher = Searcher::new(None, cfg, qdepth);
    searcher.negamax(&mut board, depth, -INF, INF).unwrap_or(0) // 時間制御なしなので必ず Ok
}

impl Searcher {
    /// 与えた tt を持つ Searcher を作る (永続/共有 TT 用)。
    fn with_tt(tt: Tt, cfg: EvalConfig, qdepth: u8) -> Self {
        let mut s = Searcher::new(None, cfg, qdepth);
        s.tt = tt;
        s
    }

    /// 反復深化本体 (深さ1 完走 → 時間制御つきで深める)。(score, best_move) を返す。
    fn run_id(
        &mut self,
        board: &mut Board,
        max_depth: u8,
        deadline: Option<Instant>,
    ) -> (i64, i32) {
        let (mut score, mut mv) = self.search_root(board, 1).unwrap_or((0, -1));
        if score.abs() > MATE_LO || max_depth <= 1 {
            return (score, mv);
        }
        self.deadline = deadline;
        let mut depth = 2u8;
        while depth <= max_depth {
            if let Some(d) = deadline {
                if Instant::now() >= d {
                    break;
                }
            }
            match self.search_root(board, depth) {
                Ok((s, m)) => {
                    score = s;
                    mv = m;
                }
                Err(_) => break, // 途中の反復は破棄し直前の結果を返す
            }
            if score.abs() > MATE_LO {
                break;
            }
            depth += 1;
        }
        (score, mv)
    }
}

/// 反復深化 + 時間制御 + 評価設定 cfg + 静穏化 qdepth で (score, best_move) を返す (fresh TT)。
pub fn search_with_cfg(
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    cfg: EvalConfig,
    qdepth: u8,
) -> (i64, i32) {
    let mut board = Board::from_bitboards(b0, b1);
    let deadline = time_limit.map(|s| Instant::now() + Duration::from_secs_f64(s));
    let mut searcher = Searcher::new(None, cfg, qdepth);
    searcher.run_id(&mut board, max_depth, deadline)
}

/// 共有 TT を使い回して反復深化探索する (永続エンジン用)。tt は探索後の状態に更新される。
///
/// 局面間で TT (= transposition の計算結果) を再利用するため、合流する部分木の読み直しを
/// 省ける = 定石生成が速くなる。**注意**: TT は要求 depth 以上のエントリを再利用するので、
/// 近傍ノードが先に深く読んだ局面は「より深い値」で返りうる。値は妥当 (>= 公称 depth) だが
/// 探索順に依存するため、共有 TT を使うと結果は fresh TT と必ずしもビット一致しない。
pub fn search_persistent(
    tt: &mut Tt,
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    cfg: EvalConfig,
    qdepth: u8,
) -> (i64, i32) {
    let mut board = Board::from_bitboards(b0, b1);
    let deadline = time_limit.map(|s| Instant::now() + Duration::from_secs_f64(s));
    let mut searcher = Searcher::with_tt(std::mem::take(tt), cfg, qdepth);
    let result = searcher.run_id(&mut board, max_depth, deadline);
    *tt = std::mem::take(&mut searcher.tt); // 蓄積した TT を呼び出し側へ戻す
    result
}

/// 探索の統計付き結果 (analyze の返り値)。qnodes は Phase2 (quiescence) 用の予約。
pub struct SearchResult {
    pub score: i64,
    pub best_move: i32,
    pub completed_depth: u8,
    pub nodes: u64,
    pub qnodes: u64,
    pub tt_hits: u64,
    pub tt_cutoffs: u64,
    pub beta_cutoffs: u64,
    pub elapsed_ms: u64,
    pub pv: Vec<u8>,
}

/// 置換表をルートから最善手で辿り PV (合法手列) を抽出する。
fn extract_pv(tt: &Tt, b0: u64, b1: u64, max_len: usize) -> Vec<u8> {
    let mut pv = Vec::new();
    let mut board = Board::from_bitboards(b0, b1);
    for _ in 0..max_len {
        if board.is_terminal() {
            break;
        }
        let (key, sym) = canonical(board.bb[0], board.bb[1]);
        let entry = match tt.get(&key) {
            Some(e) => *e,
            None => break,
        };
        let cmove = entry.3;
        if cmove < 0 {
            break;
        }
        let mv = inv_col_perms()[sym][cmove as usize] as u8;
        if board.heights[mv as usize] >= 4 {
            break; // 念のため非合法は止める
        }
        pv.push(mv);
        board.play(mv as usize).unwrap();
    }
    pv
}

/// 反復深化 + 時間制御で探索し、統計と PV 付きの SearchResult を返す。
///
/// (score, best_move) は同条件の search_with_cfg と一致する (加算的; 値は不変)。
pub fn analyze_with_cfg(
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    cfg: EvalConfig,
    qdepth: u8,
) -> SearchResult {
    let start = Instant::now();
    let mut board = Board::from_bitboards(b0, b1);
    let deadline = time_limit.map(|s| start + Duration::from_secs_f64(s));

    let mut searcher = Searcher::new(None, cfg, qdepth);
    let (mut score, mut mv) = searcher.search_root(&mut board, 1).unwrap_or((0, -1));
    let mut completed: u8 = 1;

    if !(score.abs() > MATE_LO || max_depth <= 1) {
        searcher.deadline = deadline;
        let mut depth = 2u8;
        while depth <= max_depth {
            if let Some(d) = deadline {
                if Instant::now() >= d {
                    break;
                }
            }
            match searcher.search_root(&mut board, depth) {
                Ok((s, m)) => {
                    score = s;
                    mv = m;
                    completed = depth;
                }
                Err(_) => break,
            }
            if score.abs() > MATE_LO {
                break;
            }
            depth += 1;
        }
    }

    let mut pv = extract_pv(&searcher.tt, b0, b1, 32);
    if pv.is_empty() && mv >= 0 {
        pv.push(mv as u8); // 即勝ち短絡など TT 未保存のケース
    }
    SearchResult {
        score,
        best_move: mv,
        completed_depth: completed,
        nodes: searcher.nodes,
        qnodes: searcher.qnodes,
        tt_hits: searcher.tt_hits,
        tt_cutoffs: searcher.tt_cutoffs,
        beta_cutoffs: searcher.beta_cutoffs,
        elapsed_ms: start.elapsed().as_millis() as u64,
        pv,
    }
}

/// 既定評価・静穏化なしの反復深化 + 時間制御 (wasm/定石用)。
pub fn search_position(b0: u64, b1: u64, max_depth: u8, time_limit: Option<f64>) -> (i64, i32) {
    search_with_cfg(
        b0,
        b1,
        max_depth,
        time_limit,
        EvalConfig::default_config(),
        0,
    )
}

// --- 詰み探索 (mate solver) — Phase 7 の Rust 移植 ------------------------
// solve.py と同一アルゴリズム: 零評価 (D4 不変) の反復深化 negamax は地平線内の終端
// だけを価値として伝播するので、最善値 = 最短強制勝ち / 最長粘りの負け になる。
// Python solve と (status, plies, best_move, pv) を一致させる (言語横断契約テスト)。

/// 詰み探索のステータス。手番側視点。
pub const MATE_UNKNOWN: u8 = 0;
pub const MATE_WIN: u8 = 1;
pub const MATE_LOSS: u8 = 2;
pub const MATE_DRAW: u8 = 3;

/// 詰み探索の結果 (手番側視点)。plies は win/loss のときのみ >=0、それ以外 -1。
pub struct MateResult {
    pub status: u8,
    pub plies: i32,
    pub best_move: i32,
    pub pv: Vec<u8>,
}

/// 零評価の反復深化探索で (score, best_move) を返す薄いラッパ (solve.py の _solve_value)。
fn solve_value(b0: u64, b1: u64, max_plies: u8) -> (i64, i32) {
    search_with_cfg(b0, b1, max_plies, None, EvalConfig::zero_config(), 0)
}

/// 強制勝ち/負けの主手順を双方最善で復元する (solve.py の _principal_variation)。
/// 各 ply で零評価探索の最善手を打ち、終端に届くまで辿る。勝ち側は最短、負け側は最長。
fn solve_pv(b0: u64, b1: u64, max_plies: u8) -> Vec<u8> {
    let mut line = Vec::new();
    let mut board = Board::from_bitboards(b0, b1);
    let mut remaining = max_plies;
    while !board.is_terminal() && remaining > 0 {
        let (score, mv) = solve_value(board.bb[0], board.bb[1], remaining);
        if score.abs() <= MATE_LO {
            break; // この先は強制決着でない (勝ち手順では起きない)
        }
        if mv < 0 || board.heights[mv as usize] >= 4 {
            break;
        }
        board.play(mv as usize).unwrap();
        line.push(mv as u8);
        remaining -= 1;
    }
    line
}

/// 局面 (b0,b1) の詰み探索を行い MateResult を返す (手番側視点・決定的)。
/// solve.py の solve と同義 (零評価反復深化で強制勝ち/負けの最短/最長手数と PV を求める)。
pub fn solve(b0: u64, b1: u64, max_plies: u8) -> MateResult {
    let board = Board::from_bitboards(b0, b1);
    if board.winner.is_some() {
        // 直前の着手で勝負あり。手番側は受ける手すら無く負け。
        return MateResult {
            status: MATE_LOSS,
            plies: 0,
            best_move: -1,
            pv: Vec::new(),
        };
    }
    if board.is_full() {
        return MateResult {
            status: MATE_DRAW,
            plies: -1,
            best_move: -1,
            pv: Vec::new(),
        };
    }
    let num_moves = board.num_moves() as i64;
    let (score, mv) = solve_value(b0, b1, max_plies);
    if score > MATE_LO {
        return MateResult {
            status: MATE_WIN,
            plies: ((WIN - score) - num_moves) as i32,
            best_move: mv,
            pv: solve_pv(b0, b1, max_plies),
        };
    }
    if score < -MATE_LO {
        return MateResult {
            status: MATE_LOSS,
            plies: ((WIN + score) - num_moves) as i32,
            best_move: mv,
            pv: solve_pv(b0, b1, max_plies),
        };
    }
    // 決着なし。地平線が残り全マスを覆っていれば引分確定、そうでなければ未確定。
    let status = if max_plies as i64 >= 64 - num_moves {
        MATE_DRAW
    } else {
        MATE_UNKNOWN
    };
    MateResult {
        status,
        plies: -1,
        best_move: mv,
        pv: Vec::new(),
    }
}

/// 対戦相手の仕様: 評価設定と静穏化深さ。
type Spec = (EvalConfig, u8);

/// opening から打ち継ぎ、先手=spec0 / 後手=spec1 で対局し勝者を返す。
/// time_ms>0 なら固定時間 (max_depth=64)、0 なら固定 depth。
fn play_game(opening: &[u8], spec0: Spec, spec1: Spec, depth: u8, time_ms: u32) -> Option<u8> {
    let mut board = Board::new();
    for &c in opening {
        board.play(c as usize).unwrap();
    }
    let (tl, md) = if time_ms > 0 {
        (Some(time_ms as f64 / 1000.0), 64u8)
    } else {
        (None, depth)
    };
    while !board.is_terminal() {
        let (cfg, qd) = if board.turn == 0 { spec0 } else { spec1 };
        // 各手で fresh TT 探索 (Python ハーネスと同じ意味論)。
        let (_, mv) = search_with_cfg(board.bb[0], board.bb[1], md, tl, cfg, qd);
        let col = if mv >= 0 {
            mv as usize
        } else {
            board.legal_moves()[0] as usize
        };
        board.play(col).unwrap();
    }
    board.winner
}

/// 仕様 A/B を openings で総当たり対戦させ (a_wins, b_wins, draws) を返す。
///
/// 各 opening を先後入れ替えて 2 局打ち、先手有利を相殺。time_ms>0 で固定時間対局。
#[allow(clippy::too_many_arguments)]
pub fn play_match(
    cfg_a: EvalConfig,
    qdepth_a: u8,
    cfg_b: EvalConfig,
    qdepth_b: u8,
    openings: &[Vec<u8>],
    depth: u8,
    time_ms: u32,
) -> (u32, u32, u32) {
    let spec_a = (cfg_a, qdepth_a);
    let spec_b = (cfg_b, qdepth_b);
    let (mut aw, mut bw, mut dr) = (0u32, 0u32, 0u32);
    for opening in openings {
        match play_game(opening, spec_a, spec_b, depth, time_ms) {
            Some(0) => aw += 1,
            Some(1) => bw += 1,
            _ => dr += 1,
        }
        match play_game(opening, spec_b, spec_a, depth, time_ms) {
            Some(0) => bw += 1,
            Some(1) => aw += 1,
            _ => dr += 1,
        }
    }
    (aw, bw, dr)
}
