// Score Four エンジン (WASM) を動かす Web Worker。
// メインスレッドを固めないよう、探索はここで実行する。
// ビットボードは 10進文字列で受け渡し (BigInt) し、wasm へ u64 として渡す。

let exports = null;

const ready = (async () => {
  const resp = await fetch("engine.wasm");
  const bytes = await resp.arrayBuffer();
  const { instance } = await WebAssembly.instantiate(bytes, {});
  exports = instance.exports;
})();

self.onmessage = async (ev) => {
  const msg = ev.data;
  await ready;
  const b0 = BigInt(msg.b0);
  const b1 = BigInt(msg.b1);
  if (msg.type === "search") {
    exports.sf_search(b0, b1, msg.depth | 0);
    self.postMessage({
      type: "result",
      id: msg.id,
      reason: msg.reason, // 'engine' (応手) or 'analysis' (解析)
      score: exports.sf_score().toString(),
      move: exports.sf_move() | 0,
    });
  } else if (msg.type === "solve") {
    // 詰み探索 (Phase 7)。status 0=unknown,1=win,2=loss,3=draw。
    exports.sf_solve(b0, b1, msg.maxPlies | 0);
    const len = exports.sf_solve_pv_len() | 0;
    const pv = [];
    for (let i = 0; i < len; i++) pv.push(exports.sf_solve_pv(i) | 0);
    self.postMessage({
      type: "solve",
      id: msg.id,
      status: exports.sf_solve_status() | 0,
      plies: exports.sf_solve_plies() | 0,
      move: exports.sf_solve_move() | 0,
      pv,
    });
  }
};
