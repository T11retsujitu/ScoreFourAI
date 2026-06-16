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

// 定石 (web book) を WASM へ取り込む。失敗しても探索のみで動く (graceful)。
const bookReady = (async () => {
  await ready;
  if (!exports.sf_book_add) return 0; // book API が無い古い wasm
  try {
    const resp = await fetch("book.json");
    if (!resp.ok) return 0;
    const data = await resp.json();
    exports.sf_book_clear();
    const MASK = 0xffffffffffffffffn;
    for (const k in data.entries) {
      const [mv, score] = data.entries[k];
      const key = BigInt(k);
      exports.sf_book_add(key & MASK, key >> 64n, mv | 0, BigInt(score));
    }
    return exports.sf_book_size() | 0;
  } catch (e) {
    return 0; // book 無し → 探索のみ
  }
})();

// 定石ロード完了をメインスレッドへ通知 (UI バッジ用)。
bookReady.then((n) => self.postMessage({ type: "bookinfo", size: n }));

self.onmessage = async (ev) => {
  const msg = ev.data;
  await ready;
  const b0 = BigInt(msg.b0);
  const b1 = BigInt(msg.b1);
  if (msg.type === "search") {
    await bookReady;
    // 定石にあれば探索せず即応 (序盤が一瞬で・強い)。
    let bookMv = -1;
    if (exports.sf_book_move) bookMv = exports.sf_book_move(b0, b1) | 0;
    if (bookMv >= 0) {
      self.postMessage({
        type: "result",
        id: msg.id,
        reason: msg.reason,
        score: exports.sf_book_score(b0, b1).toString(),
        move: bookMv,
        book: true,
      });
      return;
    }
    exports.sf_search(b0, b1, msg.depth | 0);
    self.postMessage({
      type: "result",
      id: msg.id,
      reason: msg.reason, // 'engine' (応手) or 'analysis' (解析)
      score: exports.sf_score().toString(),
      move: exports.sf_move() | 0,
      book: false,
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
