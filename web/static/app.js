"use strict";
/* Bug Bounty Knowledge Graph — offline, dependency-free UI */

const TOKEN = new URLSearchParams(location.search).get("token") || "";
const SVGNS = "http://www.w3.org/2000/svg";
const TYPE_COLORS = {
  technique: "#46b4ff", tool: "#c084fc", reference: "#ffd166", lesson: "#3fd07f",
  workflow: "#ff9f68", reporting: "#f472b6", "vuln-class": "#ff6b6b",
};
const TYPE_LABEL = {
  technique: "Techniques", tool: "Tools", reference: "References", lesson: "Lessons",
  workflow: "Workflows", reporting: "Reporting", "vuln-class": "Vuln classes",
};
const TYPE_ORDER = ["vuln-class", "technique", "tool", "reference", "workflow", "reporting", "lesson"];

const state = {
  graph: { nodes: [], edges: [] },   // the loaded graph DATA (nodes/edges)
  graphName: null,                   // which graph is selected (null = the server's launch graph)
  selected: null, query: "", editing: false,
  sort: "type",          // type | az | newest | updated
  typeFilter: null,      // Set of visible types in the graph (null = all)
  hideDisabled: false,   // also hide disabled nodes in the graph
  pos: {},               // node/hub positions {id: [x, y]}, from the graph's layout.json
  posFor: undefined,     // which graph `pos` belongs to
  view: null,            // user zoom/pan view box; null = fit to the graph
};
const $ = (sel) => document.querySelector(sel);

/* ----------------------------- API ----------------------------- */
async function api(method, path, body) {
  const headers = {};
  if (TOKEN) headers["X-KB-Token"] = TOKEN;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let url = "/api" + path;
  if (state.graphName) url += (url.includes("?") ? "&" : "?") + "graph=" + encodeURIComponent(state.graphName);
  const res = await fetch(url, {
    method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || res.statusText);
  return data;
}
function status(msg, kind) {
  const el = $("#status");
  el.textContent = msg || "";
  el.className = "status" + (kind ? " " + kind : "");
  if (msg && kind === "ok") setTimeout(() => { if (el.textContent === msg) { el.textContent = ""; el.className = "status"; } }, 2500);
}

/* --------------------------- Sidebar --------------------------- */
function nodeItemEl(n) {
  const item = document.createElement("div");
  item.className = "node-item" + (state.selected === n.id ? " active" : "") + (n.enabled === false ? " off" : "");
  item.dataset.id = n.id;
  item.innerHTML =
    `<span class="dot" style="background:${TYPE_COLORS[n.type] || "#888"}"></span>` +
    `<span class="label">${escapeHtml(n.title)}</span>` +
    `<span class="rc" title="reinforced">${n.reinforced || 0}</span>` +
    `<button class="pw" title="${n.enabled === false ? "Enable" : "Disable"} this knowledge">⏻</button>`;
  item.querySelector(".label").onclick = () => openNode(n.id);
  item.querySelector(".dot").onclick = () => openNode(n.id);
  item.querySelector(".rc").onclick = () => openNode(n.id);
  item.querySelector(".pw").onclick = (e) => { e.stopPropagation(); toggleEnabled(n.id, n.enabled === false); };
  return item;
}
function renderSidebar() {
  const list = $("#nodelist");
  list.innerHTML = "";
  const q = state.query.toLowerCase();
  const nodes = state.graph.nodes.filter((n) => {
    if (!q) return true;
    return (n.title + " " + n.id + " " + (n.tags || []).join(" ") + " " + (n.summary || ""))
      .toLowerCase().includes(q);
  });
  const dis = state.graph.nodes.filter((n) => n.enabled === false).length;
  $("#kbcount").textContent =
    `${state.graph.nodes.length} nodes · ${state.graph.edges.length} links` + (dis ? ` · ${dis} off` : "");

  if (state.sort === "type") {
    const byType = {};
    nodes.forEach((n) => (byType[n.type] = byType[n.type] || []).push(n));
    const types = [...new Set([...TYPE_ORDER, ...Object.keys(byType)])];
    types.forEach((t) => {
      const group = (byType[t] || []).sort((a, b) => a.title.localeCompare(b.title));
      if (!group.length) return;
      const gt = document.createElement("div");
      gt.className = "group-title";
      gt.textContent = (TYPE_LABEL[t] || t) + " · " + group.length;
      list.appendChild(gt);
      group.forEach((n) => list.appendChild(nodeItemEl(n)));
    });
  } else {
    const sorted = nodes.slice();
    if (state.sort === "az") sorted.sort((a, b) => a.title.localeCompare(b.title));
    else if (state.sort === "newest") sorted.sort((a, b) => (b.created || "").localeCompare(a.created || "") || a.title.localeCompare(b.title));
    else if (state.sort === "updated") sorted.sort((a, b) => (b.updated || "").localeCompare(a.updated || "") || a.title.localeCompare(b.title));
    const labels = { az: "A → Z", newest: "Newest created", updated: "Recently updated" };
    const gt = document.createElement("div");
    gt.className = "group-title";
    gt.textContent = `${labels[state.sort]} · ${sorted.length}`;
    list.appendChild(gt);
    sorted.forEach((n) => list.appendChild(nodeItemEl(n)));
  }
  if (!nodes.length) list.innerHTML = '<div class="empty">No matching nodes.</div>';
}

/* ---------------------------- Graph ---------------------------- */
// Static layout: nothing moves unless the user drags it or presses Tidy. Positions live in
// state.pos ({id: [x, y]} in SVG units, saved per graph as layout.json) and the view box is
// fitted to them, so resizing or filtering never reshuffles the graph.
// what is drawn now: visible nodes + hubs, their SVG elements and edges; tween cancels a running Tidy glide
let scene = { nodes: [], byId: {}, els: {}, edges: [], edgeEls: [], tween: 0 };
const HUB = (t) => "__hub__" + t;
const ROW = 28, COL_PAD = 40, HUB_TOP = 26, GAP_X = 56, GAP_Y = 44, MAX_LABEL = 48;
function typeVisible(t) { return !state.typeFilter || state.typeFilter.has(t); }
function toggleType(t) {
  if (!state.typeFilter) state.typeFilter = new Set(state.graph.nodes.map((n) => n.type));
  if (state.typeFilter.has(t)) state.typeFilter.delete(t); else state.typeFilter.add(t);
  buildGraphDOM();
}
function setAllTypes(on) { state.typeFilter = on ? null : new Set(); buildGraphDOM(); }
function renderLegend() {
  const counts = {};
  state.graph.nodes.forEach((n) => (counts[n.type] = (counts[n.type] || 0) + 1));
  const leg = $("#legend");
  leg.innerHTML = graphTypes().map((t) => {
    const off = state.typeFilter && !state.typeFilter.has(t) ? " off" : "";
    return `<span class="leg${off}" data-type="${escapeHtml(t)}"><i style="background:${TYPE_COLORS[t] || "#888"}"></i>${TYPE_LABEL[t] || escapeHtml(t)}<span class="cnt">${counts[t]}</span></span>`;
  }).join("");
  leg.querySelectorAll(".leg").forEach((el) => (el.onclick = () => toggleType(el.dataset.type)));
}
function graphTypes() {
  const present = new Set(state.graph.nodes.map((n) => n.type));
  return [...new Set([...TYPE_ORDER, ...present])].filter((t) => present.has(t));
}
function hubLabel(t) {
  return `${TYPE_LABEL[t] || t} (${state.graph.nodes.filter((n) => n.type === t).length})`;
}
function nodeRadius(n) { return n.hub ? 9 : 6 + Math.min(4, n.reinforced || 0); }
function shortTitle(s) { s = String(s); return s.length > MAX_LABEL ? s.slice(0, MAX_LABEL - 1) + "…" : s; }
const textW = (s, px) => String(s).length * px * 0.5;    // estimate: layout runs before any text is measured
// label widths shared by Tidy and Fit; px must match .gnode text / .gnode.hub text in style.css
const nodeLabelW = (n) => textW(shortTitle(n.title), 10.5);
const hubLabelW = (t) => textW(hubLabel(t), 12.5);
function canvasSize() { const svg = $("#graph"); return [svg.clientWidth || 800, svg.clientHeight || 600]; }

/* Tidy layout: each type is a small tree (hub top-left, its nodes in columns below it, joined by
   elbow connectors) and the trees flow into rows shaped like the canvas. */
function tidyLayout(nodes, W, H) {
  const byType = {};
  nodes.forEach((n) => (byType[n.type] = byType[n.type] || []).push(n));
  const maxRows = Math.max(6, Math.ceil(Math.sqrt(nodes.length) * 1.4));
  const boxes = graphTypes().filter((t) => byType[t]).map((t) => {
    const kids = byType[t].slice().sort((a, b) => a.title.localeCompare(b.title));
    const rows = Math.min(kids.length, maxRows), cols = Math.ceil(kids.length / maxRows);
    const colW = Math.max(...kids.map(nodeLabelW)) + 46;
    const w = Math.max(COL_PAD + cols * colW, hubLabelW(t) + 24);
    return { t, kids, rows, colW, w, h: HUB_TOP + (rows + 1) * ROW };
  });
  const area = boxes.reduce((s, b) => s + (b.w + GAP_X) * (b.h + GAP_Y), 0);
  // small graphs spread across the canvas; large ones keep its aspect so the fit stays readable
  const flowW = Math.max(W - 80, Math.sqrt(area * (W / H)), ...boxes.map((b) => b.w));
  const pos = {};
  let x = 0, y = 0, rowH = 0;
  boxes.forEach((b) => {
    if (x > 0 && x + b.w > flowW) { x = 0; y += rowH + GAP_Y; rowH = 0; }
    const hx = x + 10, hy = y + HUB_TOP;
    pos[HUB(b.t)] = [hx, hy];
    b.kids.forEach((n, i) => {
      pos[n.id] = [hx + COL_PAD + Math.floor(i / b.rows) * b.colW, hy + (i % b.rows + 1) * ROW];
    });
    x += b.w + GAP_X; rowH = Math.max(rowH, b.h);
  });
  return pos;
}
// Give a position to every node and hub that has none (first visit, or nodes an agent added),
// next to its hub even if the user moved that hub, stepping down past any node already there.
// Saved positions are never touched. Returns the ids it placed.
function placeNodes(W, H) {
  const tidy = tidyLayout(state.graph.nodes, W, H);
  const added = [];
  graphTypes().forEach((t) => { if (!state.pos[HUB(t)]) { state.pos[HUB(t)] = tidy[HUB(t)]; added.push(HUB(t)); } });
  const taken = Object.values(state.pos);
  const busy = (x, y) => taken.some((p) => Math.abs(p[0] - x) < ROW && Math.abs(p[1] - y) < ROW);
  state.graph.nodes.forEach((n) => {
    if (state.pos[n.id]) return;
    const tidyHub = tidy[HUB(n.type)], hubPos = state.pos[HUB(n.type)];
    const x = tidy[n.id][0] + hubPos[0] - tidyHub[0];
    let y = tidy[n.id][1] + hubPos[1] - tidyHub[1];
    for (let i = 0; i < 500 && busy(x, y); i++) y += ROW;
    state.pos[n.id] = [x, y];
    taken.push(state.pos[n.id]);
    added.push(n.id);
  });
  return added;
}
function buildGraphDOM() {
  renderLegend();
  scene.tween++;   // a rebuild supersedes any running Tidy animation
  const svg = $("#graph");
  svg.innerHTML = "";
  const [W, H] = canvasSize();
  const added = placeNodes(W, H);
  const visible = state.graph.nodes.filter(
    (n) => typeVisible(n.type) && (!state.hideDisabled || n.enabled !== false)
  );
  const visibleIds = new Set(visible.map((n) => n.id));
  const hubs = graphTypes().filter((t) => visible.some((n) => n.type === t))
    .map((t) => ({ id: HUB(t), hub: true, type: t, title: hubLabel(t) }));
  scene.nodes = visible.map((n) => ({ ...n })).concat(hubs);
  scene.byId = {};
  scene.nodes.forEach((n) => {
    n.r = nodeRadius(n);
    [n.x, n.y] = state.pos[n.id];
    scene.byId[n.id] = n;
  });
  const gEdges = document.createElementNS(SVGNS, "g");
  const gNodes = document.createElementNS(SVGNS, "g");
  svg.appendChild(gEdges); svg.appendChild(gNodes);
  scene.edges = state.graph.edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => ({ s: e.source, t: e.target, cls: "edge" }))
    .concat(visible.map((n) => ({ s: n.id, t: HUB(n.type), cls: "edge spoke", spoke: true })));
  scene.edgeEls = scene.edges.map((e) => {
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("class", e.cls);
    p.dataset.s = e.s; p.dataset.t = e.t;
    gEdges.appendChild(p);
    return p;
  });
  scene.els = {};
  scene.nodes.forEach((n) => {
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "gnode" + (n.hub ? " hub" : "") + (n.enabled === false ? " off" : ""));
    g.dataset.id = n.id;
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("r", n.r);
    c.setAttribute("fill", TYPE_COLORS[n.type] || "#888");
    const label = document.createElementNS(SVGNS, "text");
    if (n.hub) { label.setAttribute("x", -n.r); label.setAttribute("y", -n.r - 8); }
    else { label.setAttribute("x", n.r + 6); label.setAttribute("y", 4); }
    label.textContent = n.hub ? n.title : shortTitle(n.title);
    const tt = document.createElementNS(SVGNS, "title");
    tt.textContent = n.hub ? `${n.title}: drag to move the whole cluster`
      : `${n.title} [${n.type}] · ${n.confidence}, reinforced ${n.reinforced}` + (n.enabled === false ? " (disabled)" : "");
    g.appendChild(c); g.appendChild(label); g.appendChild(tt);
    gNodes.appendChild(g);
    scene.els[n.id] = g;
    attachDrag(g, n);
    if (!n.hub) {
      g.addEventListener("mouseenter", () => highlightNeighbors(n.id, true));
      g.addEventListener("mouseleave", () => highlightNeighbors(n.id, false));
    }
  });
  if (state.view) setViewBox(state.view); else fitView(W, H);
  redraw();
  const empty = $("#graph-empty");
  empty.hidden = scene.nodes.length > 0;
  empty.textContent = state.graph.nodes.length
    ? "No nodes match the current filters. Choose All to show every type."
    : "This graph has no nodes yet. Use + New node to add the first one.";
  if (added.length) saveLayout(added);   // pin new arrivals so the next visit shows them in the same place
}
// View box around every position (hidden types included, so filtering never zooms), never
// magnified past 1:1, centred in the canvas.
function fitView(W, H) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const grow = (p, right) => {
    x0 = Math.min(x0, p[0] - 14); y0 = Math.min(y0, p[1] - 26);
    x1 = Math.max(x1, p[0] + right); y1 = Math.max(y1, p[1] + 14);
  };
  state.graph.nodes.forEach((n) => grow(state.pos[n.id], 22 + nodeLabelW(n)));
  graphTypes().forEach((t) => grow(state.pos[HUB(t)], hubLabelW(t)));
  if (x0 === Infinity) { x0 = 0; y0 = 0; x1 = W; y1 = H; }
  const pad = 28, bw = x1 - x0 + 2 * pad, bh = y1 - y0 + 2 * pad;
  const s = Math.max(1, bw / W, bh / H);
  const vw = W * s, vh = H * s;
  setViewBox([x0 - pad - (vw - bw) / 2, y0 - pad - (vh - bh) / 2, vw, vh]);
}
function setViewBox(vb) { scene.vb = vb; $("#graph").setAttribute("viewBox", vb.join(" ")); }
function fitGraph() {
  state.view = null;
  fitView(...canvasSize());
}
// Wheel zooms around the pointer; dragging empty canvas pans. Only the view moves, never a
// node, and the view is kept (state.view) until Fit, Tidy or a graph switch re-fits it.
function wireGraphView() {
  const svg = $("#graph");
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [x, y, w, h] = scene.vb, p = toSvgPoint(e);
    const [W] = canvasSize();
    const k = Math.min(Math.max(Math.exp(e.deltaY * 0.0015), (W * 0.25) / w), (W * 20) / w);
    state.view = [p.x - (p.x - x) * k, p.y - (p.y - y) * k, w * k, h * k];
    setViewBox(state.view);
  }, { passive: false });
  svg.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0 || (ev.target && ev.target.closest && ev.target.closest(".gnode"))) return;
    const [x, y, w, h] = scene.vb, sx = ev.clientX, sy = ev.clientY;
    const [W, H] = canvasSize(), s = Math.max(w / W, h / H);
    trackPointer(svg, ev, "panning", (e) => {
      state.view = [x - (e.clientX - sx) * s, y - (e.clientY - sy) * s, w, h];
      setViewBox(state.view);
    });
  });
}
// Follow one pointer on el until it is released: cls marks el meanwhile, onUp (optional) runs last.
function trackPointer(el, ev, cls, onMove, onUp) {
  try { el.setPointerCapture(ev.pointerId); } catch (_) {}
  el.classList.add(cls);
  const end = (e) => {
    ["pointermove", "pointerup", "pointercancel"].forEach((t, i) => el.removeEventListener(t, i ? end : onMove));
    try { el.releasePointerCapture(ev.pointerId); } catch (_) {}
    el.classList.remove(cls);
    if (onUp) onUp(e);
  };
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}
function edgePath(e) {
  const a = scene.byId[e.s], b = scene.byId[e.t];
  if (e.spoke) {   // elbow: out of the hub, down the column's trunk, into the node
    return `M${b.x + b.r},${b.y}H${a.x - 16}V${a.y}H${a.x - a.r}`;
  }
  // related link: a shallow arc, so links read apart from the rectilinear tree
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y;
  return `M${a.x},${a.y}Q${mx - dy * 0.18},${my + dx * 0.18} ${b.x},${b.y}`;
}
function redraw() {
  scene.edgeEls.forEach((el, i) => el.setAttribute("d", edgePath(scene.edges[i])));
  scene.nodes.forEach((n) => scene.els[n.id].setAttribute("transform", `translate(${n.x},${n.y})`));
}
function toSvgPoint(ev) {
  const svg = $("#graph");
  if (svg.getScreenCTM && svg.createSVGPoint) {
    const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
    return p.matrixTransform(svg.getScreenCTM().inverse());
  }
  return { x: ev.clientX, y: ev.clientY };   // stub DOM in tests: 1:1
}
function settleTween() {   // jump a running Tidy animation to its end before the user grabs a node
  scene.tween++;
  scene.nodes.forEach((n) => { [n.x, n.y] = state.pos[n.id]; });
}
function attachDrag(g, n) {
  g.addEventListener("pointerdown", (ev) => {
    if (ev.button > 0) return;
    ev.preventDefault();
    settleTween();
    // a hub carries its whole cluster, hidden nodes included, so the cluster keeps its shape
    const group = n.hub ? [n.id, ...state.graph.nodes.filter((m) => m.type === n.type).map((m) => m.id)] : [n.id];
    const from = group.map((id) => state.pos[id].slice());
    const start = toSvgPoint(ev), sx = ev.clientX, sy = ev.clientY;
    let moved = false;
    trackPointer(g, ev, "dragging", (e) => {
      if (!moved && Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) < 4) return;
      moved = true;
      const p = toSvgPoint(e), dx = p.x - start.x, dy = p.y - start.y;
      group.forEach((id, i) => {
        state.pos[id] = [from[i][0] + dx, from[i][1] + dy];
        const s = scene.byId[id];
        if (s) [s.x, s.y] = state.pos[id];
      });
      redraw();
    }, () => {
      if (moved) saveLayout(group);
      else if (!n.hub) openNode(n.id);
    });
  });
}
// Send only the ids that moved; the server merges them, so two tabs don't overwrite each other.
async function saveLayout(ids) {
  const positions = {};
  ids.forEach((id) => (positions[id] = state.pos[id]));
  try { await api("PUT", "/layout", { positions }); }
  catch (e) { status("Couldn't save the layout: " + e.message, "err"); }
}
function tidyGraph() {
  if (!confirm("Tidy re-arranges every node and replaces the positions you've set. Continue?")) return;
  const target = tidyLayout(state.graph.nodes, ...canvasSize());
  const from = {};
  Object.keys(target).forEach((id) => (from[id] = (state.pos[id] || target[id]).slice()));
  Object.assign(state.pos, target);
  state.view = null;
  buildGraphDOM();   // fits the view to the tidy positions
  saveLayout(Object.keys(target));
  status("Graph tidied.", "ok");
  if (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  // glide from the old arrangement so the eye can follow each node to its new place
  const my = scene.tween, t0 = performance.now(), DUR = 320;
  const step = (now) => {
    if (my !== scene.tween) return;
    const k = Math.min(1, (now - t0) / DUR), e = k >= 1 ? 1 : 1 - Math.pow(2, -10 * k);
    scene.nodes.forEach((n) => {
      const a = from[n.id], b = target[n.id];
      n.x = a[0] + (b[0] - a[0]) * e; n.y = a[1] + (b[1] - a[1]) * e;
    });
    redraw();
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function highlightNeighbors(id, on) {
  const nb = new Set([id]);
  state.graph.edges.forEach((e) => {
    if (e.source === id) nb.add(e.target);
    if (e.target === id) nb.add(e.source);
  });
  scene.nodes.forEach((n) => scene.els[n.id].classList.toggle("dim", on && !n.hub && !nb.has(n.id)));
  scene.edgeEls.forEach((ln) => {
    const touch = ln.dataset.s === id || ln.dataset.t === id;
    ln.classList.toggle("hl", on && touch);
  });
}

/* ------------------------- Node detail ------------------------- */
async function openNode(id) {
  state.selected = id;
  setView("node");
  renderSidebar();
  $("#node-empty").hidden = true;
  const detail = $("#node-detail"); detail.hidden = false;
  state.editing = false;
  try {
    const n = await api("GET", "/node/" + encodeURIComponent(id));
    detail.dataset.id = id;
    detail.dataset.raw = n.raw;
    const isEnabled = String(n.meta.enabled).toLowerCase() !== "false";
    detail.dataset.enabled = isEnabled ? "1" : "0";
    const tbtn = $("#btn-toggle");
    tbtn.textContent = isEnabled ? "⏻ Disable" : "⏻ Enable";
    tbtn.className = "btn " + (isEnabled ? "is-on" : "is-off");
    $("#nd-title").textContent = n.meta.title || id;
    $("#nd-meta").innerHTML = (isEnabled ? "" : `<span class="chip disabled-badge">disabled</span>`) + metaChips(n.meta);
    $("#nd-rendered").innerHTML = renderMarkdown(n.body || "");
    wireWikilinks($("#nd-rendered"));
    $("#nd-rendered").hidden = false;
    $("#nd-editor").hidden = true;
    $("#nd-raw").value = n.raw;
  } catch (e) {
    status("Load failed: " + e.message, "err");
  }
}
function metaChips(m) {
  const chips = [];
  if (m.type) chips.push(`<span class="chip type" style="background:${TYPE_COLORS[m.type] || "#888"}">${escapeHtml(String(m.type))}</span>`);
  if (m.confidence) chips.push(`<span class="chip conf">confidence: ${escapeHtml(String(m.confidence))}</span>`);
  if (m.reinforced !== undefined) chips.push(`<span class="chip">reinforced: ${escapeHtml(String(m.reinforced))}</span>`);
  (m.tags || []).forEach((t) => chips.push(`<span class="chip">#${escapeHtml(t)}</span>`));
  if (m.updated) chips.push(`<span class="chip">updated ${escapeHtml(String(m.updated))}</span>`);
  return chips.join("");
}
function enterEdit() {
  state.editing = true;
  $("#nd-rendered").hidden = true;
  $("#nd-editor").hidden = false;
  $("#nd-raw").focus();
}
function exitEdit() {
  state.editing = false;
  $("#nd-rendered").hidden = false;
  $("#nd-editor").hidden = true;
  $("#nd-raw").value = $("#node-detail").dataset.raw || "";
}
async function saveNode() {
  const id = $("#node-detail").dataset.id;
  try {
    await api("PUT", "/node/" + encodeURIComponent(id), { raw: $("#nd-raw").value });
    status("Saved.", "ok");
    await refreshGraph();
    await openNode(id);
  } catch (e) { status("Save failed: " + e.message, "err"); }
}
async function deleteNode() {
  const id = $("#node-detail").dataset.id;
  if (!confirm(`Delete node "${id}"? This removes the file. (Links from other nodes are not auto-cleaned.)`)) return;
  try {
    await api("DELETE", "/node/" + encodeURIComponent(id));
    status("Deleted.", "ok");
    state.selected = null;
    $("#node-detail").hidden = true;
    $("#node-empty").hidden = false;
    await refreshGraph();
  } catch (e) { status("Delete failed: " + e.message, "err"); }
}
async function toggleEnabled(id, enable) {
  try {
    await api("POST", "/node/" + encodeURIComponent(id) + "/enabled", { enabled: enable });
    const node = state.graph.nodes.find((n) => n.id === id);
    if (node) node.enabled = enable;  // update in place; avoids a full refetch
    status(enable ? "Enabled " + id : "Disabled " + id + " (skipped by /induce-knowledge)", "ok");
    renderSidebar();
    if ($("#view-graph").classList.contains("active")) buildGraphDOM();
    if ($("#node-detail").dataset.id === id && !$("#node-detail").hidden) await openNode(id);
  } catch (e) { status("Toggle failed: " + e.message, "err"); }
}

/* ------------------------ Markdown (mini) ---------------------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inline(s) {
  s = escapeHtml(s);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\[\[([a-z0-9-]+)\]\]/g, '<a class="wikilink" data-slug="$1" href="#">$1</a>');
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/(^|[\s(])((?:https?:\/\/)[^\s)]+)(?=$|[\s)])/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");
  return s;
}
function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  let html = "", i = 0, listType = null;
  const closeList = () => { if (listType) { html += `</${listType}>`; listType = null; } };
  while (i < lines.length) {
    let line = lines[i];
    if (/^```/.test(line)) {
      closeList(); i++;
      let code = [];
      while (i < lines.length && !/^```/.test(lines[i])) { code.push(escapeHtml(lines[i])); i++; }
      i++; html += `<pre><code>${code.join("\n")}</code></pre>`; continue;
    }
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { closeList(); const l = m[1].length; html += `<h${l}>${inline(m[2])}</h${l}>`; i++; continue; }
    if (/^\s*([-*])\s+/.test(line)) {
      if (listType !== "ul") { closeList(); listType = "ul"; html += "<ul>"; }
      html += `<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`; i++; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      if (listType !== "ol") { closeList(); listType = "ol"; html += "<ol>"; }
      html += `<li>${inline(line.replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; continue;
    }
    if (/^\s*>\s?/.test(line)) { closeList(); html += `<blockquote>${inline(line.replace(/^\s*>\s?/, ""))}</blockquote>`; i++; continue; }
    if (/^\s*---\s*$/.test(line)) { closeList(); html += "<hr>"; i++; continue; }
    if (line.trim() === "") { closeList(); i++; continue; }
    closeList(); html += `<p>${inline(line)}</p>`; i++;
  }
  closeList();
  return html;
}
function wireWikilinks(container) {
  container.querySelectorAll("a.wikilink").forEach((a) => {
    a.addEventListener("click", (e) => { e.preventDefault(); openNode(a.dataset.slug); });
  });
}

/* ---------------------------- Views ---------------------------- */
function setView(v) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === v));
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === "view-" + v));
  if (v === "graph") setTimeout(buildGraphDOM, 30);
  if (v === "journal") loadJournal();
}
async function loadJournal() {
  try {
    const j = await api("GET", "/journal");
    $("#journal").innerHTML = renderMarkdown(j.text || "_Empty journal._");
    wireWikilinks($("#journal"));
  } catch (e) { status("Journal load failed: " + e.message, "err"); }
}

/* --------------------------- Refresh --------------------------- */
async function refreshGraph() {
  const name = state.graphName;
  // positions are fetched once per graph; after that the in-memory copy is the truth
  const [graph, layout] = await Promise.all([
    api("GET", "/graph"),
    state.posFor === name ? null : api("GET", "/layout").catch(() => ({ positions: {} })),
  ]);
  state.graph = graph;
  if (layout) { state.pos = layout.positions || {}; state.posFor = name; state.view = null; }
  renderSidebar();
  if ($("#view-graph").classList.contains("active")) buildGraphDOM();
}

/* --------------------- Export / Import ------------------------- */
function download(url) {
  if (state.graphName) url += (url.includes("?") ? "&" : "?") + "graph=" + encodeURIComponent(state.graphName);
  const a = document.createElement("a");
  a.href = url + (TOKEN ? (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(TOKEN) : "");
  a.click();
}

/* ------------------------ Knowledge graphs --------------------- */
async function loadGraphs() {
  try {
    const r = await api("GET", "/graphs");
    if (state.graphName === null) state.graphName = r.current;
    const sel = $("#graphsel");
    sel.innerHTML = r.graphs
      .map((g) => `<option value="${escapeHtml(g.name)}"${g.name === state.graphName ? " selected" : ""}>`
        + `${escapeHtml(g.name)} (${g.nodes})</option>`).join("");
    const cur = r.graphs.find((g) => g.name === state.graphName);
    $("#btn-del-graph").disabled = !cur || !cur.deletable;
    $("#btn-ren-graph").disabled = !cur || !cur.deletable;
    $("#btn-ren-graph").title = cur && cur.deletable
      ? `Rename the "${state.graphName}" graph` : "The default graph cannot be renamed";
    $("#btn-del-graph").title = cur && cur.deletable
      ? `Delete the "${state.graphName}" graph` : "The default graph is protected";
  } catch (e) { status("Graph list failed: " + e.message, "err"); }
}
async function switchGraph(name) {
  state.graphName = name;
  state.selected = null; state.typeFilter = null;
  $("#node-detail").hidden = true; $("#node-empty").hidden = false;
  await loadGraphs();
  await refreshGraph();
  setView("graph");
  status("Switched to graph: " + name, "ok");
}
async function createGraph() {
  const name = prompt("Name for the new knowledge graph:\n\n" +
    "(lowercase letters, digits, - and _ only. It starts empty.)");
  if (name === null) return;                        // cancelled
  const n = name.trim();
  if (!n) return;
  try {
    const r = await api("POST", "/graph/new?to=" + encodeURIComponent(n));
    await switchGraph(r.created);                   // open the new graph straight away
    status(`Created empty graph "${r.created}".`, "ok");
  } catch (e) { status("Create failed: " + e.message, "err"); }
}
async function renameGraph() {
  const old = state.graphName;
  if (!old || old === "default") return;
  const to = prompt(`Rename the knowledge graph "${old}" to:\n\n` +
    `(lowercase letters, digits, - and _ only. Nodes and links are unaffected.)`, old);
  if (to === null) return;                          // cancelled
  const name = to.trim();
  if (!name || name === old) return;
  try {
    const r = await api("POST", "/graph/rename?to=" + encodeURIComponent(name));
    state.graphName = r.to;
    await loadGraphs();
    await refreshGraph();
    status(`Renamed "${r.renamed}" → "${r.to}".`, "ok");
  } catch (e) { status("Rename failed: " + e.message, "err"); }
}
async function deleteGraph() {
  const name = state.graphName;
  if (!name || name === "default") return;
  const typed = prompt(
    `Permanently DELETE the knowledge graph "${name}" and every node in it?\n\n` +
    `This cannot be undone. Type the graph name to confirm:`);
  if (typed === null) return;                      // cancelled
  if (typed.trim() !== name) { status("Delete aborted — name did not match.", "err"); return; }
  try {
    const r = await api("DELETE", "/graph?confirm=" + encodeURIComponent(name));
    status(`Deleted graph "${r.deleted}" (${r.nodes_removed} node(s)).`, "ok");
    state.graphName = null;                        // fall back to the server's graph
    await loadGraphs();
    await refreshGraph();
  } catch (e) { status("Delete failed: " + e.message, "err"); }
}
async function doImport(file) {
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const nodes = parsed.nodes || [];
    if (!confirm(`Import ${nodes.length} node(s)? Existing nodes with the same slug will be overwritten.`)) return;
    const r = await api("POST", "/import", parsed.layout ? { nodes, layout: parsed.layout } : { nodes });
    status(`Imported ${r.written.length}, skipped ${r.skipped.length}.`, "ok");
    state.posFor = undefined;   // re-read layout.json so imported positions aren't re-placed and overwritten
    await refreshGraph();
  } catch (e) { status("Import failed: " + e.message, "err"); }
}

/* ----------------------------- Init ---------------------------- */
function wireEvents() {
  $("#search").addEventListener("input", (e) => { state.query = e.target.value; renderSidebar(); });
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => setView(t.dataset.view)));
  $("#graphsel").addEventListener("change", (e) => switchGraph(e.target.value));
  $("#btn-new-graph").onclick = createGraph;
  $("#btn-ren-graph").onclick = renameGraph;
  $("#btn-del-graph").onclick = deleteGraph;
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; renderSidebar(); });
  $("#flt-all").onclick = () => setAllTypes(true);
  $("#flt-none").onclick = () => setAllTypes(false);
  $("#flt-hide-disabled").addEventListener("change", (e) => { state.hideDisabled = e.target.checked; buildGraphDOM(); });
  $("#btn-tidy").onclick = tidyGraph;
  $("#btn-fit").onclick = fitGraph;
  wireGraphView();
  $("#btn-edit").onclick = enterEdit;
  $("#btn-cancel").onclick = exitEdit;
  $("#btn-save").onclick = saveNode;
  $("#btn-delete").onclick = deleteNode;
  $("#btn-toggle").onclick = () => {
    const d = $("#node-detail");
    toggleEnabled(d.dataset.id, d.dataset.enabled === "0");  // if currently off → enable
  };
  $("#btn-reindex").onclick = async () => { try { await api("POST", "/reindex"); status("INDEX.md rebuilt.", "ok"); } catch (e) { status(e.message, "err"); } };
  $("#btn-export-zip").onclick = () => download("/api/export?format=zip");
  $("#btn-export-json").onclick = () => download("/api/export?format=json");
  $("#btn-import").onclick = () => $("#import-file").click();
  $("#import-file").onchange = (e) => { if (e.target.files[0]) doImport(e.target.files[0]); e.target.value = ""; };

  const dlg = $("#new-dialog");
  $("#btn-new").onclick = () => { $("#new-form").reset(); dlg.showModal(); };
  dlg.addEventListener("close", async () => {
    if (dlg.returnValue !== "create") return;
    const body = {
      slug: $("#nn-slug").value.trim().toLowerCase(),
      title: $("#nn-title").value.trim(),
      type: $("#nn-type").value,
      tags: $("#nn-tags").value,
      summary: $("#nn-summary").value.trim(),
    };
    try {
      const r = await api("POST", "/node", body);
      status("Created " + r.slug, "ok");
      await refreshGraph();
      await openNode(r.slug);
      enterEdit();
    } catch (e) { status("Create failed: " + e.message, "err"); }
  });

  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => { if ($("#view-graph").classList.contains("active")) buildGraphDOM(); }, 200);
  });
}
async function init() {
  renderLegend();
  wireEvents();
  try {
    await loadGraphs();
    await refreshGraph();
    setView("graph");
    status("Loaded " + state.graph.nodes.length + " nodes.", "ok");
  } catch (e) {
    status("Could not reach server: " + e.message, "err");
  }
}
init();
