/* 立体4目並べ (Score Four) — WASM エンジンと対局できる Web アプリ。
   盤の規約はエンジンと共通: cell = z*16 + y*4 + x (x:file a-d, y:rank 1-4, z:height 底=0)。
   柱(col) = y*4 + x (0..15)。ビットボードは BigInt (bit cell が立つ)。 */

"use strict";

const WIN = 1000000, MATE_LO = 999935;
const SOLVE_MAX = 13;   // 詰み探索の地平線 (手番側〜7手詰めまで)。応答性のため上限を設ける。
const $ = (id) => document.getElementById(id);
const cellIdx = (x, y, z) => z * 16 + y * 4 + x;
const colXY = (c) => [c % 4, Math.floor(c / 4)];           // col -> [x,y]
const colName = (c) => "abcd"[c % 4] + (Math.floor(c / 4) + 1);
const decode = (i) => [i % 4, Math.floor((i % 16) / 4), Math.floor(i / 16)]; // -> [x,y,z]

/* ---- 76 ライン (マスク + セル) を本プロジェクトの規約で生成 ---- */
function buildLines() {
  const seen = new Set(), masks = [], cells = [];
  for (let x = 0; x < 4; x++) for (let y = 0; y < 4; y++) for (let z = 0; z < 4; z++) {
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
      if (!dx && !dy && !dz) continue;
      const cs = []; let ok = true;
      for (let k = 0; k < 4; k++) {
        const nx = x + dx * k, ny = y + dy * k, nz = z + dz * k;
        if (nx < 0 || nx > 3 || ny < 0 || ny > 3 || nz < 0 || nz > 3) { ok = false; break; }
        cs.push(cellIdx(nx, ny, nz));
      }
      if (!ok) continue;
      const key = [...cs].sort((a, b) => a - b).join(",");
      if (seen.has(key)) continue;
      seen.add(key);
      let m = 0n; for (const c of cs) m |= 1n << BigInt(c);
      masks.push(m); cells.push(cs);
    }
  }
  return { masks, cells };
}
const LINES = buildLines();

/* ---- 局面の再生 (history が唯一の真実) ---- */
function replay(history) {
  let b0 = 0n, b1 = 0n;
  const heights = new Array(16).fill(0);
  let turn = 0, lastIdx = -1, winner = null, winCells = null;
  for (const c of history) {
    const z = heights[c];
    const [x, y] = colXY(c);
    const i = cellIdx(x, y, z);
    const bit = 1n << BigInt(i);
    if (turn === 0) b0 |= bit; else b1 |= bit;
    heights[c] = z + 1; lastIdx = i;
    // 勝利判定 (直前手を含むラインのみで十分だが全走査で簡潔に)
    const occ = turn === 0 ? b0 : b1;
    if (winner === null) {
      for (let li = 0; li < LINES.masks.length; li++) {
        if ((occ & LINES.masks[li]) === LINES.masks[li]) { winner = turn; winCells = LINES.cells[li]; break; }
      }
    }
    turn ^= 1;
  }
  // 脅威 (3つ同色 + 1空き) の空きマス
  const threats = new Set();
  if (winner === null) {
    for (let li = 0; li < LINES.masks.length; li++) {
      let p0 = 0, p1 = 0, empty = -1;
      for (const c of LINES.cells[li]) {
        const bit = 1n << BigInt(c);
        if (b0 & bit) p0++; else if (b1 & bit) p1++; else empty = c;
      }
      if (empty >= 0 && (p0 === 3 || p1 === 3)) threats.add(empty);
    }
  }
  const full = heights.every((h) => h === 4);
  return { b0, b1, heights, turn, lastIdx, winner, winCells, threats, full };
}

/* 詰み手順 (柱列) を、現局面から積んだときの着地セル index 列に変換する。 */
function pvCells(heights, pv) {
  const h = heights.slice(), cells = [];
  for (const c of pv) {
    if (c < 0 || c > 15 || h[c] >= 4) break;
    const [x, y] = colXY(c);
    cells.push(cellIdx(x, y, h[c])); h[c] += 1;
  }
  return cells;
}

/* ====== ゲーム状態 ====== */
const game = {
  history: [],
  humanSide: 0,       // 0=先手(黒) / 1=後手(生成り)
  depth: 8,
  showThreat: false,
  viewMode: "3d",
  thinking: false,
  reqId: 0,
  analysis: null,     // {score, move} 現局面のエンジン評価
  solving: false,
  solveSeq: 0,
  mate: null,         // 詰み探索結果 {status, plies, move, pv, turn} (現局面のもの)
};

/* ====== Worker ====== */
const worker = new Worker("engine-worker.js");
worker.onmessage = (ev) => {
  const msg = ev.data;
  if (msg.type === "bookinfo") {            // 定石ロード完了の通知
    game.bookSize = msg.size | 0;
    const el = $("bookStatus");
    if (el) el.textContent = game.bookSize > 0 ? `定石 ${game.bookSize}局面 読込済` : "";
    return;
  }
  if (msg.type === "solve") {               // 詰み探索の結果 (solveSeq で照合)
    if (msg.id !== game.solveSeq) return;
    game.solving = false;
    const st = replay(game.history);
    game.mate = { status: msg.status, plies: msg.plies, move: msg.move, pv: msg.pv, turn: st.turn };
    render();
    return;
  }
  if (msg.id !== game.reqId) return;       // 古い結果は無視
  game.thinking = false;
  const score = Number(BigInt(msg.score));
  if (msg.reason === "engine") {
    if (msg.move >= 0) game.history.push(msg.move);
    game.analysis = null;
    render();
    requestEngineOrAnalysis();             // 次が人間番なら解析を出す
  } else {
    game.analysis = { score, move: msg.move, book: !!msg.book };
    render();
  }
};

function requestEngineOrAnalysis() {
  const st = replay(game.history);
  if (st.winner !== null || st.full) { game.thinking = false; render(); return; }
  const reason = st.turn === game.humanSide ? "analysis" : "engine";
  game.thinking = (reason === "engine");
  game.reqId++;
  worker.postMessage({
    type: "search", id: game.reqId, reason,
    b0: st.b0.toString(), b1: st.b1.toString(), depth: game.depth,
  });
  if (reason === "engine") render();       // 「思考中」を表示
}

/* ====== 操作 ====== */
function clearMate() {                            // 局面が変わったら詰み結果を無効化
  game.mate = null; game.solving = false; game.solveSeq++;
}
function requestSolve() {
  const st = replay(game.history);
  if (st.winner !== null || st.full || game.thinking || game.solving) return;
  game.mate = null; game.solving = true;
  const seq = ++game.solveSeq;
  render();
  worker.postMessage({
    type: "solve", id: seq,
    b0: st.b0.toString(), b1: st.b1.toString(), maxPlies: SOLVE_MAX,
  });
}
function drop(col) {
  const st = replay(game.history);
  if (st.winner !== null || st.full) return;
  if (st.turn !== game.humanSide) return;        // 人間の番のみ
  if (st.heights[col] >= 4) return;
  game.history.push(col);
  game.analysis = null; clearMate();
  render();
  requestEngineOrAnalysis();
}
function newGame(humanSide) {
  game.history = []; game.humanSide = humanSide; game.analysis = null; game.thinking = false;
  clearMate();
  game.reqId++;
  render();
  requestEngineOrAnalysis();                      // エンジン先手なら初手を指す
}
function undo() {
  // 人間とエンジンの2手を戻す (人間の手番に戻す)。
  if (game.thinking) return;
  if (game.history.length === 0) return;
  game.history.pop();
  const st = replay(game.history);
  if (st.winner === null && !st.full && st.turn !== game.humanSide && game.history.length > 0) {
    game.history.pop();
  }
  game.analysis = null; clearMate(); game.reqId++;
  render();
  requestEngineOrAnalysis();
}

/* ====== 3D (three.js r128) ====== */
const has3D = (typeof THREE !== "undefined");
let three = null;
const S = 1.0, RB = 0.33, VSTEP = 0.62, BASE = 4 * S + 0.6, BTH = 0.3;
const ballPos = (x, y, z) => [(x - 1.5) * S, 0.40 + z * VSTEP, (y - 1.5) * S];

function makeLabel(text) {
  const c = document.createElement("canvas"); c.width = c.height = 64;
  const g = c.getContext("2d"); g.fillStyle = "#73776f"; g.font = "bold 44px sans-serif";
  g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 32, 34);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true }));
  sp.scale.set(0.5, 0.5, 0.5); return sp;
}

let gl3dFailed = false;
function init3D() {
  if (!has3D || three || gl3dFailed) return;
  const host = $("board3d");
  const scene = new THREE.Scene();
  const W = host.clientWidth || 600, H = host.clientHeight || 400;
  const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (err) {
    gl3dFailed = true;   // WebGL 非対応環境 → スライス表示にフォールバック
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(W, H); host.appendChild(renderer.domElement);
  renderer.domElement.style.touchAction = "none";

  scene.add(new THREE.HemisphereLight(0xffffff, 0x6b6256, 0.98));
  const dir = new THREE.DirectionalLight(0xffffff, 0.5); dir.position.set(5, 9, 6); scene.add(dir);
  const base = new THREE.Mesh(new THREE.BoxGeometry(BASE, BTH, BASE),
    new THREE.MeshPhongMaterial({ color: 0xcdb78f })); base.position.y = -BTH / 2; scene.add(base);

  const pegMat = new THREE.MeshPhongMaterial({ color: 0xb79a6e }); const pegH = 4 * VSTEP + 0.15;
  const pickers = [];
  for (let x = 0; x < 4; x++) for (let y = 0; y < 4; y++) {
    const peg = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.055, pegH, 12), pegMat);
    peg.position.set((x - 1.5) * S, pegH / 2, (y - 1.5) * S); scene.add(peg);
    // クリック判定用の透明な太い柱
    const pick = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, pegH + 0.4, 10),
      new THREE.MeshBasicMaterial({ visible: false }));
    pick.position.set((x - 1.5) * S, (pegH + 0.4) / 2, (y - 1.5) * S);
    pick.userData.col = y * 4 + x; scene.add(pick); pickers.push(pick);
  }
  "abcd".split("").forEach((f, x) => { const s = makeLabel(f); s.position.set((x - 1.5) * S, 0.06, -2.25); scene.add(s); });
  ["1", "2", "3", "4"].forEach((r, y) => { const s = makeLabel(r); s.position.set(-2.25, 0.06, (y - 1.5) * S); scene.add(s); });

  const stones = new THREE.Group(), highlights = new THREE.Group();
  scene.add(stones); scene.add(highlights);

  three = {
    scene, camera, renderer, host, stones, highlights, pickers,
    raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(),
    matP1: new THREE.MeshPhongMaterial({ color: 0x2b2b30, shininess: 45, specular: 0x5a5a5a }),
    matP2: new THREE.MeshPhongMaterial({ color: 0xf2e8d6, shininess: 30, specular: 0x888888 }),
    matWin: new THREE.MeshPhongMaterial({ color: 0xd8920f, emissive: 0x6e4600, shininess: 60 }),
    ballGeo: new THREE.SphereGeometry(RB, 28, 20),
    theta: 0.72, phi: 1.0, radius: 7.6, target: new THREE.Vector3(0, 1.0, 0),
  };

  const el = renderer.domElement; let drag = false, moved = false, lx = 0, ly = 0;
  el.addEventListener("pointerdown", (e) => { drag = true; moved = false; lx = e.clientX; ly = e.clientY; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (Math.abs(e.clientX - lx) + Math.abs(e.clientY - ly) > 4) moved = true;
    three.theta -= (e.clientX - lx) * 0.01;
    three.phi = Math.max(0.16, Math.min(1.45, three.phi - (e.clientY - ly) * 0.01));
    lx = e.clientX; ly = e.clientY; e.preventDefault();
  });
  el.addEventListener("pointerup", (e) => {
    drag = false;
    if (!moved) pick3D(e);            // 動かさなければクリック=着手
  });
  el.addEventListener("pointercancel", () => { drag = false; });
  el.addEventListener("wheel", (e) => { three.radius = Math.max(4, Math.min(13, three.radius * (1 + e.deltaY * 0.0012))); e.preventDefault(); }, { passive: false });

  (function loop() {
    if (!three) return;
    const t = three, c = t.camera;
    c.position.set(
      t.target.x + t.radius * Math.sin(t.phi) * Math.sin(t.theta),
      t.target.y + t.radius * Math.cos(t.phi),
      t.target.z + t.radius * Math.sin(t.phi) * Math.cos(t.theta));
    c.lookAt(t.target); t.renderer.render(t.scene, c);
    requestAnimationFrame(loop);
  })();
}
function pick3D(e) {
  if (!three) return;
  const r = three.renderer.domElement.getBoundingClientRect();
  three.pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
  three.pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
  three.raycaster.setFromCamera(three.pointer, three.camera);
  const hit = three.raycaster.intersectObjects(three.pickers, false);
  if (hit.length) drop(hit[0].object.userData.col);
}
function resize3D() {
  if (!three) return; const W = three.host.clientWidth, H = three.host.clientHeight;
  if (!W || !H) return; three.renderer.setSize(W, H); three.camera.aspect = W / H; three.camera.updateProjectionMatrix();
}
function update3D(st) {
  if (!three) return;
  const { stones, highlights } = three;
  while (stones.children.length) stones.remove(stones.children[0]);
  while (highlights.children.length) highlights.remove(highlights.children[0]);
  const winSet = new Set(st.winCells || []);
  for (let i = 0; i < 64; i++) {
    const bit = 1n << BigInt(i);
    const v = (st.b0 & bit) ? 1 : (st.b1 & bit) ? 2 : 0;
    if (!v) continue;
    const [x, y, z] = decode(i); const p = ballPos(x, y, z);
    const mat = winSet.has(i) ? three.matWin : (v === 1 ? three.matP1 : three.matP2);
    const m = new THREE.Mesh(three.ballGeo, mat); m.position.set(p[0], p[1], p[2]); stones.add(m);
    if (i === st.lastIdx) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(RB * 1.28, 0.032, 8, 28),
        new THREE.MeshBasicMaterial({ color: 0x3b6ea5 }));
      ring.position.set(p[0], p[1], p[2]); ring.rotation.x = Math.PI / 2; highlights.add(ring);
    }
  }
  if (st.winCells) {
    const A = new THREE.Vector3(...ballPos(...decode(st.winCells[0])));
    const B = new THREE.Vector3(...ballPos(...decode(st.winCells[3])));
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, A.distanceTo(B), 12),
      new THREE.MeshBasicMaterial({ color: 0xd8920f }));
    tube.position.copy(A).add(B).multiplyScalar(0.5);
    tube.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), B.clone().sub(A).normalize());
    highlights.add(tube);
  }
  if (game.showThreat && !st.winCells) {
    st.threats.forEach((i) => {
      const p = ballPos(...decode(i));
      const g = new THREE.Mesh(new THREE.SphereGeometry(RB * 0.92, 16, 12),
        new THREE.MeshBasicMaterial({ color: 0x2f8f83, transparent: true, opacity: 0.42 }));
      g.position.set(p[0], p[1], p[2]); highlights.add(g);
    });
  }
  // 詰み手順 (PV) を半透明の紫マーカーで盤上に重ねる。
  (st.matePv || []).forEach((i, k) => {
    const p = ballPos(...decode(i));
    const g = new THREE.Mesh(new THREE.SphereGeometry(RB * 0.7, 16, 12),
      new THREE.MeshBasicMaterial({ color: k % 2 === 0 ? 0x7a5cc7 : 0xb39ddb, transparent: true, opacity: 0.5 }));
    g.position.set(p[0], p[1], p[2]); highlights.add(g);
  });
}

/* ====== スライス (2D フォールバック / 併用) ====== */
function renderSlices(st) {
  const el = $("slices"); el.innerHTML = "";
  const winSet = new Set(st.winCells || []);
  const mateOrder = new Map((st.matePv || []).map((i, k) => [i, k + 1]));
  for (let z = 0; z < 4; z++) {
    const slice = document.createElement("div"); slice.className = "slice";
    const zlabel = z === 0 ? "段1（底）" : z === 3 ? "段4（上）" : "段" + (z + 1);
    slice.innerHTML = `<h2>${zlabel}<span>z=${z}</span></h2>`;
    const files = document.createElement("div"); files.className = "files";
    files.innerHTML = "<div></div>" + "abcd".split("").map((f) => `<div>${f}</div>`).join("");
    slice.appendChild(files);
    for (let y = 3; y >= 0; y--) {
      const row = document.createElement("div"); row.className = "grid-row";
      row.innerHTML = `<div class="rank">${y + 1}</div>`;
      for (let x = 0; x < 4; x++) {
        const ci = cellIdx(x, y, z); const bit = 1n << BigInt(ci);
        const v = (st.b0 & bit) ? 1 : (st.b1 & bit) ? 2 : 0;
        const cell = document.createElement("div"); cell.className = "cell";
        if (winSet.has(ci)) cell.classList.add("win");
        else if (ci === st.lastIdx) cell.classList.add("last");
        else if (game.showThreat && st.threats.has(ci)) cell.classList.add("threat");
        if (v === 0 && mateOrder.has(ci)) cell.classList.add("mate");
        if (v === 0) {
          cell.innerHTML = mateOrder.has(ci)
            ? `<span class="mateno">${mateOrder.get(ci)}</span>` : '<span class="peg"></span>';
        } else cell.innerHTML = `<span class="bead ${v === 1 ? "p1" : "p2"}${ci === st.lastIdx ? " fresh" : ""}"></span>`;
        row.appendChild(cell);
      }
      slice.appendChild(row);
    }
    el.appendChild(slice);
  }
}

/* ====== ドロップ用 4x4 グリッド (確実な入力手段) ====== */
function renderDropGrid(st) {
  const el = $("dropGrid"); el.innerHTML = "";
  const playable = st.winner === null && !st.full && st.turn === game.humanSide && !game.thinking;
  for (let y = 3; y >= 0; y--) {
    for (let x = 0; x < 4; x++) {
      const c = y * 4 + x;
      const b = document.createElement("button");
      b.className = "drop";
      b.innerHTML = `<span class="dn">${colName(c)}</span><span class="dh">${st.heights[c]}/4</span>`;
      const hint = game.analysis && game.analysis.move === c;
      if (hint) b.classList.add("hint");
      if (game.mate && (game.mate.status === 1 || game.mate.status === 2) && game.mate.move === c) {
        b.classList.add("mate");
      }
      b.disabled = !playable || st.heights[c] >= 4;
      b.addEventListener("click", () => drop(c));
      el.appendChild(b);
    }
  }
}

/* ====== 評価表示 ====== */
function fmtEval(score, turn) {
  const s = turn === 0 ? score : -score;     // 先手視点
  if (s > MATE_LO) return { txt: "先手 勝ち（読み切り）", cls: "p1" };
  if (s < -MATE_LO) return { txt: "後手 勝ち（読み切り）", cls: "p2" };
  const lead = s >= 0 ? "先手" : "後手";
  return { txt: `${lead}有利  (${s >= 0 ? "+" : ""}${s})`, cls: s >= 0 ? "p1" : "p2" };
}

function fmtMate(m) {
  const side = (t) => t === 0 ? "先手（黒）" : "後手（生成り）";
  const pv = m.pv.length ? m.pv.map(colName).join(" → ") : "";
  if (m.status === 1) return { txt: `${side(m.turn)}に ${m.plies}手で詰みあり`, sub: pv, cls: m.turn === 0 ? "p1" : "p2" };
  if (m.status === 2) return { txt: `${side(m.turn)}は ${m.plies}手で詰まされる`, sub: pv, cls: m.turn === 0 ? "p2" : "p1" };
  if (m.status === 3) return { txt: "双方最善で引き分け（読み切り）", sub: "", cls: "" };
  return { txt: `${SOLVE_MAX}手以内に強制詰みなし`, sub: "", cls: "" };
}

/* ====== メイン描画 ====== */
function render() {
  const st = replay(game.history);
  // 詰み探索結果の PV を現局面のセル列に変換 (win/loss のみ; 盤上にハイライト)。
  st.matePv = (game.mate && (game.mate.status === 1 || game.mate.status === 2) && game.mate.pv.length)
    ? pvCells(st.heights, game.mate.pv) : [];

  if (game.viewMode === "3d") update3D(st);
  else renderSlices(st);
  renderDropGrid(st);

  // ステータス
  const statusEl = $("status"), evalEl = $("evalLine"), hintEl = $("hintLine");
  $("counter").textContent = `手 ${game.history.length} / 64`;
  $("btnUndo").disabled = game.history.length === 0 || game.thinking;
  $("btnSolve").disabled = game.thinking || game.solving || st.winner !== null || st.full;

  const sideName = (p) => p === 0 ? "先手（黒）" : "後手（生成り）";
  if (st.winner !== null) {
    const w = st.winner;
    statusEl.innerHTML = `<span class="badge ${w === 0 ? "p1" : "p2"}">${sideName(w)}の勝ち</span>` +
      (w === game.humanSide ? "  あなたの勝ちです！" : "  エンジンの勝ちです。");
  } else if (st.full) {
    statusEl.innerHTML = `<span class="badge">引き分け</span>`;
  } else if (game.thinking) {
    statusEl.innerHTML = `<span class="thinking">エンジン思考中…</span>`;
  } else if (st.turn === game.humanSide) {
    statusEl.innerHTML = `<span class="turn"><span class="dot ${st.turn === 0 ? "p1" : "p2"}"></span>あなた（${sideName(st.turn)}）の番 — 柱を選んでください</span>`;
  } else {
    statusEl.innerHTML = `<span class="turn"><span class="dot ${st.turn === 0 ? "p1" : "p2"}"></span>エンジン（${sideName(st.turn)}）の番</span>`;
  }

  // 評価・ヒント
  if (game.analysis && st.winner === null && !st.full) {
    const e = fmtEval(game.analysis.score, st.turn);
    const tag = game.analysis.book ? ` <span class="booktag">定石</span>` : "";
    evalEl.innerHTML = `評価: <b class="${e.cls}">${e.txt}</b>${tag}`;
    if (st.turn === game.humanSide && game.analysis.move >= 0) {
      const label = game.analysis.book ? "定石の手" : "エンジンの推奨手";
      hintEl.textContent = `${label}: ${colName(game.analysis.move)}`;
    } else hintEl.textContent = "";
  } else {
    evalEl.textContent = ""; hintEl.textContent = "";
  }

  // 詰み探索の表示
  const mateEl = $("mateLine");
  if (game.solving) {
    mateEl.innerHTML = `<span class="thinking">詰み探索中…</span>`;
  } else if (game.mate) {
    const f = fmtMate(game.mate);
    mateEl.innerHTML = `詰み探索: <b class="${f.cls}">${f.txt}</b>` +
      (f.sub ? `<span class="matePv">${f.sub}</span>` : "");
  } else {
    mateEl.textContent = "";
  }

  // 手順
  const ml = $("moveList"); ml.innerHTML = "";
  game.history.forEach((c, i) => {
    const sp = document.createElement("span"); sp.className = "mv " + (i % 2 === 0 ? "p1" : "p2");
    sp.textContent = `${i + 1}.${colName(c)}`;
    ml.appendChild(sp);
  });
}

/* ====== ビュー切替 ====== */
function setView(mode) {
  if (mode === "3d" && has3D && !gl3dFailed) { init3D(); }   // 失敗したら gl3dFailed が立つ
  if (mode === "3d" && (!has3D || gl3dFailed)) mode = "slice";
  game.viewMode = mode === "3d" ? "3d" : "slice";
  $("view3d").classList.toggle("active", game.viewMode === "3d");
  $("viewSlice").classList.toggle("active", game.viewMode === "slice");
  $("view3d").disabled = !has3D || gl3dFailed;
  $("board3d").style.display = game.viewMode === "3d" ? "block" : "none";
  $("slices").style.display = game.viewMode === "slice" ? "flex" : "none";
  if (game.viewMode === "3d") { resize3D(); }
  render();
}

/* ====== 配線 ====== */
function wire() {
  $("btnNewBlack").addEventListener("click", () => newGame(0));
  $("btnNewWhite").addEventListener("click", () => newGame(1));
  $("btnUndo").addEventListener("click", undo);
  $("btnSolve").addEventListener("click", requestSolve);
  $("depthSel").addEventListener("change", (e) => { game.depth = parseInt(e.target.value, 10); });
  $("threatToggle").addEventListener("change", (e) => { game.showThreat = e.target.checked; render(); });
  $("view3d").addEventListener("click", () => setView("3d"));
  $("viewSlice").addEventListener("click", () => setView("slice"));
  window.addEventListener("resize", resize3D);
  if (!has3D) { $("view3d").disabled = true; $("view3d").title = "この環境では3Dを読み込めませんでした"; }
}

wire();
setView(has3D ? "3d" : "slice");
newGame(0);
