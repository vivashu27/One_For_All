"use strict";
/* Graph view: static clustered layout, drag-to-arrange, saved positions, Tidy. Runs app.js
   headlessly with a stub DOM and fetch. */
const fs = require("fs");
const P = require("path").resolve(__dirname, "..", "web/static/app.js");
let src = fs.readFileSync(P, "utf8").replace(/\n\s*init\(\);\s*$/, "\n");
src += "\n;return { scene, state, buildGraphDOM, toggleType, setAllTypes, tidyGraph, fitGraph, wireGraphView };";

function mkEl(tag) {
  const L = {}, kids = [], cls = new Set(), attrs = {};
  const el = {
    tag, dataset: {}, children: kids, clientWidth: 1000, clientHeight: 600, textContent: "", hidden: false, attrs,
    set innerHTML(_) { kids.length = 0; }, get innerHTML() { return ""; },
    setAttribute(k, v) { attrs[k] = String(v); if (k === "class") { cls.clear(); String(v).split(/\s+/).forEach(c => c && cls.add(c)); } },
    getAttribute(k) { return attrs[k]; },
    removeAttribute() {}, appendChild(c) { kids.push(c); return c; },
    addEventListener(t, fn) { (L[t] = L[t] || []).push(fn); },
    removeEventListener(t, fn) { if (L[t]) L[t] = L[t].filter(f => f !== fn); },
    setPointerCapture() {}, releasePointerCapture() {},
    querySelector() { return mkEl("c"); }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 600 }; },
    classList: { toggle: (c, on) => { on ? cls.add(c) : cls.delete(c); }, add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) },
    fire(t, ev) { (L[t] || []).forEach(f => f(ev)); },
  };
  return el;
}
const cache = {};
const document = { createElementNS: (_n, t) => mkEl(t), createElement: t => mkEl(t), querySelector: s => (cache[s] = cache[s] || mkEl("sel")), querySelectorAll: () => [] };
let q = [];
const requestAnimationFrame = cb => q.push(cb);
const drain = (lim = 6000) => { let n = 0; while (q.length && n < lim) { q.shift()(performance.now() + 1e6); n++; } return n; };
const location = { search: "" };
const puts = [];
const fetch = async (url, opts = {}) => {
  if (opts.method === "PUT") puts.push({ url, body: JSON.parse(opts.body) });
  return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({ ok: true }) };
};
const flush = () => new Promise(r => setTimeout(r, 5));
let confirmAnswer = true;
globalThis.confirm = () => confirmAnswer;

const app = new Function("document", "requestAnimationFrame", "setTimeout", "location", "URLSearchParams", "console", "fetch", src)
  (document, requestAnimationFrame, setTimeout, location, URLSearchParams, console, fetch);
const { scene, state } = app;

// 3 types, several nodes each, plus cross-type related links
const mk = (id, type, related = []) => ({ id, title: id.toUpperCase(), type, tags: [], confidence: "medium", reinforced: 1, summary: "", related, enabled: true });
state.graph = {
  nodes: [
    mk("t1", "technique", ["o1"]), mk("t2", "technique", ["t1"]), mk("t3", "technique"), mk("t4", "technique"),
    mk("o1", "tool", ["t1"]), mk("o2", "tool"), mk("o3", "tool"),
    mk("r1", "reference", ["t2"]), mk("r2", "reference"),
  ],
  edges: [{ source: "t1", target: "o1" }, { source: "t1", target: "t2" }, { source: "t2", target: "r1" }],
};

const out = [];
const ck = (n, c) => out.push([n, !!c]);
const real = () => scene.nodes.filter(n => !n.hub);
const hubs = () => scene.nodes.filter(n => n.hub);
const at = id => `${scene.byId[id].x.toFixed(1)},${scene.byId[id].y.toFixed(1)}`;
const snap = () => scene.nodes.map(n => n.id + "@" + at(n.id)).sort().join("|");
const down = (g, x, y) => g.fire("pointerdown", { clientX: x, clientY: y, pointerId: 1, button: 0, preventDefault() {} });
const move = (g, x, y) => g.fire("pointermove", { clientX: x, clientY: y, pointerId: 1 });
const up = (g, x, y) => g.fire("pointerup", { clientX: x, clientY: y, pointerId: 1 });

(async () => {
  app.wireGraphView();
  app.buildGraphDOM();
  ck("3 hubs created (one per visible type)", hubs().length === 3);
  ck("hub ids/types correct", hubs().map(h => h.type).sort().join() === "reference,technique,tool");
  ck("9 real nodes kept", real().length === 9);
  ck("one spoke per real node", scene.edges.filter(e => e.cls.includes("spoke")).length === 9);
  ck("real links preserved", scene.edges.filter(e => e.cls === "edge").length === 3);
  ck("spokes point to own-type hub", scene.edges.filter(e => e.cls.includes("spoke"))
    .every(e => e.t === "__hub__" + scene.byId[e.s].type));
  ck("static: no animation loop after build", q.length === 0);
  await flush();
  ck("first view saves the initial layout once", puts.length === 1 && Object.keys(puts[0].body.positions).length === 9 + 3);

  // tree shape: every node hangs below and right of its OWN hub; no two nodes overlap
  const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const under = n => { const h = scene.byId["__hub__" + n.type]; return n.x > h.x && n.y > h.y; };
  ck("every node hangs below-right of its own hub", real().every(under));
  let minGap = Infinity;
  scene.nodes.forEach((a, i) => scene.nodes.slice(i + 1).forEach(b => { minGap = Math.min(minGap, d(a, b)); }));
  ck(`no overlapping nodes (min gap ${minGap.toFixed(0)} ≥ 24)`, minGap >= 24);
  // clusters don't overlap: bounding boxes of hub+children are disjoint
  const box = t => { const ns = scene.nodes.filter(n => n.type === t);
    return [Math.min(...ns.map(n => n.x)), Math.min(...ns.map(n => n.y)), Math.max(...ns.map(n => n.x)), Math.max(...ns.map(n => n.y))]; };
  const bx = ["technique", "tool", "reference"].map(box);
  const hit = (a, b) => a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
  ck("cluster boxes are disjoint", !hit(bx[0], bx[1]) && !hit(bx[0], bx[2]) && !hit(bx[1], bx[2]));

  // stability: rebuilding and filtering never reshuffle
  const base = snap();
  app.buildGraphDOM();
  ck("rebuild keeps every position", snap() === base);
  const o2 = at("o2");
  app.toggleType("technique");
  ck("filter hides a type's nodes AND its hub", real().length === 5 && hubs().length === 2 && !scene.byId["__hub__technique"]);
  ck("filtering does not move the others", at("o2") === o2);
  app.toggleType("technique");
  ck("filter restored at the same positions", snap() === base);
  app.setAllTypes(false);
  ck("None → no nodes and no hubs", scene.nodes.length === 0);
  app.setAllTypes(true);
  ck("All → restored", snap() === base);
  state.graph.nodes[0].phase = ["recon", "hunt"]; state.graph.nodes[4].phase = ["recon"];
  state.showPhases = true; app.buildGraphDOM();
  ck("phases overlay adds virtual phase hubs", ["recon", "hunt", "all"].every(p => scene.byId["__hub__phase:" + p]));
  ck("phase spine links recon → hunt", scene.edges.some(e => e.cls.includes("phase-spine") && e.s === "__hub__phase:recon" && e.t === "__hub__phase:hunt"));
  ck("each phase of a node gets a spoke", scene.edges.filter(e => e.cls === "edge phase" && e.s === "t1").length === 2);
  ck("overlay does not move real nodes", real().every(n => !base.includes(n.id + "@") || base.includes(n.id + "@" + at(n.id))));
  state.showPhases = false; app.buildGraphDOM();
  ck("overlay off removes phase hubs", !scene.nodes.some(n => n.phaseHub));
  await flush();
  ck("rebuilds and filters don't save again", puts.length === 1);

  // drag a node: it follows the pointer, stays where dropped, and the layout is saved
  const t1 = scene.byId["t1"], x0 = t1.x, y0 = t1.y;
  down(scene.els["t1"], 100, 100); move(scene.els["t1"], 150, 130);
  ck("drag follows the pointer", Math.abs(scene.byId["t1"].x - (x0 + 50)) < 0.5 && Math.abs(scene.byId["t1"].y - (y0 + 30)) < 0.5);
  ck("dragging moves nothing else", at("t2") === base.match(/t2@([^|]+)/)[1]);
  up(scene.els["t1"], 150, 130); drain(); await flush();
  ck("dropped node stays put (no spring back)", Math.abs(scene.byId["t1"].x - (x0 + 50)) < 0.5);
  const saved = puts.length && puts[puts.length - 1];
  ck("drop saves only the moved node (other tabs' positions survive)", saved && saved.url.startsWith("/api/layout") &&
    Math.abs(saved.body.positions.t1[0] - (x0 + 50)) < 0.5 && Object.keys(saved.body.positions).join() === "t1");
  app.buildGraphDOM();
  ck("moved node survives a rebuild", Math.abs(scene.byId["t1"].x - (x0 + 50)) < 0.5);

  // a click (no movement) does not save
  const n = puts.length;
  down(scene.els["o3"], 10, 10); up(scene.els["o3"], 10, 10); await flush();
  ck("click without moving does not save", puts.length === n);

  // drag a hub: its whole cluster moves with it, others stay
  const hr = scene.byId["__hub__reference"], r1 = scene.byId["r1"], r1x = r1.x, hx = hr.x, o1 = at("o1");
  down(scene.els["__hub__reference"], 0, 0); move(scene.els["__hub__reference"], 40, -20); up(scene.els["__hub__reference"], 40, -20);
  await flush();
  ck("hub drag moves the hub", Math.abs(scene.byId["__hub__reference"].x - (hx + 40)) < 0.5);
  ck("hub drag carries its cluster", Math.abs(scene.byId["r1"].x - (r1x + 40)) < 0.5);
  ck("hub drag leaves other clusters", at("o1") === o1);
  ck("hub drag saves the hub and its cluster only", Object.keys(puts[puts.length - 1].body.positions).sort().join() === "__hub__reference,r1,r2");

  // saved positions from layout.json are honoured; a new node lands beside its (moved) hub
  state.pos = { o1: [5, 5] };
  state.graph.nodes.push(mk("o4", "tool"));
  app.buildGraphDOM();
  ck("saved position honoured", scene.byId["o1"].x === 5 && scene.byId["o1"].y === 5);
  ck("new node lands under its own (moved) hub", under(scene.byId["o4"]) &&
    d(scene.byId["o4"], scene.byId["__hub__tool"]) < 200);
  ck("new node overlaps nothing", scene.nodes.every(m => m.id === "o4" || d(m, scene.byId["o4"]) >= 24));
  // a node the user dragged into the slot a new node would take is not covered by it
  state.graph.nodes.push(mk("o5", "tool")); app.buildGraphDOM();
  const slot = state.pos.o5.slice();
  state.graph.nodes.pop(); delete state.pos.o5;
  state.pos.o2 = slot.slice();
  state.graph.nodes.push(mk("o5", "tool")); app.buildGraphDOM();
  ck("new node steps aside from a hand-placed node in its slot", d(scene.byId["o5"], scene.byId["o2"]) >= 24);
  ck("the hand-placed node is not moved", scene.byId["o2"].x === slot[0] && scene.byId["o2"].y === slot[1]);

  // zoom and pan change only the view, survive a rebuild, and Fit returns to the automatic view
  const svg = document.querySelector("#graph"), vb = () => svg.getAttribute("viewBox");
  const fitted = vb(), keep = snap();
  svg.fire("wheel", { clientX: 500, clientY: 300, deltaY: -300, preventDefault() {} });
  const zw = Number(vb().split(" ")[2]), fw = Number(fitted.split(" ")[2]);
  ck("wheel up zooms in around the pointer", zw < fw);
  const z = vb();
  svg.fire("pointerdown", { target: svg, clientX: 100, clientY: 100, pointerId: 2, button: 0, preventDefault() {} });
  svg.fire("pointermove", { clientX: 160, clientY: 100, pointerId: 2 });
  svg.fire("pointerup", { clientX: 160, clientY: 100, pointerId: 2 });
  ck("dragging the background pans", Number(vb().split(" ")[0]) < Number(z.split(" ")[0]));
  ck("zoom and pan never move nodes", snap() === keep);
  const panned = vb();
  app.toggleType("tool"); app.toggleType("tool");
  ck("view survives filtering", vb() === panned);
  app.fitGraph();
  ck("Fit returns to the fitted view", vb() === fitted);

  // Tidy overwrites every hand-placed position, so it asks first; declining changes nothing
  const before = snap(), nPuts = puts.length;
  confirmAnswer = false; app.tidyGraph(); drain(); await flush(); confirmAnswer = true;
  ck("declined Tidy moves nothing and saves nothing", snap() === before && puts.length === nPuts);

  // Tidy: back to the clean layout, saved, settles without a physics loop
  app.tidyGraph(); drain(); await flush();
  ck("tidy restores non-overlapping clusters", (() => { let m = Infinity;
    scene.nodes.forEach((a, i) => scene.nodes.slice(i + 1).forEach(b => { m = Math.min(m, d(a, b)); })); return m >= 24; })());
  ck("tidy saves the layout", puts.length && Object.keys(puts[puts.length - 1].body.positions).length === 11 + 3);
  ck("tidy animation finishes", q.length === 0);

  let all = true;
  for (const [n, c] of out) { console.log(`  [${c ? "PASS" : "FAIL"}] ${n}`); all = all && c; }
  console.log(all ? "ALLPASS" : "SOME-FAILED");
  process.exit(all ? 0 : 1);
})();
