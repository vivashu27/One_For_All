"use strict";
/* Exercises the REAL browser flow: init -> wireEvents -> loadGraphs -> switchGraph -> deleteGraph,
   with fetch stubbed. This is the layer the server-side suites cannot reach. */
const fs = require("fs");
const P = require("path").resolve(__dirname, "..", "web/static/app.js");
let src = fs.readFileSync(P, "utf8").replace(/\n\s*init\(\);\s*$/, "\n");
src += "\n;return { state, sim, init, switchGraph, deleteGraph, loadGraphs };";

function mkEl(tag) {
  const L = {}, kids = [], cls = new Set();
  const el = {
    tag, dataset: {}, children: kids, clientWidth: 1000, clientHeight: 600,
    textContent: "", disabled: false, title: "", value: "", _html: "",
    set innerHTML(v) { el._html = String(v); kids.length = 0; }, get innerHTML() { return el._html; },
    setAttribute(k, v) { if (k === "class") { cls.clear(); String(v).split(/\s+/).forEach(c => c && cls.add(c)); } },
    removeAttribute() {}, appendChild(c) { kids.push(c); return c; },
    addEventListener(t, fn) { (L[t] = L[t] || []).push(fn); },
    removeEventListener(t, fn) { if (L[t]) L[t] = L[t].filter(f => f !== fn); },
    setPointerCapture() {}, releasePointerCapture() {},
    querySelector() { return mkEl("c"); }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 600 }; },
    classList: { toggle: (c, on) => { on ? cls.add(c) : cls.delete(c); }, add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c) },
    fire(t, ev) { (L[t] || []).forEach(f => f(ev)); },
    _handlers: L,
  };
  return el;
}
const cache = {};
const document = {
  createElementNS: (_n, t) => mkEl(t), createElement: t => mkEl(t),
  querySelector: s => (cache[s] = cache[s] || mkEl("sel" + s)),
  querySelectorAll: () => [],
};
const $ = s => document.querySelector(s);
const requestAnimationFrame = () => {};           // skip the physics loop here
const location = { search: "" };

/* ---- fetch stub ---- */
const calls = [];
let GRAPHS = [
  { name: "default", dir: "/d", nodes: 52, current: true, deletable: false },
  { name: "web3", dir: "/w", nodes: 3, current: false, deletable: true },
];
let deleted = null;
function jsonRes(obj) {
  return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => obj, text: async () => "" };
}
const fetch = async (url, opts = {}) => {
  calls.push((opts.method || "GET") + " " + url);
  const u = new URL(url, "http://x");
  const p = u.pathname, g = u.searchParams.get("graph");
  if (p === "/api/graphs") return jsonRes({ graphs: GRAPHS, current: "default" });
  if (p === "/api/graph") {
    const n = g === "web3" ? 3 : 52;
    return jsonRes({ nodes: Array.from({ length: n }, (_, i) => ({
      id: `${g || "default"}-n${i}`, title: `N${i}`, type: "technique", tags: [], confidence: "low",
      reinforced: 0, summary: "", related: [], enabled: true, created: "2026-01-01", updated: "2026-01-01" })),
      edges: [], count: n });
  }
  if (p === "/api/journal") return jsonRes({ text: "# J" });
  if (p === "/api/graph" ) return jsonRes({});
  if (p.startsWith("/api/graph") && (opts.method === "DELETE")) { deleted = g; return jsonRes({ ok: true, deleted: g, nodes_removed: 3 }); }
  return jsonRes({ ok: true });
};
const window = { addEventListener() {} };
let promptReply = "web3";
const prompt = () => promptReply;
const confirm = () => true;

const app = new Function("document", "requestAnimationFrame", "setTimeout", "location",
  "URLSearchParams", "console", "fetch", "prompt", "confirm", "URL", "window", src)
  (document, requestAnimationFrame, setTimeout, location, URLSearchParams, console, fetch, prompt, confirm, URL, window);
const { state } = app;

const out = [];
const ck = (n, c) => out.push([n, !!c]);
const flush = () => new Promise(r => setTimeout(r, 5));

(async () => {
  // state must separate DATA from NAME (the bug)
  ck("state.graph starts as a data object", state.graph && Array.isArray(state.graph.nodes));
  ck("state.graphName is a separate field", "graphName" in state && state.graphName === null);

  let threw = null;
  try { await app.init(); } catch (e) { threw = e; }
  await flush();
  ck("init() did not throw", threw === null);
  if (threw) console.log("    threw:", threw.message);

  // wireEvents must have run (it comes after renderLegend in init)
  ck("change listener wired on #graphsel", ($("#graphsel")._handlers.change || []).length === 1);
  ck("delete button wired", typeof $("#btn-del-graph").onclick === "function");

  // dropdown populated, current preselected
  ck("dropdown lists both graphs", $("#graphsel").innerHTML.includes("default (52)")
    && $("#graphsel").innerHTML.includes("web3 (3)"));
  ck("current graph selected", state.graphName === "default");
  ck("delete disabled for default", $("#btn-del-graph").disabled === true);
  ck("graph data loaded (52 nodes)", state.graph.nodes.length === 52);

  // THE reported failure: switching via the dropdown
  calls.length = 0;
  $("#graphsel").fire("change", { target: { value: "web3" } });
  await flush();
  ck("switch set graphName", state.graphName === "web3");
  ck("switch refetched with ?graph=web3", calls.some(c => c.includes("/api/graph?graph=web3")));
  ck("switched data loaded (3 nodes)", state.graph.nodes.length === 3);
  ck("no [object Object] in any URL", !calls.some(c => c.includes("object%20Object") || c.includes("[object")));
  ck("delete enabled for web3", $("#btn-del-graph").disabled === false);

  // delete flow asks for typed confirmation and sends confirm=
  calls.length = 0; promptReply = "web3";
  await app.deleteGraph(); await flush();
  ck("delete sent confirm=web3", calls.some(c => c.startsWith("DELETE") && c.includes("confirm=web3")));

  // a mismatched typed name must NOT send a delete
  calls.length = 0; state.graphName = "web3"; promptReply = "wrong-name";
  await app.deleteGraph(); await flush();
  ck("mismatched confirmation aborts", !calls.some(c => c.startsWith("DELETE")));

  let all = true;
  for (const [n, c] of out) { console.log(`  [${c ? "PASS" : "FAIL"}] ${n}`); all = all && c; }
  console.log(all ? "ALLPASS" : "SOME-FAILED");
  process.exit(all ? 0 : 1);
})();
