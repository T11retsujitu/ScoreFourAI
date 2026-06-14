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
struct KeyHasher(u64);

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

type Tt = HashMap<u128, TtEntry, BuildHasherDefault<KeyHasher>>;

pub const WIN: i64 = 1_000_000;
pub const INF: i64 = WIN * 2;
pub const MATE_LO: i64 = WIN - 64 - 1;

const EXACT: u8 = 0;
const LOWER: u8 = 1;
const UPPER: u8 = 2;

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

/// 着手順: 置換表の手を先頭、残りは中央寄り順。
fn ordered_moves(board: &Board, tt_move: i32) -> Vec<u8> {
    let rank = column_rank();
    let mut moves = board.legal_moves();
    moves.sort_by_key(|&c| rank[c as usize]);
    if tt_move >= 0 {
        if let Some(pos) = moves.iter().position(|&c| c as i32 == tt_move) {
            let c = moves.remove(pos);
            moves.insert(0, c);
        }
    }
    moves
}

/// 締切超過の標識。
struct Timeout;

/// 置換表エントリ: (depth, value, flag, best_move(正規形の柱) or -1)。
type TtEntry = (u8, i64, u8, i8);

struct Searcher {
    tt: Tt,
    deadline: Option<Instant>,
    nodes: u64,
    tt_hits: u64,
    tt_cutoffs: u64,
    beta_cutoffs: u64,
    cfg: EvalConfig,
}

impl Searcher {
    fn new(deadline: Option<Instant>, cfg: EvalConfig) -> Self {
        Searcher {
            tt: Tt::default(),
            deadline,
            nodes: 0,
            tt_hits: 0,
            tt_cutoffs: 0,
            beta_cutoffs: 0,
            cfg,
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
            return Ok(eval_with(board, &self.cfg));
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
            let threats = board.winning_moves(me ^ 1);
            if threats.len() >= 2 {
                return Ok(-(WIN - (board.num_moves() as i64 + 2)));
            }
            if threats.len() == 1 {
                forced = Some(threats[0]);
            }
        }

        let moves: Vec<u8> = match forced {
            Some(c) => vec![c],
            None => ordered_moves(board, tt_move),
        };

        let mut best = -INF;
        let mut best_move: i32 = -1;
        let mut first = true;
        for col in moves {
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

        let mut first = true;
        for col in ordered_moves(board, tt_move) {
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
pub fn negamax_value(b0: u64, b1: u64, depth: u8) -> i64 {
    let mut board = Board::from_bitboards(b0, b1);
    let mut searcher = Searcher::new(None, EvalConfig::default_config());
    searcher.negamax(&mut board, depth, -INF, INF).unwrap_or(0) // 時間制御なしなので必ず Ok
}

/// 反復深化 + 時間制御 + 評価設定 cfg で (score, best_move) を返す。非終端局面のみ。
pub fn search_with_cfg(
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    cfg: EvalConfig,
) -> (i64, i32) {
    let mut board = Board::from_bitboards(b0, b1);
    let deadline = time_limit.map(|s| Instant::now() + Duration::from_secs_f64(s));

    // 深さ1 は無条件に完走 (最低限の手を保証)。
    let mut searcher = Searcher::new(None, cfg);
    let (mut score, mut mv) = searcher.search_root(&mut board, 1).unwrap_or((0, -1));
    if score.abs() > MATE_LO || max_depth <= 1 {
        return (score, mv);
    }

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
) -> SearchResult {
    let start = Instant::now();
    let mut board = Board::from_bitboards(b0, b1);
    let deadline = time_limit.map(|s| start + Duration::from_secs_f64(s));

    let mut searcher = Searcher::new(None, cfg);
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
        qnodes: 0,
        tt_hits: searcher.tt_hits,
        tt_cutoffs: searcher.tt_cutoffs,
        beta_cutoffs: searcher.beta_cutoffs,
        elapsed_ms: start.elapsed().as_millis() as u64,
        pv,
    }
}

/// 既定評価での反復深化 + 時間制御。
pub fn search_position(b0: u64, b1: u64, max_depth: u8, time_limit: Option<f64>) -> (i64, i32) {
    search_with_cfg(b0, b1, max_depth, time_limit, EvalConfig::default_config())
}

/// opening から打ち継ぎ、先手=cfg0 / 後手=cfg1 の評価で固定深さ対局し勝者を返す。
fn play_game(opening: &[u8], cfg0: EvalConfig, cfg1: EvalConfig, depth: u8) -> Option<u8> {
    let mut board = Board::new();
    for &c in opening {
        board.play(c as usize).unwrap();
    }
    while !board.is_terminal() {
        let cfg = if board.turn == 0 { cfg0 } else { cfg1 };
        // 各手で fresh TT 探索 (Python ハーネスと同じ意味論)。
        let (_, mv) = search_with_cfg(board.bb[0], board.bb[1], depth, None, cfg);
        let col = if mv >= 0 {
            mv as usize
        } else {
            board.legal_moves()[0] as usize
        };
        board.play(col).unwrap();
    }
    board.winner
}

/// 評価 A/B を openings で総当たり対戦させ (a_wins, b_wins, draws) を返す。
///
/// 各 opening を先後入れ替えて 2 局 (A先手/B後手 と B先手/A後手) 打ち、先手有利を相殺。
pub fn play_match(
    cfg_a: EvalConfig,
    cfg_b: EvalConfig,
    openings: &[Vec<u8>],
    depth: u8,
) -> (u32, u32, u32) {
    let (mut aw, mut bw, mut dr) = (0u32, 0u32, 0u32);
    for opening in openings {
        match play_game(opening, cfg_a, cfg_b, depth) {
            Some(0) => aw += 1,
            Some(1) => bw += 1,
            _ => dr += 1,
        }
        match play_game(opening, cfg_b, cfg_a, depth) {
            Some(0) => bw += 1,
            Some(1) => aw += 1,
            _ => dr += 1,
        }
    }
    (aw, bw, dr)
}
