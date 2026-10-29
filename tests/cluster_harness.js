"use strict";
const fs = require("fs");
const P = require("path").resolve(__dirname, "..", "web/static/app.js");
let src = fs.readFileSync(P, "utf8").replace(/\n\s*init\(\);\s*$/, "\n");
src += "\n;return { sim, state, buildGraphDOM, toggleType, setAllTypes };";

let paints = 0;
function mkEl(tag) {
  const L = {}, kids = [], cls = new Set();
  const el = {
    tag, dataset: {}, children: kids, clientWidth: 1000, clientHeight: 600, textContent: "",
    set innerHTML(_) { kids.length = 0; }, get innerHTML() { return ""; },
    setAttribute(k, v) { if (k === "class") { cls.clear(); String(v).split(/\s+/).forEach(c => c && cls.add(c)); } if (k === "transform") paints++; },
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
const document = { createElementNS: (_n, t) => mkEl(t), createElement: t => mkEl(t), querySelector: s => (cache[s] = cache[s] || mkEl("sel")) };
let q = [];
const requestAnimationFrame = cb => q.push(cb);
const drain = (lim = 6000) => { let n = 0; while (q.length && n < lim) { q.shift()(); n++; } return n; };
const location = { search: "" };

const app = new Function("document", "requestAnimationFrame", "setTimeout", "location", "URLSearchParams", "console", src)
  (document, requestAnimationFrame, setTimeout, location, URLSearchParams, console);
const { sim, state } = app;

// 3 types, several nodes each, plus cross-type related links (the thing that used to clump)
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
const real = () => sim.nodes.filter(n => !n.hub);
const hubs = () => sim.nodes.filter(n => n.hub);

app.buildGraphDOM();
ck("3 hubs created (one per visible type)", hubs().length === 3);
ck("hub ids/types correct", hubs().map(h => h.type).sort().join() === "reference,technique,tool");
ck("9 real nodes kept", real().length === 9);
ck("hubs are anchored (fixed)", hubs().every(h => h.fixed === true));
const hubPos = hubs().map(h => `${h.x.toFixed(1)},${h.y.toFixed(1)}`).join("|");
ck("one spoke per real node", sim.edges.filter(e => e.cls.includes("spoke")).length === 9);
ck("real links preserved", sim.edges.filter(e => e.cls === "edge").length === 3);
ck("spokes point to own-type hub", sim.edges.filter(e => e.cls.includes("spoke"))
  .every(e => e.t === "__hub__" + sim.byId[e.s].type));

drain();
ck("settled", sim.looping === false);
ck("hubs never moved", hubs().map(h => `${h.x.toFixed(1)},${h.y.toFixed(1)}`).join("|") === hubPos);

// THE point of the change: each node must end up nearest its OWN category hub
const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
const misplaced = real().filter(n => {
  const own = sim.byId["__hub__" + n.type];
  return hubs().some(h => h.type !== n.type && d(n, h) < d(n, own));
});
ck("every node nearest its own hub (segregated)", misplaced.length === 0);
if (misplaced.length) console.log("    misplaced:", misplaced.map(n => n.id + "/" + n.type).join(" "));

// clusters are actually separated: max intra-cluster radius < min hub-to-hub distance
const maxR = Math.max(...real().map(n => d(n, sim.byId["__hub__" + n.type])));
let minHub = Infinity;
hubs().forEach((a, i) => hubs().slice(i + 1).forEach(b => { minHub = Math.min(minHub, d(a, b)); }));
ck(`clusters separated (maxRadius ${maxR.toFixed(0)} < hubGap ${minHub.toFixed(0)})`, maxR < minHub);

// filters still work with hubs present
app.toggleType("tool"); drain();
ck("filter hides a type's nodes AND its hub", real().length === 6 && hubs().length === 2 && !sim.byId["__hub__tool"]);
app.toggleType("tool"); drain();
ck("filter restored", real().length === 9 && hubs().length === 3);
app.setAllTypes(false); drain();
ck("None → no nodes and no hubs", sim.nodes.length === 0);
app.setAllTypes(true); drain();
ck("All → restored", real().length === 9 && hubs().length === 3);

// drag on a real node still works after settle
const g = sim.els["t1"], before = paints;
g.fire("pointerdown", { clientX: 10, clientY: 10, pointerId: 1, preventDefault() {} });
g.fire("pointermove", { clientX: 500, clientY: 320, pointerId: 1 });
ck("drag still follows cursor + repaints", Math.abs(sim.byId["t1"].x - 500) < 1 && paints > before);
g.fire("pointerup", { clientX: 500, clientY: 320, pointerId: 1 });
ck("released node unpinned", sim.byId["t1"].fixed === false);
drain();

let all = true;
for (const [n, c] of out) { console.log(`  [${c ? "PASS" : "FAIL"}] ${n}`); all = all && c; }
console.log(all ? "ALLPASS" : "SOME-FAILED");
process.exit(all ? 0 : 1);
