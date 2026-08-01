"use strict";
// Optimus brain viewer — read-only frontend. Hand-rolled SVG force-directed graph,
// zero external libraries, zero network calls beyond this localhost server.

const SVGNS = "http://www.w3.org/2000/svg";
const AUDIT_FILL = {
  "verified": "#3fb950", "drifted": "#f85149",
  "unverifiable-here": "#8b949e", "skipped": "#6e7681", "none": "#30363d",
};
const TIER_STROKE = { 1: "#d29922", 2: "#58a6ff", 3: "#bc8cff", 4: "#39c5cf" };

const el = (id) => document.getElementById(id);
const svg = el("graph");
const gViewport = el("viewport");
const gNodes = el("nodes");
const gEdges = el("edges");

const state = {
  nodes: [], edges: [], byId: new Map(),
  selected: null,
  filters: { audit: "all", tiers: new Set([1, 2, 3, 4]), project: "" },
  matches: new Set(),         // search highlight set
  transform: { x: 0, y: 0, k: 1 },
  alpha: 0, running: false,
};

// ---- shapes: tier → SVG element (audit state drives fill) ----------------- //
function shapeFor(node, r) {
  const t = node.tier;
  let shape;
  if (t === 1) {            // identity → star
    shape = document.createElementNS(SVGNS, "polygon");
    shape.setAttribute("points", starPoints(r, r * 0.42, 5));
  } else if (t === 3) {     // dispositions → hexagon
    shape = document.createElementNS(SVGNS, "polygon");
    shape.setAttribute("points", regularPoly(r, 6, 0));
  } else if (t === 4) {     // ephemeral → triangle
    shape = document.createElementNS(SVGNS, "polygon");
    shape.setAttribute("points", regularPoly(r, 3, -Math.PI / 2));
  } else {                  // projects (and fallback) → circle
    shape = document.createElementNS(SVGNS, "circle");
    shape.setAttribute("r", r);
  }
  shape.setAttribute("class", "shape");
  shape.setAttribute("fill", AUDIT_FILL[node.audit_state] || AUDIT_FILL.none);
  shape.setAttribute("stroke", TIER_STROKE[t] || "#444");
  return shape;
}
function regularPoly(r, n, off) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = off + (i * 2 * Math.PI) / n;
    pts.push(`${(r * Math.cos(a)).toFixed(1)},${(r * Math.sin(a)).toFixed(1)}`);
  }
  return pts.join(" ");
}
function starPoints(rOuter, rInner, spikes) {
  const pts = [];
  for (let i = 0; i < spikes * 2; i++) {
    const r = i % 2 ? rInner : rOuter;
    const a = (i * Math.PI) / spikes - Math.PI / 2;
    pts.push(`${(r * Math.cos(a)).toFixed(1)},${(r * Math.sin(a)).toFixed(1)}`);
  }
  return pts.join(" ");
}
const radiusFor = (n) => Math.min(26, 11 + Math.sqrt(n.claim_count || 0) * 2.2);

// ---- load + build --------------------------------------------------------- //
async function load() {
  const graph = await (await fetch("/api/graph")).json();
  state.nodes = graph.nodes.map((n, i) => ({
    ...n,
    x: Math.cos(i) * 220 + (n.tier - 2) * 60,
    y: Math.sin(i * 1.3) * 200 + (n.tier - 2) * 90,
    vx: 0, vy: 0, r: radiusFor(n),
  }));
  state.byId = new Map(state.nodes.map((n) => [n.id, n]));
  state.edges = graph.edges
    .map((e) => ({ ...e, s: state.byId.get(e.source), t: state.byId.get(e.target) }))
    .filter((e) => e.s && e.t);
  renderSummary(graph.summary);
  buildProjectFilter();
  el("tomb-count").textContent = graph.summary.tombstones;
  buildSvg();
  kick(1.0);
}

function renderSummary(s) {
  el("summary").innerHTML =
    `${s.pages} pages · ${s.edges} edges · ${s.claims} claims<br>` +
    `<span style="color:${AUDIT_FILL.verified}">${s.verified} verified</span> · ` +
    `<span style="color:${AUDIT_FILL.drifted};font-weight:700">${s.drifted} DRIFTED</span> · ` +
    `<span style="color:${AUDIT_FILL["unverifiable-here"]}">${s.unverifiable} unverif</span> · ` +
    `${s.skipped} skipped`;
}
function buildProjectFilter() {
  const projects = [...new Set(state.nodes.map((n) => n.project).filter(Boolean))].sort();
  const sel = el("project");
  for (const p of projects) {
    const o = document.createElement("option");
    o.value = p; o.textContent = p; sel.appendChild(o);
  }
}

function buildSvg() {
  gNodes.innerHTML = ""; gEdges.innerHTML = "";
  for (const e of state.edges) {
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("class", "edge");
    line.dataset.rel = e.rel;
    e._line = line; gEdges.appendChild(line);
  }
  for (const n of state.nodes) {
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "node");
    g.dataset.id = n.id;
    const shape = shapeFor(n, n.r);
    const label = document.createElementNS(SVGNS, "text");
    label.setAttribute("class", "label");
    label.setAttribute("y", n.r + 13);
    label.textContent = n.title.length > 26 ? n.title.slice(0, 24) + "…" : n.title;
    const title = document.createElementNS(SVGNS, "title");
    title.textContent =
      `${n.title}\ntier ${n.tier} · ${n.type}` + (n.project ? ` · ${n.project}` : "") +
      `\naudit: ${n.audit_state} (${n.claim_count} claims)`;
    g.append(shape, label, title);
    if (n.status !== "active") g.classList.add("deprecated");
    g.addEventListener("pointerdown", (ev) => onNodeDown(ev, n));
    g.addEventListener("click", (ev) => { if (!g._dragged) selectNode(n.id); });
    n._g = g; gNodes.appendChild(g);
  }
  applyFilters();
}

// ---- force simulation ----------------------------------------------------- //
function tick() {
  const N = state.nodes, REP = 9000, SPRING = 0.03, REST = 120, CENTER = 0.015;
  for (const n of N) { if (!n._fixed) { n.vx *= 0.85; n.vy *= 0.85; } }
  for (let i = 0; i < N.length; i++) {
    const a = N[i];
    for (let j = i + 1; j < N.length; j++) {
      const b = N[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy || 0.01;
      const f = REP / d2;
      const d = Math.sqrt(d2);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      if (!a._fixed) { a.vx += fx; a.vy += fy; }
      if (!b._fixed) { b.vx -= fx; b.vy -= fy; }
    }
  }
  for (const e of state.edges) {
    let dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const f = SPRING * (d - REST);
    const fx = (dx / d) * f, fy = (dy / d) * f;
    if (!e.s._fixed) { e.s.vx += fx; e.s.vy += fy; }
    if (!e.t._fixed) { e.t.vx -= fx; e.t.vy -= fy; }
  }
  for (const n of N) {
    if (n._fixed) continue;
    n.vx -= n.x * CENTER; n.vy -= n.y * CENTER;
    n.x += n.vx * state.alpha; n.y += n.vy * state.alpha;
  }
}
function paint() {
  for (const e of state.edges)
    if (e._line) {
      e._line.setAttribute("x1", e.s.x); e._line.setAttribute("y1", e.s.y);
      e._line.setAttribute("x2", e.t.x); e._line.setAttribute("y2", e.t.y);
    }
  for (const n of state.nodes)
    n._g.setAttribute("transform", `translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`);
}
function loop() {
  tick(); paint();
  state.alpha *= 0.992;
  if (state.alpha > 0.01) requestAnimationFrame(loop);
  else { state.running = false; paint(); }
}
function kick(a = 0.6) {
  state.alpha = Math.max(state.alpha, a);
  if (!state.running) { state.running = true; requestAnimationFrame(loop); }
}

// ---- filters -------------------------------------------------------------- //
function applyFilters() {
  const f = state.filters;
  const visible = new Set();
  for (const n of state.nodes) {
    let ok = f.tiers.has(n.tier);
    if (ok && f.project) ok = n.project === f.project;
    if (ok && f.audit !== "all") {
      // drifted filter: a page counts if it has ANY drifted claim
      if (f.audit === "drifted") ok = (n.audit_counts.drifted || 0) > 0;
      else ok = n.audit_state === f.audit;
    }
    n._visible = ok;
    if (ok) visible.add(n.id);
    n._g.classList.toggle("hidden", !ok);
  }
  for (const e of state.edges)
    e._line.classList.toggle("hidden", !(visible.has(e.source) && visible.has(e.target)));
  applyHighlight();
}
function applyHighlight() {
  const hasMatch = state.matches.size > 0;
  for (const n of state.nodes) {
    n._g.classList.toggle("match", state.matches.has(n.id));
    n._g.classList.toggle("dim", hasMatch && n._visible && !state.matches.has(n.id));
    n._g.classList.toggle("selected", n.id === state.selected);
  }
}

// ---- interaction: pan / zoom / drag --------------------------------------- //
function applyTransform() {
  const t = state.transform;
  gViewport.setAttribute("transform", `translate(${t.x},${t.y}) scale(${t.k})`);
}
function screenToGraph(sx, sy) {
  const r = svg.getBoundingClientRect(), t = state.transform;
  return { x: (sx - r.left - t.x) / t.k, y: (sy - r.top - t.y) / t.k };
}
svg.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const t = state.transform;
  const r = svg.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
  const k = Math.max(0.15, Math.min(4, t.k * factor));
  t.x = mx - ((mx - t.x) * k) / t.k;
  t.y = my - ((my - t.y) * k) / t.k;
  t.k = k; applyTransform();
}, { passive: false });

let panning = null;
svg.addEventListener("pointerdown", (ev) => {
  if (ev.target.closest(".node")) return;     // node drag handled separately
  panning = { x: ev.clientX, y: ev.clientY, tx: state.transform.x, ty: state.transform.y };
  svg.classList.add("panning");
});
window.addEventListener("pointermove", (ev) => {
  if (!panning) return;
  state.transform.x = panning.tx + (ev.clientX - panning.x);
  state.transform.y = panning.ty + (ev.clientY - panning.y);
  applyTransform();
});
window.addEventListener("pointerup", () => { panning = null; svg.classList.remove("panning"); });

let drag = null;
function onNodeDown(ev, n) {
  ev.stopPropagation();
  n._g._dragged = false;
  drag = { n, startX: ev.clientX, startY: ev.clientY };
  n._fixed = true;
  n._g.setPointerCapture(ev.pointerId);
  const move = (e) => {
    if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 3) n._g._dragged = true;
    const p = screenToGraph(e.clientX, e.clientY);
    n.x = p.x; n.y = p.y; n.vx = n.vy = 0; kick(0.25);
  };
  const up = (e) => {
    n._fixed = false; drag = null;
    n._g.removeEventListener("pointermove", move);
    n._g.removeEventListener("pointerup", up);
    setTimeout(() => { n._g._dragged = false; }, 0);
  };
  n._g.addEventListener("pointermove", move);
  n._g.addEventListener("pointerup", up);
}

// ---- detail panel --------------------------------------------------------- //
async function selectNode(id) {
  state.selected = id; applyHighlight();
  el("tombstones").classList.add("hidden");
  const d = await (await fetch("/api/page?id=" + encodeURIComponent(id))).json();
  if (d.error) return;
  el("detail-body").innerHTML = renderDetail(d);
  el("detail").classList.remove("hidden");
}
function esc(s) {
  return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function statePill(st) { return `<span class="pill state-${st}">${st}</span>`; }
function renderDetail(d) {
  const counts = d.claims.reduce((m, c) => (m[c.audit.state] = (m[c.audit.state] || 0) + 1, m), {});
  const head =
    `<h2>${esc(d.title)}</h2>` +
    `<div><span class="pill tier${d.tier}">tier ${d.tier}</span>` +
    `<span class="pill">${esc(d.type)}</span>` +
    (d.project ? `<span class="pill">${esc(d.project)}</span>` : "") +
    (d.status !== "active" ? `<span class="pill state-drifted">${esc(d.status)}</span>` : "") +
    `</div>` +
    `<div class="meta-line">id: ${esc(d.id)}` +
    (d.aliases.length ? ` · aliases: ${esc(d.aliases.join(", "))}` : "") + `</div>` +
    (d.source_root ? `<div class="meta-line">source_root: ${esc(d.source_root)}</div>` : "") +
    `<div class="meta-line">audit: ` +
    Object.keys(AUDIT_FILL).filter((k) => counts[k]).map((k) =>
      `<span style="color:${AUDIT_FILL[k]}">${counts[k]} ${k}</span>`).join(" · ") +
    ` · ${d.claims.length} claims</div>`;

  const claims = d.claims.map((c) => {
    const cls = `claim k-${c.kind} s-${c.audit.state}`;
    let inner = `<div class="kind-tag">${esc(c.kind)} ${statePill(c.audit.state)}` +
      (c.status !== "active" ? ` <span class="pill">${esc(c.status)}</span>` : "") + `</div>` +
      `<div class="ctext">${esc(c.text)}</div>`;
    if (c.rationale) inner += `<div class="why"><b>Why:</b> ${esc(c.rationale)}</div>`;
    if (c.quote) inner += `<div class="quote">${esc(c.quote)}</div>`;
    inner += `<div class="src">${esc(c.source)}</div>`;
    if (c.audit.state === "unverifiable-here" && c.audit.as_of)
      inner += `<div class="asof">last-known-good as of ${esc(c.audit.as_of)}</div>`;
    if (c.audit.state === "drifted")
      inner += `<div class="asof" style="color:${AUDIT_FILL.drifted}">⚠ ${esc(c.audit.detail)}</div>`;
    return `<div class="${cls}">${inner}</div>`;
  }).join("");

  const body = d.body
    ? `<details><summary>page markdown body</summary><pre class="body">${esc(d.body)}</pre></details>`
    : "";
  return head + (claims || `<p class="empty">No claims on this page.</p>`) + body;
}
el("detail-close").addEventListener("click", () => {
  el("detail").classList.add("hidden"); state.selected = null; applyHighlight();
});

// ---- tombstones ----------------------------------------------------------- //
async function showTombstones() {
  el("detail").classList.add("hidden");
  const { tombstones } = await (await fetch("/api/tombstones")).json();
  el("tomb-body").innerHTML = tombstones.length
    ? tombstones.map((t) =>
        `<div class="tomb"><h3>${esc(t.entity)}</h3>` +
        `<div class="meta-line">deprecated ${esc(t.created)}</div>` +
        `<div>${esc(t.reason)}</div>` +
        `<div class="meta-line">aliases: ${esc((t.aliases || []).join(", ")) || "—"}<br>` +
        `pages: ${esc((t.pages || []).join(", ")) || "—"}</div></div>`).join("")
    : `<p class="empty">No deprecated entities — nothing has been forgotten yet.</p>`;
  el("tombstones").classList.remove("hidden");
}
el("tombstone-btn").addEventListener("click", showTombstones);
el("tomb-close").addEventListener("click", () => el("tombstones").classList.add("hidden"));

// ---- search --------------------------------------------------------------- //
let searchTimer = null;
el("search").addEventListener("input", (ev) => {
  clearTimeout(searchTimer);
  const q = ev.target.value.trim();
  searchTimer = setTimeout(() => runSearch(q), 160);
});
async function runSearch(q) {
  if (!q) { state.matches.clear(); el("search-results").innerHTML = ""; applyHighlight(); return; }
  const { results } = await (await fetch("/api/search?q=" + encodeURIComponent(q))).json();
  state.matches = new Set(results.map((r) => r.page_id));
  el("search-results").innerHTML = results.slice(0, 12).map((r) =>
    `<li data-id="${esc(r.page_id)}">${esc(r.title)}<span class="via">${esc(r.via)}</span></li>`).join("");
  for (const li of el("search-results").children)
    li.addEventListener("click", () => { focusNode(li.dataset.id); });
  applyHighlight();
  // center on first match
  if (results.length) focusNode(results[0].page_id, false);
}
function focusNode(id, select = true) {
  const n = state.byId.get(id);
  if (!n) return;
  const r = svg.getBoundingClientRect(), t = state.transform;
  t.k = Math.max(t.k, 1);
  t.x = r.width / 2 - n.x * t.k;
  t.y = r.height / 2 - n.y * t.k;
  applyTransform();
  if (select) selectNode(id);
}

// ---- filter chips --------------------------------------------------------- //
for (const chip of el("audit-filter").children)
  chip.addEventListener("click", () => {
    [...el("audit-filter").children].forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.filters.audit = chip.dataset.state; applyFilters();
  });
for (const chip of el("tier-filter").children)
  chip.addEventListener("click", () => {
    const tier = +chip.dataset.tier;
    if (state.filters.tiers.has(tier)) { state.filters.tiers.delete(tier); chip.classList.remove("active"); }
    else { state.filters.tiers.add(tier); chip.classList.add("active"); }
    applyFilters();
  });
el("project").addEventListener("change", (ev) => {
  state.filters.project = ev.target.value; applyFilters();
});
el("refresh-btn").addEventListener("click", async () => {
  const s = await (await fetch("/api/refresh")).json();
  renderSummary(s);
  // reload graph to rebind audit states
  await reloadGraphStates();
});
async function reloadGraphStates() {
  const graph = await (await fetch("/api/graph")).json();
  const fresh = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const n of state.nodes) {
    const g = fresh.get(n.id);
    if (!g) continue;
    n.audit_state = g.audit_state; n.audit_counts = g.audit_counts;
    const shape = n._g.querySelector(".shape");
    shape.setAttribute("fill", AUDIT_FILL[n.audit_state] || AUDIT_FILL.none);
  }
  applyFilters();
}

// center the graph initially
function centerView() {
  const r = svg.getBoundingClientRect();
  state.transform = { x: r.width / 2, y: r.height / 2, k: 1 };
  applyTransform();
}
centerView();
load().catch((e) => { el("summary").textContent = "failed to load: " + e; });
