//! Score Four コアの Rust 実装 (PyO3 拡張モジュール `score_four_rs`)。
//!
//! 段階1 (コア先行): board.py / lines.py を Rust へ移植し、Python 参照と同一結果を
//! 返すことを言語横断の契約テストで保証する。探索・評価は後続段階で移植する。

use pyo3::prelude::*;

mod board;
mod lines;

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

#[pymodule]
fn score_four_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_lines, m)?)?;
    m.add_class::<RustBoard>()?;
    Ok(())
}
