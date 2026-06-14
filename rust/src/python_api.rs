//! PyO3 バインディング (Python 拡張 `score_four_rs`)。`python` feature でのみ有効。
//! wasm ビルドでは無効化される (pyo3 は wasm32 をターゲットにできないため)。

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::board::Board;
use crate::evaluate::EvalConfig;
use crate::{evaluate, lines, search, symmetry};

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

/// 評価設定タプル (parity_weight, immediate, parity_mode, w1, w2, w3) -> EvalConfig。
fn cfg_from_tuple(c: (i64, i64, u8, i64, i64, i64)) -> EvalConfig {
    EvalConfig {
        parity_weight: c.0,
        immediate: c.1,
        parity_mode: c.2,
        weights: [c.3, c.4, c.5],
    }
}

/// 設定での評価値 (D4不変性テスト用)。基本重み w1,w2,w3 は既定 1,5,25。
#[pyfunction]
#[pyo3(name = "eval_cfg", signature = (b0, b1, parity_weight, immediate, parity_mode, w1=1, w2=5, w3=25))]
#[allow(clippy::too_many_arguments)]
fn py_eval_cfg(
    b0: u64,
    b1: u64,
    parity_weight: i64,
    immediate: i64,
    parity_mode: u8,
    w1: i64,
    w2: i64,
    w3: i64,
) -> i64 {
    let cfg = cfg_from_tuple((parity_weight, immediate, parity_mode, w1, w2, w3));
    evaluate::eval_with(&Board::from_bitboards(b0, b1), &cfg)
}

/// 全幅ウィンドウの negamax 値 (fresh TT)。Python negamax(full window) と一致。
#[pyfunction]
#[pyo3(name = "negamax_value")]
fn py_negamax_value(b0: u64, b1: u64, depth: u8) -> i64 {
    search::negamax_value(b0, b1, depth)
}

/// 反復深化 + 時間制御 + 評価設定で (score, best_move)。
/// 既定 (-8, 0, 0, 1, 5, 25) で Python search と一致。
#[pyfunction]
#[pyo3(name = "search", signature = (b0, b1, max_depth, time_limit=None, parity_weight=-8, immediate=0, parity_mode=0, w1=1, w2=5, w3=25))]
#[allow(clippy::too_many_arguments)]
fn py_search(
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    parity_weight: i64,
    immediate: i64,
    parity_mode: u8,
    w1: i64,
    w2: i64,
    w3: i64,
) -> (i64, i64) {
    let cfg = cfg_from_tuple((parity_weight, immediate, parity_mode, w1, w2, w3));
    let (score, mv) = search::search_with_cfg(b0, b1, max_depth, time_limit, cfg);
    (score, mv as i64)
}

/// search の最善手だけを返す (既定評価)。
#[pyfunction]
#[pyo3(name = "best_move", signature = (b0, b1, max_depth, time_limit=None))]
fn py_best_move(b0: u64, b1: u64, max_depth: u8, time_limit: Option<f64>) -> i64 {
    search::search_position(b0, b1, max_depth, time_limit).1 as i64
}

/// 既定評価で反復深化探索し、統計と PV 付きの結果を dict で返す (ベンチマーク/解析用)。
/// (score, best_move) は同条件の search と一致する (加算的; 値は不変)。
#[pyfunction]
#[pyo3(name = "analyze", signature = (b0, b1, max_depth, time_limit=None))]
fn py_analyze<'py>(
    py: Python<'py>,
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
) -> PyResult<Bound<'py, PyDict>> {
    let r = search::analyze_with_cfg(b0, b1, max_depth, time_limit, EvalConfig::default_config());
    let d = PyDict::new(py);
    d.set_item("score", r.score)?;
    d.set_item("best_move", r.best_move)?;
    d.set_item("completed_depth", r.completed_depth)?;
    d.set_item("nodes", r.nodes)?;
    d.set_item("qnodes", r.qnodes)?;
    d.set_item("tt_hits", r.tt_hits)?;
    d.set_item("tt_cutoffs", r.tt_cutoffs)?;
    d.set_item("beta_cutoffs", r.beta_cutoffs)?;
    d.set_item("elapsed_ms", r.elapsed_ms)?;
    let pv: Vec<i64> = r.pv.iter().map(|&x| x as i64).collect();
    d.set_item("pv", pv)?;
    Ok(d)
}

/// 評価 A/B を openings で総当たり対戦させ (a_wins, b_wins, draws) を返す。
/// cfg は (parity_weight, immediate, parity_mode, w1, w2, w3)。
#[pyfunction]
#[pyo3(name = "play_match")]
fn py_play_match(
    cfg_a: (i64, i64, u8, i64, i64, i64),
    cfg_b: (i64, i64, u8, i64, i64, i64),
    openings: Vec<Vec<u8>>,
    depth: u8,
) -> (u32, u32, u32) {
    search::play_match(
        cfg_from_tuple(cfg_a),
        cfg_from_tuple(cfg_b),
        &openings,
        depth,
    )
}

#[pymodule]
fn score_four_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_lines, m)?)?;
    m.add_function(wrap_pyfunction!(py_canonical, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_default, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_cfg, m)?)?;
    m.add_function(wrap_pyfunction!(py_negamax_value, m)?)?;
    m.add_function(wrap_pyfunction!(py_search, m)?)?;
    m.add_function(wrap_pyfunction!(py_best_move, m)?)?;
    m.add_function(wrap_pyfunction!(py_analyze, m)?)?;
    m.add_function(wrap_pyfunction!(py_play_match, m)?)?;
    m.add_class::<RustBoard>()?;
    Ok(())
}
