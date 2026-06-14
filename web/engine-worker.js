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
  }
};
