//! Score Four コアの Rust 実装 (PyO3 拡張モジュール `score_four_rs`)。
//!
//! 段階1 (コア先行): board.py / lines.py を Rust へ移植し、Python 参照と同一結果を
//! 返すことを言語横断の契約テストで保証する。探索・評価は後続段階で移植する。

use pyo3::prelude::*;

mod board;
mod evaluate;
mod lines;
mod search;
mod symmetry;

use board::Board;

/// 全 76 本の勝利ラインを (i0, i1, i2, i3) のタプル列で返す (Python の all_lines と一致)。
#[pyfunction]
#[pyo3(name = "lines")]
fn py_lines() -> Vec<(usize, usize, usize, usize)> {
    lines::all_lines()
        .into_iter()
        .map(|l| (l[0], l[1], l[2], l[3]))
        .collect()
}

/// Python の `Board` と同じ意味論を持つビットボード局面 (契約テスト用)。
#[pyclass]
struct RustBoard {
    inner: Board,
}

#[pymethods]
impl RustBoard {
    #[new]
    fn new() -> Self {
        RustBoard {
            inner: Board::new(),
        }
    }

    fn legal_moves(&self) -> Vec<u8> {
        self.inner.legal_moves()
    }

    fn winning_moves(&self, player: usize) -> Vec<u8> {
        self.inner.winning_moves(player)
    }

    fn has_winning_move(&self, player: usize) -> bool {
        self.inner.has_winning_move(player)
    }

    fn play(&mut self, column: usize) -> PyResult<bool> {
        self.inner
            .play(column)
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    fn undo(&mut self) {
        self.inner.undo();
    }

    fn is_full(&self) -> bool {
        self.inner.is_full()
    }

    fn is_terminal(&self) -> bool {
        self.inner.is_terminal()
    }

    fn bb(&self) -> (u64, u64) {
        (self.inner.bb[0], self.inner.bb[1])
    }

    fn heights(&self) -> Vec<u8> {
        self.inner.heights.to_vec()
    }

    #[getter]
    fn turn(&self) -> u8 {
        self.inner.turn
    }

    #[getter]
    fn winner(&self) -> Option<u8> {
        self.inner.winner
    }

    #[getter]
    fn num_moves(&self) -> usize {
        self.inner.num_moves()
    }
}

/// 局面 (b0,b1) の D4 正規化キーと変換 t (Python の canonical と一致)。
#[pyfunction]
#[pyo3(name = "canonical")]
fn py_canonical(b0: u64, b1: u64) -> (u128, usize) {
    symmetry::canonical(b0, b1)
}

/// 既定評価 default_eval の値 (手番側視点)。Python の default_eval と一致。
#[pyfunction]
#[pyo3(name = "eval_default")]
fn py_eval_default(b0: u64, b1: u64) -> i64 {
    evaluate::default_eval(&Board::from_bitboards(b0, b1))
}

/// 全幅ウィンドウの negamax 値 (fresh TT)。Python negamax(full window) と一致。
#[pyfunction]
#[pyo3(name = "negamax_value")]
fn py_negamax_value(b0: u64, b1: u64, depth: u8) -> i64 {
    search::negamax_value(b0, b1, depth)
}

/// 反復深化 + 時間制御で (score, best_move)。Python search と一致 (time_limit=None 時)。
#[pyfunction]
#[pyo3(name = "search", signature = (b0, b1, max_depth, time_limit=None))]
fn py_search(b0: u64, b1: u64, max_depth: u8, time_limit: Option<f64>) -> (i64, i64) {
    let (score, mv) = search::search_position(b0, b1, max_depth, time_limit);
    (score, mv as i64)
}

/// search の最善手だけを返す。
#[pyfunction]
#[pyo3(name = "best_move", signature = (b0, b1, max_depth, time_limit=None))]
fn py_best_move(b0: u64, b1: u64, max_depth: u8, time_limit: Option<f64>) -> i64 {
    search::search_position(b0, b1, max_depth, time_limit).1 as i64
}

#[pymodule]
fn score_four_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_lines, m)?)?;
    m.add_function(wrap_pyfunction!(py_canonical, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_default, m)?)?;
    m.add_function(wrap_pyfunction!(py_negamax_value, m)?)?;
    m.add_function(wrap_pyfunction!(py_search, m)?)?;
    m.add_function(wrap_pyfunction!(py_best_move, m)?)?;
    m.add_class::<RustBoard>()?;
    Ok(())
}
