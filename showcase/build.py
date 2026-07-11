"""Build the PUBLIC Optimus brain showcase — a static site for Vercel.

Reads the brain STRICTLY read-only and exports ONLY the public slice:
  - an interactive brain MAP (every page is a bubble; private pages are
    anonymized — shape visible, content never)
  - aggregate corpus stats (counts by tier/type/project, event log ops)
  - the aegis-finance + aegis-quant-knowledge project pages (full text)
  - real retrieval-demo output (deterministic, LLM-free scoring)

NEVER exported: identity/disposition content, conversations, and every
non-aegis project's content (coursework, personal portfolio, hobbies) — those
appear only as anonymous bubbles/counts. All output is English.

Outputs into showcase/optimus-brain/ (the Vercel deploy root):
  index.html   — human view (interactive map + explanations)
  brain.json   — machine view (CORS: *) for DeepSeek/Claude/any agent
  llms.txt     — plain-text index for LLM agents
  pages/*.md   — raw public pages
  vercel.json  — static config + CORS headers

Usage:  python showcase/build.py   (from the optimus repo root)
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "optimus-brain"

PUBLIC_PROJECTS = ("aegis-finance", "aegis-quant-knowledge")
DEMO_QUERIES = [
    "what is aegis finance",
    "aegis structure",
    "aegis quant knowledge lessons",
]

sys.path.insert(0, str(ROOT))
from core.query import retrieve          # noqa: E402
from core.store import Store             # noqa: E402


def corpus_stats(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
    by_type = {r[0]: r[1] for r in q(
        "SELECT type, COUNT(*) FROM pages WHERE status='active' GROUP BY type")}
    by_project = {r[0] or "(none)": r[1] for r in q(
        "SELECT project, COUNT(*) FROM pages WHERE status='active' GROUP BY project")}
    n_pages = sum(by_type.values())
    n_claims = q("SELECT COUNT(*) FROM claims")[0][0]
    n_aliases = q("SELECT COUNT(*) FROM aliases")[0][0]
    n_edges = q("SELECT COUNT(*) FROM edges")[0][0]
    last_updated = q("SELECT MAX(updated) FROM pages")[0][0]
    events_by_op = {r[0]: r[1] for r in q(
        "SELECT op, COUNT(*) FROM events GROUP BY op")}
    return {
        "pages": n_pages, "claims": n_claims, "aliases": n_aliases,
        "edges": n_edges, "last_updated": last_updated,
        "pages_by_type": by_type,
        "pages_by_project": {
            (p if p in PUBLIC_PROJECTS else "private"): c
            for p, c in sorted(by_project.items())
        },
        "events_by_op": events_by_op,
    }


def sanitize(text: str) -> str:
    """Scrub local paths and email addresses from anything exported publicly."""
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "~", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email redacted]", text)
    return text


def public_pages(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, type, project, path, updated FROM pages "
        "WHERE status='active' AND project IN (?, ?) ORDER BY project, type",
        PUBLIC_PROJECTS,
    ).fetchall()
    out = []
    for r in rows:
        md = sanitize((ROOT / r["path"]).read_text(encoding="utf-8"))
        out.append({"id": r["id"], "title": r["title"], "type": r["type"],
                    "project": r["project"], "updated": r["updated"],
                    "markdown": md})
    return out


def graph_data(conn: sqlite3.Connection) -> dict:
    """Nodes + edges for the interactive brain map. Private pages appear as
    ANONYMOUS bubbles — real id/title/project replaced — so the brain's shape
    is visible without leaking content."""
    rows = conn.execute(
        "SELECT id, title, type, project FROM pages WHERE status='active'"
    ).fetchall()
    claims = {r[0]: r[1] for r in conn.execute(
        "SELECT page_id, COUNT(*) FROM claims GROUP BY page_id")}
    edges = conn.execute(
        "SELECT src_page_id, dst_page_id, rel FROM edges").fetchall()

    anon_page: dict[str, str] = {}
    anon_proj: dict[str, str] = {}
    nodes = []
    for r in sorted(rows, key=lambda x: x["id"]):
        public = r["project"] in PUBLIC_PROJECTS
        if public:
            pid, title, proj = r["id"], r["title"], r["project"]
        else:
            pid = anon_page.setdefault(r["id"], f"private-{len(anon_page) + 1}")
            title = None
            if r["project"]:
                proj = anon_proj.setdefault(
                    r["project"], f"private project {len(anon_proj) + 1}")
            else:
                proj = None
        nodes.append({"id": pid, "title": title, "type": r["type"],
                      "project": proj, "claims": claims.get(r["id"], 0),
                      "public": public})

    node_ids = {n["id"] for n in nodes}
    public_ids = {n["id"] for n in nodes if n["public"]}

    def _pid(raw: str) -> str | None:
        if raw in node_ids:
            return raw
        return anon_page.get(raw)

    links = []
    for e in edges:
        s, d = _pid(e["src_page_id"]), _pid(e["dst_page_id"])
        if s and d:
            links.append({"source": s, "target": d, "rel": e["rel"]})

    # Claims as satellite neurons: every verified fact orbits its page.
    # Public pages expose the claim text; private pages contribute anonymous
    # dots (the brain's true density shows, content never does).
    # Claim node ids are ORDINAL, never the raw claim id — the claims table
    # uses semantic string ids that embed private project names.
    claim_rows = conn.execute(
        "SELECT id, page_id, text FROM claims WHERE status='active' ORDER BY id"
    ).fetchall()
    for i, c in enumerate(claim_rows):
        parent = _pid(c["page_id"])
        if parent is None:
            continue
        public = parent in public_ids
        cid = f"fact-{i + 1}"
        nodes.append({
            "id": cid, "kind": "claim", "parent": parent, "public": public,
            "text": sanitize(c["text"] or "")[:280] if public else None,
        })
        links.append({"source": parent, "target": cid, "rel": "claim"})
    for n in nodes:
        n.setdefault("kind", "page")
    return {"nodes": nodes, "links": links}


def demo_retrievals(store: Store) -> list[dict]:
    out = []
    for query in DEMO_QUERIES:
        res = retrieve(store, query, k=3)
        out.append({
            "query": query,
            "results": [
                {"page_id": p.page_id, "title": p.title, "type": p.type,
                 "project": p.project, "score": p.score,
                 "public": p.project in PUBLIC_PROJECTS}
                for p in res.pages
            ],
        })
    return out


def brain_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ── HTML rendering (no dependencies — tiny markdown subset) ─────────────────

def md_to_html(md: str) -> str:
    out, in_code, in_list = [], False, False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append("<pre>" if in_code else "</pre>")
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
        if esc.startswith("### "):
            out.append(f"<h4>{esc[4:]}</h4>")
        elif esc.startswith("## "):
            out.append(f"<h3>{esc[3:]}</h3>")
        elif esc.startswith("# "):
            out.append(f"<h2>{esc[2:]}</h2>")
        elif esc.strip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc.strip()[2:]}</li>")
            continue
        elif esc.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{esc}</p>")
        if in_list and not esc.strip().startswith(("- ", "* ")):
            out.insert(-1, "</ul>")
            in_list = False
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# Plain-language meaning of each page type — shown in the map's detail panel.
TYPE_EXPLAIN = {
    "overview": "What a project IS — the summary page the AI reads first when "
                "asked about it.",
    "structure": "The project's map — how its files and modules are organized.",
    "history": "The project's story over time, distilled from its git commits.",
    "decisions": "Key decisions and their reasoning, each backed by a cited "
                 "source.",
    "identity": "Who the human behind the brain is. Private — never exported.",
    "disposition": "How the human prefers to work and communicate. Private — "
                   "never exported.",
}


def render_html(stats: dict, pages: list[dict], demos: list[dict],
                graph: dict, commit: str, built_at: str) -> str:
    tiles = [
        ("Pages", stats["pages"], "knowledge pages (bubbles on the map)"),
        ("Claims", stats["claims"], "atomic facts with provenance"),
        ("Aliases", stats["aliases"], "names that route a query"),
        ("Edges", stats["edges"], "links between pages"),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="tile-label">{label}</div>'
        f'<div class="tile-value">{value}</div>'
        f'<div class="tile-sub">{sub}</div></div>'
        for label, value, sub in tiles
    )

    ingest_html = "".join(
        f'<span class="pill">{html.escape(op)} × {n}</span>'
        for op, n in sorted(stats["events_by_op"].items())
    )

    demos_html = ""
    for d in demos:
        rows = "".join(
            f'<tr><td><code>{html.escape(r["page_id"])}</code>'
            + ("" if r["public"] else " 🔒") + "</td>"
            f'<td>{html.escape(r["type"])}</td>'
            f'<td class="num">{r["score"]:g}</td></tr>'
            for r in d["results"]
        )
        demos_html += (
            f'<div class="demo"><div class="demo-q">“{html.escape(d["query"])}”</div>'
            f'<table><thead><tr><th>page</th><th>type</th>'
            f'<th class="num">score</th></tr></thead><tbody>{rows}</tbody></table></div>'
        )

    pages_html = ""
    for p in pages:
        pages_html += (
            f'<details class="page" id="page-{html.escape(p["id"])}">'
            f'<summary><strong>{html.escape(p["title"])}</strong>'
            f' <span class="meta">{html.escape(p["project"])} · {html.escape(p["type"])}'
            f' · updated {html.escape(str(p["updated"]))}'
            f' · <a href="pages/{html.escape(p["id"])}.md">raw</a></span></summary>'
            f'<div class="page-body">{md_to_html(p["markdown"])}</div></details>'
        )

    graph_json = json.dumps(graph)
    type_explain_json = json.dumps(TYPE_EXPLAIN)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Optimus Brain — Interactive Map</title>
<meta name="description" content="An interactive map of Optimus: the memory layer behind Aegis Finance. English-only, machine-readable.">
<style>
:root {{
  --bg: #FAFAF7; --surface: #FFFFFF; --ink: #1A1A1A; --ink-2: #52525B;
  --ink-3: #8E8E93; --line: #E4E4E0; --accent: #2C6E8F;
  --good-bg: #E7F2E9; --good-ink: #276236; --lock-bg: #F1F0EC;
  --c-overview: #2a78d6; --c-structure: #1baf7a; --c-history: #eda100;
  --c-decisions: #4a3aa7; --c-personal: #e34948; --c-private: #9a9a96;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #121214; --surface: #1C1C1F; --ink: #ECECEA; --ink-2: #A9A9B2;
    --ink-3: #77777F; --line: #2C2C30; --accent: #6FB1D0;
    --good-bg: #1E2F23; --good-ink: #8CC79A; --lock-bg: #232326;
    --c-overview: #3987e5; --c-structure: #199e70; --c-history: #c98500;
    --c-decisions: #9085e9; --c-personal: #e66767; --c-private: #6e6e74; }}
}}
* {{ box-sizing: border-box; margin: 0; }}
body {{ background: var(--bg); color: var(--ink); font: 16px/1.6 ui-sans-serif,
  system-ui, "Segoe UI", sans-serif; padding: 0 16px 80px; }}
main {{ max-width: 960px; margin: 0 auto; }}
header {{ padding: 40px 0 8px; }}
h1 {{ font-size: 28px; letter-spacing: -0.02em; }}
h2 {{ font-size: 20px; margin: 40px 0 12px; letter-spacing: -0.01em; }}
p.lede {{ color: var(--ink-2); max-width: 68ch; }}
.map-wrap {{ display: grid; grid-template-columns: 1fr 300px; gap: 12px;
  margin-top: 16px; }}
@media (max-width: 760px) {{ .map-wrap {{ grid-template-columns: 1fr; }} }}
#map-card {{ background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; overflow: hidden; position: relative; }}
#brainmap {{ display: block; width: 100%; height: 480px; cursor: grab; }}
#map-hint {{ position: absolute; left: 12px; bottom: 10px; font-size: 12.5px;
  color: var(--ink-3); pointer-events: none; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 10px 16px; padding: 10px 14px;
  border-top: 1px solid var(--line); font-size: 13px; color: var(--ink-2); }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.dot {{ width: 11px; height: 11px; border-radius: 50%; display: inline-block; }}
#panel {{ background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; padding: 16px; font-size: 14.5px; align-self: start;
  position: sticky; top: 12px; }}
#panel h3 {{ font-size: 16px; margin-bottom: 6px; }}
#panel .meta {{ color: var(--ink-3); font-size: 12.5px; }}
#panel p {{ margin-top: 8px; color: var(--ink-2); }}
#panel a {{ color: var(--accent); }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr));
  gap: 12px; margin-top: 16px; }}
.tile {{ background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 14px 16px; }}
.tile-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--ink-3); }}
.tile-value {{ font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums;
  margin: 2px 0; }}
.tile-sub {{ font-size: 12.5px; color: var(--ink-2); }}
.card {{ background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 18px 20px; margin-top: 12px; }}
.flow {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  font-size: 14.5px; color: var(--ink-2); margin-top: 8px; }}
.flow b {{ color: var(--ink); font-weight: 600; }}
.flow .arrow {{ color: var(--ink-3); }}
.pill {{ display: inline-block; background: var(--lock-bg); border-radius: 999px;
  padding: 2px 10px; font-size: 13px; color: var(--ink-2); margin: 2px 4px 2px 0; }}
ul {{ padding-left: 22px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14.5px; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); }}
th {{ color: var(--ink-3); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.05em; font-weight: 600; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.demo {{ margin-top: 14px; }}
.demo-q {{ font-weight: 600; margin-bottom: 6px; }}
details.page {{ background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px 16px; margin-top: 10px; }}
details.page summary {{ cursor: pointer; }}
.meta {{ color: var(--ink-3); font-size: 13px; }}
.page-body {{ border-top: 1px solid var(--line); margin-top: 10px; padding-top: 10px;
  font-size: 15px; overflow-x: auto; }}
.page-body h2, .page-body h3, .page-body h4 {{ margin: 14px 0 6px; }}
pre {{ background: var(--lock-bg); border-radius: 8px; padding: 10px 12px;
  overflow-x: auto; font-size: 13px; }}
code {{ font: 13.5px/1.5 ui-monospace, "Cascadia Code", monospace;
  background: var(--lock-bg); border-radius: 4px; padding: 1px 4px; }}
pre code {{ background: none; padding: 0; }}
a {{ color: var(--accent); }}
footer {{ margin-top: 48px; color: var(--ink-3); font-size: 13px; }}
</style>
</head>
<body>
<main>
<header>
  <h1>🧠 Optimus Brain — interactive map</h1>
  <p class="lede">Optimus is the persistent memory layer behind
  <strong>Aegis Finance</strong>. Everything it knows lives in markdown
  "pages" connected by links — this map shows the whole brain. <strong>Big
  bubbles are pages</strong> (color = page type); <strong>every small dot
  orbiting a page is one verified fact</strong> it holds, and the moving
  pulses trace how retrieval walks the links. Gray means private — you can
  see those neurons exist, never what's inside. Click anything: pages explain
  themselves, public facts show their text. All content is English.</p>
</header>

<h2>The brain, mapped</h2>
<div class="map-wrap">
  <div id="map-card">
    <canvas id="brainmap"></canvas>
    <div id="map-hint">drag bubbles · click for details</div>
    <div class="legend">
      <span><i class="dot" style="background:var(--c-overview)"></i>overview</span>
      <span><i class="dot" style="background:var(--c-structure)"></i>structure</span>
      <span><i class="dot" style="background:var(--c-history)"></i>history</span>
      <span><i class="dot" style="background:var(--c-decisions)"></i>decisions</span>
      <span><i class="dot" style="background:var(--c-personal)"></i>identity/disposition</span>
      <span><i class="dot" style="background:var(--c-private)"></i>private (anonymized)</span>
    </div>
  </div>
  <aside id="panel">
    <h3>Click a bubble</h3>
    <p>Every bubble is one knowledge page. Bigger bubble = more verified facts
    inside. The two clusters on the map are the public Aegis projects; the
    gray bubbles are the private rest of the brain.</p>
  </aside>
</div>

<h2>How it digests information</h2>
<div class="card">
  <div class="flow"><b>1 · ingest</b><span class="arrow">→</span>
    <span>git repos &amp; folders are read and turned into typed pages
    (overview / structure / history / decisions), each fact cited back to its
    source</span></div>
  <div class="flow"><b>2 · index</b><span class="arrow">→</span>
    <span>pages, facts, name-aliases and links land in one SQLite index;
    every operation is logged</span></div>
  <div class="flow"><b>3 · retrieve</b><span class="arrow">→</span>
    <span>questions are answered by deterministic scoring (no AI guessing at
    this step — same question, same answer, always cited)</span></div>
  <div class="flow"><b>4 · serve</b><span class="arrow">→</span>
    <span>AI sessions (Claude, DeepSeek, any agent) consult it through MCP
    tools like <code>brain_query</code> instead of re-reading whole
    repositories</span></div>
  <p style="margin-top:10px; color: var(--ink-2); font-size: 14px;">
  Operations recorded so far: {ingest_html}</p>
</div>

<h2>Corpus at a glance</h2>
<div class="tiles">{tile_html}</div>

<h2>Retrieval, demonstrated (real output)</h2>
<div class="card">
  <p style="font-size:14px; color: var(--ink-2);">Each query below was run
  through the actual retrieval engine at build time. Higher score = better
  match. 🔒 marks a private page — it can be <em>found</em>, but its content
  is never exported here.</p>
  {demos_html}
</div>

<h2>Public knowledge pages (full text)</h2>
{pages_html}

<h2>For AI agents</h2>
<div class="card">
  <p>Everything public on this page is machine-readable, English, CORS-open:</p>
  <ul>
    <li><code>GET /brain.json</code> — stats, graph, public pages (full markdown), retrieval demos</li>
    <li><code>GET /llms.txt</code> — plain-text index of what is here and how to use it</li>
    <li><code>GET /pages/&lt;id&gt;.md</code> — each public page raw</li>
  </ul>
  <pre><code>curl -s https://optimus-brain-alpha.vercel.app/brain.json | jq '.stats'</code></pre>
  <p style="font-size:14px; color: var(--ink-2);">This export is a static
  snapshot — it changes only when the showcase is rebuilt, and the build ONLY
  reads the brain (the store is opened read-only).</p>
</div>

<footer>
  Snapshot of brain @ git <code>{commit}</code> · built {built_at} ·
  Optimus is read-only here; the live brain runs locally with Aegis Finance.
</footer>
</main>

<script>
const GRAPH = {graph_json};
const TYPE_EXPLAIN = {type_explain_json};

const canvas = document.getElementById("brainmap");
const panel = document.getElementById("panel");
const ctx = canvas.getContext("2d");
const css = (v) => getComputedStyle(document.documentElement)
  .getPropertyValue(v).trim();

function typeColor(n) {{
  if (n.kind === "claim") {{
    const parent = byId[n.parent];
    return parent ? typeColor(parent) : css("--c-private");
  }}
  if (!n.public) return css("--c-private");
  if (n.type === "overview") return css("--c-overview");
  if (n.type === "structure") return css("--c-structure");
  if (n.type === "history") return css("--c-history");
  if (n.type === "decisions") return css("--c-decisions");
  return css("--c-personal");
}}

// layout state
let W = 0, H = 0, DPR = 1;
const nodes = GRAPH.nodes.map((n, i) => ({{
  ...n,
  r: n.kind === "claim" ? 3.5 : 10 + Math.sqrt(n.claims || 0) * 3.2,
  x: 0, y: 0, vx: 0, vy: 0, seed: i
}}));
const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
const links = GRAPH.links
  .map(l => ({{ s: byId[l.source], t: byId[l.target], rel: l.rel }}))
  .filter(l => l.s && l.t);

function resize() {{
  DPR = window.devicePixelRatio || 1;
  W = canvas.clientWidth; H = 480;
  canvas.width = W * DPR; canvas.height = H * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}}
resize();
window.addEventListener("resize", resize);

// deterministic initial placement: pages on a ring (public cluster left),
// claims scattered around their parent page
nodes.filter(n => n.kind === "page").forEach((n, i, pages) => {{
  const a = (i / pages.length) * Math.PI * 2;
  const cx = n.public ? 0.36 : 0.66;
  n.x = W * cx + Math.cos(a) * 90 + (i % 3) * 7;
  n.y = H * 0.5 + Math.sin(a) * 120 + (i % 5) * 5;
}});
nodes.filter(n => n.kind === "claim").forEach((n, i) => {{
  const p = byId[n.parent];
  const a = (i * 2.399963) % (Math.PI * 2); // golden angle scatter
  n.x = (p ? p.x : W / 2) + Math.cos(a) * 34;
  n.y = (p ? p.y : H / 2) + Math.sin(a) * 34;
}});

let dragging = null, hover = null, alpha = 1;

function step() {{
  // forces: repulsion, springs on links, mild center gravity
  for (let i = 0; i < nodes.length; i++) {{
    const a = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {{
      const b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      let d2 = dx * dx + dy * dy || 1;
      const min = (a.r + b.r + (a.kind === "claim" || b.kind === "claim" ? 4 : 14));
      // tiny claim nodes repel weakly; pages keep their spacing
      const scale = (a.kind === "claim" ? 0.18 : 1) * (b.kind === "claim" ? 0.18 : 1);
      const f = Math.min(2600 * scale / d2, 0.9) + (d2 < min * min ? 0.5 : 0);
      const d = Math.sqrt(d2);
      dx /= d; dy /= d;
      a.vx -= dx * f; a.vy -= dy * f;
      b.vx += dx * f; b.vy += dy * f;
    }}
    // gravity: pages toward their cluster; claims toward their parent
    if (a.kind === "claim") {{
      const p = byId[a.parent];
      if (p) {{ a.vx += (p.x - a.x) * 0.02; a.vy += (p.y - a.y) * 0.02; }}
    }} else {{
      const gx = W * (a.public ? 0.36 : 0.68), gy = H * 0.5;
      a.vx += (gx - a.x) * 0.004; a.vy += (gy - a.y) * 0.004;
    }}
  }}
  for (const l of links) {{
    let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 1;
    const want = l.rel === "claim" ? l.s.r + 26 : l.s.r + l.t.r + 46;
    const f = (d - want) * 0.012;
    dx /= d; dy /= d;
    l.s.vx += dx * f * d * 0.02; l.s.vy += dy * f * d * 0.02;
    l.t.vx -= dx * f * d * 0.02; l.t.vy -= dy * f * d * 0.02;
  }}
  for (const n of nodes) {{
    if (n === dragging) {{ n.vx = 0; n.vy = 0; continue; }}
    n.vx *= 0.86; n.vy *= 0.86;
    n.x += n.vx * alpha; n.y += n.vy * alpha;
    n.x = Math.max(n.r + 4, Math.min(W - n.r - 4, n.x));
    n.y = Math.max(n.r + 4, Math.min(H - n.r - 4, n.y));
  }}
}}

function draw(now) {{
  ctx.clearRect(0, 0, W, H);
  const ink = css("--ink"), ink3 = css("--ink-3"), surface = css("--surface");

  ctx.lineWidth = 1.1;
  for (const l of links) {{
    ctx.strokeStyle = css("--line");
    ctx.globalAlpha = l.rel === "claim" ? 0.55 : 1;
    ctx.beginPath(); ctx.moveTo(l.s.x, l.s.y); ctx.lineTo(l.t.x, l.t.y);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }}

  // signal pulses traveling along the links — the "thinking" effect
  for (let i = 0; i < links.length; i++) {{
    const l = links[i];
    const period = l.rel === "claim" ? 4200 : 2600;
    const phase = ((now / period) + i * 0.37) % 1;
    const px = l.s.x + (l.t.x - l.s.x) * phase;
    const py = l.s.y + (l.t.y - l.s.y) * phase;
    ctx.beginPath();
    ctx.arc(px, py, l.rel === "claim" ? 1.3 : 2.1, 0, Math.PI * 2);
    ctx.fillStyle = typeColor(l.t);
    ctx.globalAlpha = 0.7 * Math.sin(phase * Math.PI);
    ctx.fill();
    ctx.globalAlpha = 1;
  }}

  for (const n of nodes) {{
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    ctx.fillStyle = typeColor(n);
    ctx.globalAlpha = n.kind === "claim"
      ? (n.public ? 0.75 : 0.35)
      : (n.public ? 0.92 : 0.55);
    ctx.fill();
    ctx.globalAlpha = 1;
    if (n.kind !== "claim") {{
      // 2px surface ring so overlapping bubbles stay separable
      ctx.lineWidth = 2; ctx.strokeStyle = surface; ctx.stroke();
    }}
    if (n === hover) {{
      ctx.lineWidth = 2.5; ctx.strokeStyle = ink; ctx.stroke();
    }}
  }}
  // labels for public PAGE bubbles (text in ink, never series color)
  ctx.font = "12px ui-sans-serif, system-ui";
  ctx.textAlign = "center";
  for (const n of nodes) {{
    if (!n.public || n.kind === "claim") continue;
    const label = n.id.replace("aegis-finance-", "").replace(
      "aegis-quant-knowledge-", "quant-");
    ctx.fillStyle = ink;
    ctx.fillText(label, n.x, n.y + n.r + 14);
  }}
  ctx.fillStyle = ink3;
  ctx.fillText("public: Aegis projects", W * 0.36, 20);
  ctx.fillText("private (anonymized)", W * 0.68, 20);
}}

function loop(now) {{ step(); draw(now || 0); requestAnimationFrame(loop); }}
requestAnimationFrame(loop);

function nodeAt(x, y) {{
  for (let i = nodes.length - 1; i >= 0; i--) {{
    const n = nodes[i];
    const dx = x - n.x, dy = y - n.y;
    if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
  }}
  return null;
}}
function pos(e) {{
  const r = canvas.getBoundingClientRect();
  const p = e.touches ? e.touches[0] : e;
  return [p.clientX - r.left, p.clientY - r.top];
}}

canvas.addEventListener("mousemove", (e) => {{
  const [x, y] = pos(e);
  if (dragging) {{ dragging.x = x; dragging.y = y; return; }}
  hover = nodeAt(x, y);
  canvas.style.cursor = hover ? "pointer" : "grab";
}});
canvas.addEventListener("mousedown", (e) => {{
  const [x, y] = pos(e);
  dragging = nodeAt(x, y);
}});
window.addEventListener("mouseup", () => {{ dragging = null; }});
canvas.addEventListener("click", (e) => {{
  const [x, y] = pos(e);
  const n = nodeAt(x, y);
  if (n) showPanel(n);
}});
canvas.addEventListener("touchstart", (e) => {{
  const [x, y] = pos(e);
  const n = nodeAt(x, y);
  if (n) showPanel(n);
}}, {{ passive: true }});

function esc(s) {{
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}}

function showPanel(n) {{
  if (n.kind === "claim") {{
    const parent = byId[n.parent];
    if (n.public && n.text) {{
      panel.innerHTML =
        "<h3>Verified fact</h3>" +
        '<div class="meta">from ' + esc(parent ? parent.title : n.parent) + "</div>" +
        "<p>“" + esc(n.text) + "”</p>" +
        "<p style='font-size:13px'>Every small dot is one fact the brain " +
        "holds, cited back to its source at ingest time.</p>";
    }} else {{
      panel.innerHTML =
        "<h3>🔒 Private fact</h3>" +
        "<p>A verified fact inside a private page — it exists on the map so " +
        "the brain's density is honest, but its content never leaves the " +
        "local machine.</p>";
    }}
    return;
  }}
  const explain = TYPE_EXPLAIN[n.type] || "A knowledge page.";
  const conn = links.filter(l => l.rel !== "claim" && (l.s === n || l.t === n)).length;
  if (n.public) {{
    panel.innerHTML =
      "<h3>" + esc(n.title) + "</h3>" +
      '<div class="meta">' + esc(n.project) + " · " + esc(n.type) +
      " · " + n.claims + " verified fact" + (n.claims === 1 ? "" : "s") +
      " · " + conn + " link" + (conn === 1 ? "" : "s") + "</div>" +
      "<p>" + esc(explain) + "</p>" +
      '<p><a href="#page-' + esc(n.id) + '" onclick="document.getElementById(' +
      "'page-" + esc(n.id) + "'" + ').open = true">Read the full page below ↓</a></p>';
  }} else {{
    panel.innerHTML =
      "<h3>🔒 Private page</h3>" +
      '<div class="meta">' + esc(n.project || "personal") + " · " + esc(n.type) +
      " · " + n.claims + " fact" + (n.claims === 1 ? "" : "s") + "</div>" +
      "<p>" + esc(explain) + "</p>" +
      "<p>Private pages exist on the map so you can see the brain's true " +
      "shape — but their titles and contents are excluded from this export " +
      "by construction.</p>";
  }}
}}
</script>
</body>
</html>
"""


def main() -> None:
    store = Store(ROOT, read_only=True)
    conn = store._conn
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    stats = corpus_stats(conn)
    pages = public_pages(conn)
    demos = demo_retrievals(store)
    graph = graph_data(conn)
    commit = brain_commit()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(exist_ok=True)

    for p in pages:
        (OUT / "pages" / f"{p['id']}.md").write_text(p["markdown"], encoding="utf-8")

    brain_json = {
        "what": "Public read-only snapshot of the Optimus brain (memory layer "
                "behind Aegis Finance). English-only. Private pages excluded; "
                "they appear only as anonymized graph nodes and counts.",
        "built_at": built_at, "brain_commit": commit,
        "stats": stats,
        "graph": graph,
        "public_pages": pages,
        "retrieval_demos": demos,
        "how_to_use": {
            "for_ai_agents": "Fetch this file. `public_pages[*].markdown` is "
                             "the full knowledge text. `graph` is the page map "
                             "(private nodes anonymized). Answer questions "
                             "from it in English; cite page ids.",
            "raw_pages": "GET /pages/<id>.md",
        },
    }
    (OUT / "brain.json").write_text(
        json.dumps(brain_json, indent=1, ensure_ascii=False), encoding="utf-8")

    llms = ["# Optimus Brain — public snapshot (English)",
            f"# built {built_at} · brain @ {commit}", "",
            "This host is a read-only export of the Optimus memory layer",
            "behind Aegis Finance. Machine endpoints:", "",
            "  /brain.json      full public snapshot (stats + graph + pages + demos)",
            "  /pages/<id>.md   raw public knowledge pages:", ""]
    llms += [f"    /pages/{p['id']}.md  — {p['title']}" for p in pages]
    llms += ["", "Private content (identity, dispositions, personal projects)",
             "is excluded by construction — anonymized graph nodes and",
             "aggregate counts only."]
    (OUT / "llms.txt").write_text("\n".join(llms), encoding="utf-8")

    (OUT / "vercel.json").write_text(json.dumps({
        "headers": [{
            "source": "/(brain.json|llms.txt|pages/.*)",
            "headers": [
                {"key": "Access-Control-Allow-Origin", "value": "*"},
                {"key": "Cache-Control", "value": "public, max-age=3600"},
            ],
        }],
    }, indent=1), encoding="utf-8")

    (OUT / "index.html").write_text(
        render_html(stats, pages, demos, graph, commit, built_at),
        encoding="utf-8")

    store.close()
    print(f"showcase built -> {OUT}")
    print(f"  pages exported: {[p['id'] for p in pages]}")
    print(f"  graph: {len(graph['nodes'])} nodes / {len(graph['links'])} links")
    print(f"  stats: {stats['pages']} pages / {stats['claims']} claims")


if __name__ == "__main__":
    main()
