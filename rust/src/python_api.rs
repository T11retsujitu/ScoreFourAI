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
        ..EvalConfig::default_config()
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

/// 64 セルの幾何種類 CORNER/EDGE/FACE/INTERIOR (Phase 10 実験)。Python の CELL_TYPE と一致。
#[pyfunction]
#[pyo3(name = "cell_types")]
fn py_cell_types() -> Vec<u8> {
    evaluate::CELL_TYPE.to_vec()
}

/// 局面 (b0,b1) の D4 不変な整数特徴量 [open1,open2,open3,parity,reach3,center] (先手-後手差)。
/// 学習評価 (Phase 8) の教師データ生成・契約テスト用。Python の FEATURES と一致。
#[pyfunction]
#[pyo3(name = "features")]
fn py_features(b0: u64, b1: u64) -> Vec<i64> {
    evaluate::features(&Board::from_bitboards(b0, b1)).to_vec()
}

/// 学習線形重み lw による手番側視点の評価値 (整数内積)。Python の learned_eval と一致。
#[pyfunction]
#[pyo3(name = "eval_learned")]
fn py_eval_learned(b0: u64, b1: u64, lw: Vec<i64>) -> PyResult<i64> {
    if lw.len() != evaluate::NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "lw must have {} weights",
            evaluate::NF
        )));
    }
    let mut w = [0i64; evaluate::NF];
    w.copy_from_slice(&lw);
    Ok(evaluate::eval_learned(&Board::from_bitboards(b0, b1), &w))
}

/// 学習評価 (重み lw) を先手 A、既定パリティ評価を B として openings で総当たり対戦させ
/// (a_wins, b_wins, draws) を返す。Phase 8 の採否判定用。time_ms>0 で固定時間対局。
#[pyfunction]
#[pyo3(name = "play_match_learned", signature = (lw, openings, depth, time_ms=0, qdepth=0))]
fn py_play_match_learned(
    lw: Vec<i64>,
    openings: Vec<Vec<u8>>,
    depth: u8,
    time_ms: u32,
    qdepth: u8,
) -> PyResult<(u32, u32, u32)> {
    if lw.len() != evaluate::NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "lw must have {} weights",
            evaluate::NF
        )));
    }
    let mut w = [0i64; evaluate::NF];
    w.copy_from_slice(&lw);
    Ok(search::play_match(
        EvalConfig::learned_config(w),
        qdepth,
        EvalConfig::default_config(),
        qdepth,
        &openings,
        depth,
        time_ms,
    ))
}

/// 局面 (b0,b1) の幾何・解放特徴 8 次元 (手番側視点・Phase 10)。Python geometric_features と一致。
#[pyfunction]
#[pyo3(name = "geometric_features")]
fn py_geometric_features(b0: u64, b1: u64) -> Vec<i64> {
    evaluate::geometric_features(&Board::from_bitboards(b0, b1)).to_vec()
}

/// 幾何重み w による手番側視点の加点 (整数内積)。Python eval_geometric と一致。
#[pyfunction]
#[pyo3(name = "eval_geometric")]
fn py_eval_geometric(b0: u64, b1: u64, w: Vec<i64>) -> PyResult<i64> {
    if w.len() != evaluate::GEO_NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "w must have {} weights",
            evaluate::GEO_NF
        )));
    }
    let mut gw = [0i64; evaluate::GEO_NF];
    gw.copy_from_slice(&w);
    Ok(evaluate::eval_geometric(
        &Board::from_bitboards(b0, b1),
        &gw,
    ))
}

/// 幾何候補 (default + geo 重み) を先手 A、既定 default を B として openings で総当たり対戦し
/// (a_wins, b_wins, draws) を返す。Phase 10 の採否判定用。time_ms>0 で固定時間対局。
#[pyfunction]
#[pyo3(name = "play_match_geometric", signature = (geo_weights, openings, depth, time_ms=0, qdepth=0))]
fn py_play_match_geometric(
    geo_weights: Vec<i64>,
    openings: Vec<Vec<u8>>,
    depth: u8,
    time_ms: u32,
    qdepth: u8,
) -> PyResult<(u32, u32, u32)> {
    if geo_weights.len() != evaluate::GEO_NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "geo_weights must have {} weights",
            evaluate::GEO_NF
        )));
    }
    let mut gw = [0i64; evaluate::GEO_NF];
    gw.copy_from_slice(&geo_weights);
    Ok(search::play_match(
        EvalConfig::default_plus_geometric(gw),
        qdepth,
        EvalConfig::default_config(),
        qdepth,
        &openings,
        depth,
        time_ms,
    ))
}

/// 全幅ウィンドウの negamax 値 (fresh TT, 静穏化 qdepth)。Python negamax と一致。
#[pyfunction]
#[pyo3(name = "negamax_value", signature = (b0, b1, depth, qdepth=0))]
fn py_negamax_value(b0: u64, b1: u64, depth: u8, qdepth: u8) -> i64 {
    search::negamax_value(b0, b1, depth, qdepth)
}

/// 候補評価 (default + geo) での全幅 negamax 値 (fresh TT)。Phase 10 の探索契約用。
#[pyfunction]
#[pyo3(name = "negamax_value_geometric")]
fn py_negamax_value_geometric(b0: u64, b1: u64, depth: u8, geo_weights: Vec<i64>) -> PyResult<i64> {
    if geo_weights.len() != evaluate::GEO_NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "geo_weights must have {} weights",
            evaluate::GEO_NF
        )));
    }
    let mut gw = [0i64; evaluate::GEO_NF];
    gw.copy_from_slice(&geo_weights);
    Ok(search::negamax_value_cfg(
        b0,
        b1,
        depth,
        0,
        EvalConfig::default_plus_geometric(gw),
    ))
}

/// 候補評価 (default + geo) で反復深化探索し (score, best_move) を返す。Phase 10 の探索契約用。
#[pyfunction]
#[pyo3(name = "search_geometric", signature = (b0, b1, max_depth, geo_weights, time_limit=None))]
fn py_search_geometric(
    b0: u64,
    b1: u64,
    max_depth: u8,
    geo_weights: Vec<i64>,
    time_limit: Option<f64>,
) -> PyResult<(i64, i64)> {
    if geo_weights.len() != evaluate::GEO_NF {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "geo_weights must have {} weights",
            evaluate::GEO_NF
        )));
    }
    let mut gw = [0i64; evaluate::GEO_NF];
    gw.copy_from_slice(&geo_weights);
    let (score, mv) = search::search_with_cfg(
        b0,
        b1,
        max_depth,
        time_limit,
        EvalConfig::default_plus_geometric(gw),
        0,
    );
    Ok((score, mv as i64))
}

/// 反復深化 + 時間制御 + 評価設定 + 静穏化 qdepth で (score, best_move)。
/// 既定 (-8,0,0,1,5,25, qdepth=0) で Python search と一致。
#[pyfunction]
#[pyo3(name = "search", signature = (b0, b1, max_depth, time_limit=None, parity_weight=-8, immediate=0, parity_mode=0, w1=1, w2=5, w3=25, qdepth=0))]
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
    qdepth: u8,
) -> (i64, i64) {
    let cfg = cfg_from_tuple((parity_weight, immediate, parity_mode, w1, w2, w3));
    let (score, mv) = search::search_with_cfg(b0, b1, max_depth, time_limit, cfg, qdepth);
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
#[pyo3(name = "analyze", signature = (b0, b1, max_depth, time_limit=None, qdepth=0))]
fn py_analyze<'py>(
    py: Python<'py>,
    b0: u64,
    b1: u64,
    max_depth: u8,
    time_limit: Option<f64>,
    qdepth: u8,
) -> PyResult<Bound<'py, PyDict>> {
    let r = search::analyze_with_cfg(
        b0,
        b1,
        max_depth,
        time_limit,
        EvalConfig::default_config(),
        qdepth,
    );
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

/// 詰み探索 (Phase 7)。局面 (b0,b1) の強制勝ち/負けを零評価反復深化で読み切り、
/// status / plies / best_move / pv を dict で返す。Python の solve.solve と一致する。
/// status: "win" / "loss" / "draw" / "unknown" (手番側視点)。
#[pyfunction]
#[pyo3(name = "solve", signature = (b0, b1, max_plies=64))]
fn py_solve<'py>(py: Python<'py>, b0: u64, b1: u64, max_plies: u8) -> PyResult<Bound<'py, PyDict>> {
    let r = search::solve(b0, b1, max_plies);
    let status = match r.status {
        search::MATE_WIN => "win",
        search::MATE_LOSS => "loss",
        search::MATE_DRAW => "draw",
        _ => "unknown",
    };
    let d = PyDict::new(py);
    d.set_item("status", status)?;
    // plies は win/loss のときだけ意味を持つ (それ以外は None)。
    if r.status == search::MATE_WIN || r.status == search::MATE_LOSS {
        d.set_item("plies", r.plies)?;
    } else {
        d.set_item("plies", py.None())?;
    }
    d.set_item("best_move", r.best_move)?;
    let pv: Vec<i64> = r.pv.iter().map(|&x| x as i64).collect();
    d.set_item("pv", pv)?;
    Ok(d)
}

/// 評価/静穏化 A/B を openings で総当たり対戦させ (a_wins, b_wins, draws) を返す。
/// cfg は (parity_weight, immediate, parity_mode, w1, w2, w3)。time_ms>0 で固定時間対局。
#[pyfunction]
#[pyo3(name = "play_match", signature = (cfg_a, cfg_b, openings, depth, time_ms=0, qdepth_a=0, qdepth_b=0))]
#[allow(clippy::too_many_arguments)]
fn py_play_match(
    cfg_a: (i64, i64, u8, i64, i64, i64),
    cfg_b: (i64, i64, u8, i64, i64, i64),
    openings: Vec<Vec<u8>>,
    depth: u8,
    time_ms: u32,
    qdepth_a: u8,
    qdepth_b: u8,
) -> (u32, u32, u32) {
    search::play_match(
        cfg_from_tuple(cfg_a),
        qdepth_a,
        cfg_from_tuple(cfg_b),
        qdepth_b,
        &openings,
        depth,
        time_ms,
    )
}

#[pymodule]
fn score_four_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_lines, m)?)?;
    m.add_function(wrap_pyfunction!(py_canonical, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_default, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_cfg, m)?)?;
    m.add_function(wrap_pyfunction!(py_cell_types, m)?)?;
    m.add_function(wrap_pyfunction!(py_features, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_learned, m)?)?;
    m.add_function(wrap_pyfunction!(py_play_match_learned, m)?)?;
    m.add_function(wrap_pyfunction!(py_geometric_features, m)?)?;
    m.add_function(wrap_pyfunction!(py_eval_geometric, m)?)?;
    m.add_function(wrap_pyfunction!(py_play_match_geometric, m)?)?;
    m.add_function(wrap_pyfunction!(py_negamax_value, m)?)?;
    m.add_function(wrap_pyfunction!(py_negamax_value_geometric, m)?)?;
    m.add_function(wrap_pyfunction!(py_search_geometric, m)?)?;
    m.add_function(wrap_pyfunction!(py_search, m)?)?;
    m.add_function(wrap_pyfunction!(py_best_move, m)?)?;
    m.add_function(wrap_pyfunction!(py_analyze, m)?)?;
    m.add_function(wrap_pyfunction!(py_solve, m)?)?;
    m.add_function(wrap_pyfunction!(py_play_match, m)?)?;
    m.add_class::<RustBoard>()?;
    Ok(())
}
