//! ビットボード表現・着手生成・勝利判定 (board.py の Rust 移植)。
//!
//! Python の `Board` と完全に同じ意味論を持たせ、言語横断の契約テストで全局面一致を
//! 保証する (センサー先行)。着手は柱 0..15 の選択のみ。コマは最下段の空きに落ちる。

use crate::lines::{build_line_tables, LineTables, NUM_CELLS};
use std::sync::OnceLock;

pub const N: u8 = 4;
pub const NUM_COLUMNS: usize = 16;

static TABLES: OnceLock<LineTables> = OnceLock::new();

fn tables() -> &'static LineTables {
    TABLES.get_or_init(build_line_tables)
}

/// 76 ラインのビットマスク (評価関数の全ライン走査用)。
pub fn line_masks() -> &'static [u64] {
    &tables().line_masks
}

#[derive(Clone)]
pub struct Board {
    pub bb: [u64; 2],
    pub heights: [u8; NUM_COLUMNS],
    pub turn: u8,
    pub winner: Option<u8>,
    moves_played: usize,            // 盤上のコマ総数 (復元局面でも正しく持つ)
    history: Vec<(u8, Option<u8>)>, // (column, 着手前の winner)
}

impl Default for Board {
    fn default() -> Self {
        Self::new()
    }
}

impl Board {
    pub fn new() -> Self {
        Board {
            bb: [0, 0],
            heights: [0; NUM_COLUMNS],
            turn: 0,
            winner: None,
            moves_played: 0,
            history: Vec::new(),
        }
    }

    /// ビットボード (b0, b1) から非終端局面を復元する (探索の入口で使う)。
    ///
    /// 高さは各柱の占有数、手番は総コマ数の偶奇で一意。winner は None 前提
    /// (非終端の入力でのみ呼ぶ)。history は空 (探索が打つ手だけ undo 対象になる)。
    pub fn from_bitboards(b0: u64, b1: u64) -> Self {
        let occ = b0 | b1;
        let mut heights = [0u8; NUM_COLUMNS];
        for (c, h) in heights.iter_mut().enumerate() {
            let mut count = 0u8;
            for z in 0..4 {
                if occ & (1u64 << (c + z * 16)) != 0 {
                    count += 1;
                }
            }
            *h = count;
        }
        let moves_played = occ.count_ones() as usize;
        Board {
            bb: [b0, b1],
            heights,
            turn: (moves_played & 1) as u8,
            winner: None,
            moves_played,
            history: Vec::new(),
        }
    }

    pub fn num_moves(&self) -> usize {
        self.moves_played
    }

    pub fn is_full(&self) -> bool {
        self.moves_played == NUM_CELLS
    }

    pub fn is_terminal(&self) -> bool {
        self.winner.is_some() || self.is_full()
    }

    pub fn legal_moves(&self) -> Vec<u8> {
        if self.winner.is_some() {
            return Vec::new();
        }
        (0..NUM_COLUMNS as u8)
            .filter(|&c| self.heights[c as usize] < N)
            .collect()
    }

    /// player がセル idx に置いたら idx を通る線で 4 が揃うか (試し置き; idx は未占有)。
    // any(|&mask| occ & mask == mask) は「mask が occ の部分集合か」の判定で、単純な
    // 等値ではないため contains では表せない (clippy::manual_contains は誤検知)。
    #[allow(clippy::manual_contains)]
    fn completes_line(&self, player: usize, idx: usize) -> bool {
        let occ = self.bb[player] | (1u64 << idx);
        tables().cell_lines[idx]
            .iter()
            .any(|&mask| occ & mask == mask)
    }

    /// idx に既に置いた直後の勝利判定 (idx を通る線のみの増分判定)。
    #[allow(clippy::manual_contains)]
    fn wins_through(&self, player: usize, idx: usize) -> bool {
        let occ = self.bb[player];
        tables().cell_lines[idx]
            .iter()
            .any(|&mask| occ & mask == mask)
    }

    pub fn winning_moves(&self, player: usize) -> Vec<u8> {
        if self.winner.is_some() {
            return Vec::new();
        }
        let mut res = Vec::new();
        for c in 0..NUM_COLUMNS {
            let h = self.heights[c];
            if h < N && self.completes_line(player, c + (h as usize) * 16) {
                res.push(c as u8);
            }
        }
        res
    }

    pub fn has_winning_move(&self, player: usize) -> bool {
        if self.winner.is_some() {
            return false;
        }
        (0..NUM_COLUMNS).any(|c| {
            let h = self.heights[c];
            h < N && self.completes_line(player, c + (h as usize) * 16)
        })
    }

    /// 手番のプレイヤーが柱 column に着手する。勝ちを決めた手なら Ok(true)。
    pub fn play(&mut self, column: usize) -> Result<bool, String> {
        if self.winner.is_some() {
            return Err("game is already decided".to_string());
        }
        let h = self.heights[column];
        if h >= N {
            return Err(format!("column {column} is full"));
        }
        let player = self.turn as usize;
        let idx = column + (h as usize) * 16;
        self.bb[player] |= 1u64 << idx;
        self.heights[column] = h + 1;
        self.history.push((column as u8, self.winner));
        self.moves_played += 1;
        let won = self.wins_through(player, idx);
        if won {
            self.winner = Some(self.turn);
        }
        self.turn ^= 1;
        Ok(won)
    }

    pub fn undo(&mut self) {
        let (column, prev_winner) = self.history.pop().expect("no move to undo");
        let column = column as usize;
        self.turn ^= 1;
        let player = self.turn as usize;
        let h = self.heights[column] - 1;
        self.heights[column] = h;
        let idx = column + (h as usize) * 16;
        self.bb[player] &= !(1u64 << idx);
        self.moves_played -= 1;
        self.winner = prev_winner;
    }
}
