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
let sim = { looping: false, alpha: 0, epoch: 0, nodes: [], byId: {}, els: {}, edgeEls: [] };
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
  const types = [...new Set([...TYPE_ORDER, ...Object.keys(counts)])].filter((t) => counts[t]);
  const leg = $("#legend");
  leg.innerHTML = types.map((t) => {
    const off = state.typeFilter && !state.typeFilter.has(t) ? " off" : "";
    return `<span class="leg${off}" data-type="${escapeHtml(t)}"><i style="background:${TYPE_COLORS[t] || "#888"}"></i>${TYPE_LABEL[t] || escapeHtml(t)}<span class="cnt">${counts[t]}</span></span>`;
  }).join("");
  leg.querySelectorAll(".leg").forEach((el) => (el.onclick = () => toggleType(el.dataset.type)));
}
function buildGraphDOM() {
  renderLegend();
  const svg = $("#graph");
  svg.innerHTML = "";
  sim.looping = false; sim.alpha = 0;  // stop any in-flight loop before rebuilding
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  sim.W = W;
  const visible = state.graph.nodes.filter(
    (n) => typeVisible(n.type) && (!state.hideDisabled || n.enabled !== false)
  );
  const visibleIds = new Set(visible.map((n) => n.id));
  // One anchored parent hub per category, spaced on an ellipse, so the graph reads as
  // labelled clusters instead of a single blob. Hubs are synthetic (not KB nodes).
  const counts = {};
  visible.forEach((n) => (counts[n.type] = (counts[n.type] || 0) + 1));
  const hubTypes = [...new Set([...TYPE_ORDER, ...Object.keys(counts)])].filter((t) => counts[t]);
  const RX = W * 0.33, RY = H * 0.30;
  const hubs = hubTypes.map((t, i) => {
    const a = (i / hubTypes.length) * Math.PI * 2 - Math.PI / 2;
    return {
      id: "__hub__" + t, hub: true, type: t, title: TYPE_LABEL[t] || t,
      x: W / 2 + Math.cos(a) * RX, y: H / 2 + Math.sin(a) * RY,
      vx: 0, vy: 0, fixed: true, r: 13,   // fixed → the tick leaves it anchored
    };
  });
  const hubById = {}; hubs.forEach((h) => (hubById[h.type] = h));

  sim.nodes = visible.map((n) => {
    const h = hubById[n.type];
    return {
      ...n,
      x: (h ? h.x : W / 2) + (Math.random() - 0.5) * 120,
      y: (h ? h.y : H / 2) + (Math.random() - 0.5) * 120,
      vx: 0, vy: 0, fixed: false, r: 7 + Math.min(10, (n.reinforced || 0) * 2),
    };
  }).concat(hubs);
  sim.byId = {}; sim.nodes.forEach((n) => (sim.byId[n.id] = n));
  const gEdges = document.createElementNS(SVGNS, "g");
  const gNodes = document.createElementNS(SVGNS, "g");
  svg.appendChild(gEdges); svg.appendChild(gNodes);
  // weak links between related nodes; strong spoke pinning each node to its own hub
  sim.edges = state.graph.edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => ({ s: e.source, t: e.target, len: 110, k: 0.006, cls: "edge" }))
    .concat(visible.filter((n) => hubById[n.type])
      .map((n) => ({ s: n.id, t: hubById[n.type].id, len: 78, k: 0.055, cls: "edge spoke" })));
  sim.edgeEls = sim.edges.map((e) => {
    const ln = document.createElementNS(SVGNS, "line");
    ln.setAttribute("class", e.cls);
    ln.dataset.s = e.s; ln.dataset.t = e.t;
    gEdges.appendChild(ln);
    return ln;
  });
  sim.els = {}; sim.labels = {};
  sim.nodes.forEach((n) => {
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "gnode" + (n.hub ? " hub" : "") + (n.enabled === false ? " off" : ""));
    g.dataset.id = n.id;
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("r", n.r);
    c.setAttribute("fill", TYPE_COLORS[n.type] || "#888");
    const label = document.createElementNS(SVGNS, "text");
    label.setAttribute("x", n.r + 4); label.setAttribute("y", 4);
    label.textContent = n.hub ? `${n.title} (${counts[n.type]})` : n.title;
    g.appendChild(c); g.appendChild(label);
    const tt = document.createElementNS(SVGNS, "title");
    tt.textContent = n.hub ? `${n.title} — ${counts[n.type]} node(s)`
      : `${n.title} [${n.type}] — ${n.confidence}, reinforced ${n.reinforced}` + (n.enabled === false ? " (disabled)" : "");
    g.appendChild(tt);
    gNodes.appendChild(g);
    sim.els[n.id] = g;
    sim.labels[n.id] = label;
    if (!n.hub) {   // hubs are layout anchors: not draggable, not clickable
      attachDrag(g, n);
      g.addEventListener("mouseenter", () => highlightNeighbors(n.id, true));
      g.addEventListener("mouseleave", () => highlightNeighbors(n.id, false));
    }
  });
  startSim();
}
function startSim(reheat) {
  // Reheatable, single-instance loop. `sim.alpha` is the energy; `sim.looping`
  // guards against spawning a second rAF loop. Any interaction (drag) can reheat.
  sim.alpha = Math.max(sim.alpha, reheat == null ? 1 : reheat);
  if (sim.looping) return;
  sim.looping = true;
  const myEpoch = ++sim.epoch;  // a rebuild bumps the epoch; a superseded loop dies
  const svg = $("#graph");
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  function tick() {
    if (myEpoch !== sim.epoch) return;  // a newer loop owns the graph now → stop
    const ns = sim.nodes;
    for (let i = 0; i < ns.length; i++) {
      for (let j = i + 1; j < ns.length; j++) {
        const a = ns[i], b = ns[j];
        let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy || 0.01, d = Math.sqrt(d2);
        const rep = 5200 / d2, fx = (dx / d) * rep, fy = (dy / d) * rep;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    (sim.edges || []).forEach((e) => {
      const a = sim.byId[e.s], b = sim.byId[e.t];
      if (!a || !b) return;
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const k = (d - e.len) * e.k, fx = (dx / d) * k, fy = (dy / d) * k;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    });
    ns.forEach((n) => {
      if (n.fixed) { n.vx = n.vy = 0; return; }  // anchored hub, or pinned to cursor
      // no center gravity: hub spokes do the positioning, keeping clusters apart
      n.x += n.vx * sim.alpha * 0.4; n.y += n.vy * sim.alpha * 0.4;
      n.x = Math.max(n.r + 6, Math.min(W - n.r - 6, n.x));
      n.y = Math.max(n.r + 6, Math.min(H - 20, n.y));
      n.vx *= 0.82; n.vy *= 0.82;
    });
    sim.alpha *= 0.992;
    frame();
    if (sim.alpha > 0.02) requestAnimationFrame(tick);
    else sim.looping = false;  // settle; restartable via startSim(reheat)
  }
  requestAnimationFrame(tick);
}
function frame() {
  sim.edgeEls.forEach((ln) => {
    const a = sim.byId[ln.dataset.s], b = sim.byId[ln.dataset.t];
    if (!a || !b) return;
    ln.setAttribute("x1", a.x); ln.setAttribute("y1", a.y);
    ln.setAttribute("x2", b.x); ln.setAttribute("y2", b.y);
  });
  sim.nodes.forEach((n) => {
    sim.els[n.id].setAttribute("transform", `translate(${n.x},${n.y})`);
    // nodes are clamped to the canvas but their labels are not: flip the text inward
    // near the right edge so long titles stay readable instead of being cut off.
    if (n.lw == null) {   // measured once per rebuild: titles vary a lot in length
      const el = sim.labels[n.id];
      n.lw = (el.getComputedTextLength ? el.getComputedTextLength() : 0) || el.textContent.length * 5.8;
    }
    const flip = n.x + n.r + 8 + n.lw > (sim.W || 800);
    if (flip !== n.flipped) {
      const t = sim.labels[n.id];
      t.setAttribute("x", flip ? -(n.r + 4) : n.r + 4);
      t.setAttribute("text-anchor", flip ? "end" : "start");
      n.flipped = flip;
    }
  });
}
function attachDrag(g, n) {
  let moved = false, startX, startY;
  g.addEventListener("pointerdown", (ev) => {
    ev.preventDefault(); moved = false; startX = ev.clientX; startY = ev.clientY;
    n.fixed = true;
    try { g.setPointerCapture(ev.pointerId); } catch (_) {}
    startSim(0.5);  // wake the sim so the drag is live even if the graph had settled
    const svg = $("#graph");
    const onMove = (e) => {
      const r = svg.getBoundingClientRect();
      n.x = e.clientX - r.left; n.y = e.clientY - r.top; n.vx = n.vy = 0;
      if (Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY) > 4) moved = true;
      frame();                               // immediate, zero-latency repaint
      if (!sim.looping) startSim(0.3);        // re-ignite if it cooled mid-drag
    };
    const onUp = (e) => {
      g.removeEventListener("pointermove", onMove);
      g.removeEventListener("pointerup", onUp);
      try { g.releasePointerCapture(ev.pointerId); } catch (_) {}
      n.fixed = false; n.vx = n.vy = 0;
      if (!moved) openNode(n.id);
    };
    g.addEventListener("pointermove", onMove);
    g.addEventListener("pointerup", onUp);
  });
}
function highlightNeighbors(id, on) {
  const nb = new Set([id]);
  state.graph.edges.forEach((e) => {
    if (e.source === id) nb.add(e.target);
    if (e.target === id) nb.add(e.source);
  });
  sim.nodes.forEach((n) => sim.els[n.id].classList.toggle("dim", on && !nb.has(n.id)));
  sim.edgeEls.forEach((ln) => {
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
  state.graph = await api("GET", "/graph");
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
    const r = await api("POST", "/import", { nodes });
    status(`Imported ${r.written.length}, skipped ${r.skipped.length}.`, "ok");
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
