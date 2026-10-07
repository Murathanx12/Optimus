"""Build the PUBLIC Optimus brain showcase — a static site for Vercel.

Reads the brain STRICTLY read-only and exports ONLY the public slice:
  - an interactive brain MAP (every page is a neuron; private pages are
    anonymized — shape visible, content never)
  - aggregate corpus stats (counts by tier/type/project, event log ops)
  - the aegis-finance + aegis-quant-knowledge project pages (full text)
  - real retrieval-demo output (deterministic, LLM-free scoring)

NEVER exported: identity/disposition content, conversations, and every
non-aegis project's content (coursework, personal portfolio, hobbies) — those
appear only as anonymous neurons/counts. All output is English.

Outputs into showcase/optimus-brain/ (the Vercel deploy root):
  index.html   — human view (neural map + explanations)
  brain.json   — machine view (CORS: *) for DeepSeek/Claude/any agent
  llms.txt     — plain-text index for LLM agents
  pages/*.md   — raw public pages
  vercel.json  — static config + CORS headers

Usage (from the optimus repo root):
  python showcase/build.py              rebuild everything from the brain DB
  python showcase/build.py --from-json  re-render ONLY index.html from the
                                        committed brain.json; the brain DB is
                                        not opened and nothing else is written

The page speaks the Aegis visual language of 2026-10-07 (style C "orbit" for
the map, style A "blackline" for the explanation cards): pure black, white
ink, blue for forward flow, orange ONLY for the query signal. The map is laid
out from a DECLARED taxonomy (MAP_RINGS), never a physics simulation, so the
same brain.json draws the same picture on every load.
"""

from __future__ import annotations

import argparse
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


# ── The map's declared taxonomy (no physics, ever) ───────────────────────────
# The force graph this page used to draw never stopped moving: a force layout
# invents distances the brain does not hold, and it has no fixed point, so the
# neurons kept pushing each other. Every page is now placed by two declared
# rules and nothing else:
#   ring     what the page is FOR (its type), looked up in MAP_RINGS
#   bearing  which project it belongs to: one equal sector per project,
#            public projects first (PUBLIC_PROJECTS order, centred on the top
#            of the dial), private projects clockwise after them in their
#            anonymised ordinal order
# Claims are not placed here: the page draws each one as a bead on a fixed
# slot of its page's dendrites (slot = its order among that page's claims).
# Same brain.json -> same picture, on every load and every day. A new page
# type moves nothing until it is declared here; until then it waits on the
# fallback ring.
#
# Why these rings: identity and disposition span every project, so they sit
# at the one point equidistant from all of them (and they are private, so the
# centre is two anonymous neurons). Structure is the inner ring, the story of
# a project (its decisions and history) the middle one, and the overview — the
# hub page an AI reads first, where most facts gather — the outer ring, so its
# dendrites have open space to fan into instead of crowding the centre.
MAP_RINGS: tuple[dict, ...] = (
    {"key": "self", "label": "SELF", "types": ("identity", "disposition"),
     "r": 0.075, "centre": True},
    {"key": "structure", "label": "STRUCTURE", "types": ("structure",),
     "r": 0.36},
    {"key": "story", "label": "DECISIONS · HISTORY",
     "types": ("decisions", "history"), "r": 0.60},
    {"key": "overview", "label": "OVERVIEW", "types": ("overview",),
     "r": 0.84},
)
MAP_FALLBACK_RING = "story"
# Share of one sector's width that pages sharing a ring AND a project fan out
# across (two such pages sit at +/-14% of the sector from its centre line).
MAP_SECTOR_SPREAD = 0.56


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def map_layout(graph: dict) -> dict:
    """Polar position of every PAGE on the map, from the declared taxonomy.

    Returns the rings, one sector per project (with its bearing), and per page
    its ring, its radius (a fraction of the drawable radius) and its bearing
    in degrees (0 = east, clockwise, as on screen). Also the bearing queries
    enter along (the sector boundary nearest the top) and the bearing ring
    labels are printed along (the boundary nearest the bottom). A pure
    function of the graph: no clock, no randomness, no layout pass.
    """
    ring_of_type = {t: i for i, ring in enumerate(MAP_RINGS)
                    for t in ring["types"]}
    fallback = next(i for i, ring in enumerate(MAP_RINGS)
                    if ring["key"] == MAP_FALLBACK_RING)
    pages = [n for n in graph["nodes"] if n.get("kind", "page") == "page"]
    ring_of = {p["id"]: ring_of_type.get(p["type"], fallback) for p in pages}

    def sector_key(p: dict) -> str | None:
        if MAP_RINGS[ring_of[p["id"]]].get("centre"):
            return None
        return p["project"] or ""

    seen: list[str] = []
    for p in pages:
        key = sector_key(p)
        if key is not None and key not in seen:
            seen.append(key)
    public = [k for k in PUBLIC_PROJECTS if k in seen]
    order = public + [k for k in seen if k not in PUBLIC_PROJECTS]
    step = 360.0 / max(len(order), 1)
    first = (-90.0 - (len(public) - 1) / 2 * step) if public else -90.0 + step / 2

    sectors = []
    for k, key in enumerate(order):
        label = (key or "no project").replace("-", " ").upper()
        m = re.fullmatch(r"PRIVATE PROJECT (\d+)", label)
        sectors.append({
            "key": key, "label": label,
            "short": f"PRIVATE {m.group(1)}" if m else label,
            "public": key in PUBLIC_PROJECTS,
            "a": round(first + k * step, 3),
        })
    index_of = {key: k for k, key in enumerate(order)}

    groups: dict[tuple[int, str | None], list[dict]] = {}
    for p in pages:
        groups.setdefault((ring_of[p["id"]], sector_key(p)), []).append(p)
    placed: dict[str, dict] = {}
    for (ring, key), members in groups.items():
        types = MAP_RINGS[ring]["types"]
        members.sort(key=lambda p: (types.index(p["type"]) if p["type"] in types
                                    else len(types), p["id"]))
        m = len(members)
        for i, p in enumerate(members):
            if key is None:          # the centre: evenly round the middle
                a, sector = 180.0 + i * 360.0 / m, None
            else:
                off = 0.0 if m == 1 else (i / (m - 1) - 0.5) * MAP_SECTOR_SPREAD * step
                a, sector = sectors[index_of[key]]["a"] + off, index_of[key]
            placed[p["id"]] = {"ring": ring, "r": MAP_RINGS[ring]["r"],
                               "a": round(a, 3), "sector": sector}

    bounds = [first + (k + 0.5) * step for k in range(len(order))] or [-90.0]
    port = min(bounds, key=lambda b: (_angle_gap(b, -90.0), b))
    ring_label = min(bounds, key=lambda b: (_angle_gap(b, 90.0), b))
    return {
        "rings": [{"key": r["key"], "label": r["label"], "r": r["r"],
                   "centre": bool(r.get("centre"))} for r in MAP_RINGS],
        "sectors": sectors,
        "pages": placed,
        "query_port": round(port, 3),
        "ring_label_bearing": round(ring_label, 3),
    }


def _split_front_matter(md: str) -> tuple[str | None, str]:
    """('id: ...\\n...', rest) for a page that opens with a YAML block."""
    if not md.startswith("---\n"):
        return None, md
    end = md.find("\n---", 4)
    if end < 0:
        return None, md
    close = md.find("\n", end + 4)
    return md[4:end], (md[close + 1:] if close >= 0 else "")


def page_body_html(md: str) -> str:
    """A public page: its front-matter (claims + sources) as a folded block,
    then the markdown body."""
    fm, body = _split_front_matter(md)
    head = ""
    if fm is not None:
        head = ('<details class="fm"><summary>front-matter · claims and '
                f'sources</summary><pre>{html.escape(fm)}</pre></details>\n')
    return head + md_to_html(body)


# The four steps of "how it digests information". Every module path printed
# here is checked to exist by tests/test_showcase.py, so the page cannot drift
# from the code. The retrieve step is the orange one: it is the query signal
# the map replays.
PIPELINE: tuple[tuple[str, str, str, bool], ...] = (
    ("Ingest", "Git repos and folders are read and turned into typed pages "
     "(overview, structure, history, decisions), each fact cited back to its "
     "source.", "core/ingest.py", False),
    ("Index", "Pages, facts, name-aliases and links land in one SQLite index; "
     "every operation is logged.", "core/store.py", False),
    ("Retrieve", "Questions are answered by deterministic scoring: no AI "
     "guessing at this step. Same question, same answer, always cited.",
     "core/query.py", True),
    ("Serve", "AI sessions (Claude, DeepSeek, any agent) consult it through "
     "MCP tools like brain_query instead of re-reading whole repositories.",
     "mcp/server.py", False),
)

TILES = (
    ("Pages", "pages", "knowledge pages (the neurons on the map)"),
    ("Claims", "claims", "atomic facts with provenance (the beads)"),
    ("Aliases", "aliases", "names that route a query"),
    ("Edges", "edges", "links between pages (the axons)"),
)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _score_bar(score: float, top: float) -> str:
    pct = 0.0 if top <= 0 else max(0.0, min(100.0, 100.0 * score / top))
    return f'<span class="bar"><i style="width:{pct:.1f}%"></i></span>'


def _result_label(r: dict) -> str:
    """A retrieval hit as printed: its id when public; never a private id."""
    if r.get("public"):
        return f'<code>{html.escape(r["page_id"])}</code>'
    return '<span class="tag">private</span>private page'


def _readout_html(demos: list[dict]) -> str:
    """The replay readout under the map, filled with the first query so the
    page is complete before (and without) any script or motion."""
    if not demos:
        return ('<div class="ro-head" id="ro-head">no retrieval demo in this '
                'snapshot</div><div class="ro-q" id="ro-q"></div>'
                '<ol class="ro-list" id="ro-list"></ol>')
    d = demos[0]
    top = max((r["score"] for r in d["results"]), default=0)
    rows = "".join(
        f'<li class="shown"><span class="rk">#{i + 1}</span>'
        f'<span class="pid">{_result_label(r)}'
        f'<span class="ty">{html.escape(r["type"])}</span></span>'
        f'{_score_bar(r["score"], top)}<span class="sc">{r["score"]:g}</span></li>'
        for i, r in enumerate(d["results"]))
    return (f'<div class="ro-head" id="ro-head">query 01 / {len(demos):02d} · '
            'ranked by the real retrieval engine</div>'
            f'<div class="ro-q" id="ro-q">“{html.escape(d["query"])}”</div>'
            f'<ol class="ro-list" id="ro-list">{rows}</ol>')


def _json_for_script(obj: object) -> str:
    """JSON that is safe inside <script type="application/json">: no '<', '>'
    or '&' survive literally, so no fact text can close the tag."""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


_CSS = r"""
:root {
  --bg: #000000;
  --ink: #ffffff;
  --ink-2: rgba(255, 255, 255, .68);
  --ink-3: rgba(255, 255, 255, .46);
  --line: rgba(255, 255, 255, .10);
  --line-2: rgba(255, 255, 255, .20);
  --blue: #4a8dff;
  --blue-hi: #6fb0ff;
  --orange: #ff8a1f;
  --orange-hi: #ffb36b;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  color-scheme: dark;
}
@property --bracket { syntax: "<color>"; inherits: true; initial-value: rgba(255, 255, 255, .55); }
* { box-sizing: border-box; margin: 0; }
html { background: var(--bg); }
body { background: var(--bg); color: var(--ink); font: 16px/1.6 var(--sans);
  -webkit-font-smoothing: antialiased; padding: 0 16px 80px; }
main { max-width: 1160px; margin: 0 auto; }
a { color: var(--blue-hi); text-decoration: none; border-bottom: 1px solid rgba(111, 176, 255, .35); }
a:hover { border-bottom-color: var(--blue-hi); }
code { font: 12.5px/1.5 var(--mono); color: var(--ink); background: rgba(255, 255, 255, .06);
  padding: 1px 5px; border-radius: 2px; }
pre { font: 12.5px/1.6 var(--mono); color: var(--ink-2); background: rgba(255, 255, 255, .03);
  border: 1px solid var(--line); padding: 12px 14px; overflow-x: auto; }
pre code { background: none; padding: 0; color: inherit; }
::selection { background: rgba(74, 141, 255, .35); }
.kicker, .sec-n, .ctl-label, .p-k, .p-meta, .t-k, .d-k, .ro-head, .pg-k, .st-n, .lk,
.metarow, footer, .tag, .op { font-family: var(--mono); text-transform: uppercase; }

/* style A: hairline frame + 12 px corner brackets */
.hud { position: relative; border: 1px solid var(--line); --bracket: rgba(255, 255, 255, .55);
  background:
    linear-gradient(var(--bracket), var(--bracket)) left top / 12px 1.5px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) left top / 1.5px 12px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) right top / 12px 1.5px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) right top / 1.5px 12px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) left bottom / 12px 1.5px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) left bottom / 1.5px 12px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) right bottom / 12px 1.5px no-repeat,
    linear-gradient(var(--bracket), var(--bracket)) right bottom / 1.5px 12px no-repeat;
  background-origin: border-box; }

/* header */
header { padding: 56px 0 4px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.08fr);
  gap: 0 48px; align-items: start; }
header .h-text { padding-top: 4px; }
header .metarow { grid-column: 1 / -1; margin-top: 26px; padding-top: 14px; border-top: 1px solid var(--line); }
.kicker { font-size: 11px; letter-spacing: 3px; color: var(--ink-3); }
.kicker .sep { color: var(--blue); margin: 0 8px; }
.wordmark { font: 200 64px/1 var(--sans); letter-spacing: 22px; margin: 24px 0 16px; color: var(--ink); }
.tagline { font: 300 21px/1.4 var(--sans); color: var(--ink); }
.lede { font-size: 15.5px; color: var(--ink-2); max-width: 74ch; }
.lede strong { color: var(--ink); font-weight: 500; }
.lede .o { color: var(--orange-hi); }
.lede .b { color: var(--blue-hi); }
.metarow { display: flex; flex-wrap: wrap; gap: 6px 24px; margin-top: 18px; font-size: 11px;
  line-height: 1.6; letter-spacing: 1.8px; color: var(--ink-3); }
.metarow b { color: var(--blue-hi); font-weight: 400; }

/* sections */
section { margin-top: 76px; }
header + section { margin-top: 56px; }
.sec-head { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.sec-n { font-size: 11px; letter-spacing: 3px; color: var(--blue); }
.sec-head h2 { font: 300 26px/1.2 var(--sans); color: var(--ink); white-space: nowrap; }
.sec-head .rule { flex: 1; height: 1px; background: var(--line); min-width: 16px; }
.sec-sub { color: var(--ink-2); font-size: 14.5px; max-width: 76ch; margin: -6px 0 18px; }

/* the map */
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
.ctl-label { font-size: 10.5px; letter-spacing: 2.6px; color: var(--ink-3); margin-right: 6px; }
.chip { font: 11.5px/1.25 var(--mono); letter-spacing: .4px; color: var(--ink-2); background: transparent;
  border: 1px solid var(--line-2); border-radius: 0; padding: 7px 11px; cursor: pointer;
  transition: color .2s, border-color .2s; }
.chip:hover { color: var(--ink); border-color: rgba(255, 255, 255, .45); }
.chip:focus-visible { outline: 1px solid var(--blue-hi); outline-offset: 2px; }
.chip:disabled { cursor: default; color: var(--ink-3); border-color: var(--line); }
.qchip[aria-pressed="true"] { color: var(--orange-hi); border-color: var(--orange); }
.motion { margin-left: auto; text-transform: uppercase; letter-spacing: 1.6px; font-size: 10.5px; }
.motion[aria-pressed="true"] { color: var(--blue-hi); border-color: var(--blue); }
.map-grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
.map-col, .side-col { min-width: 0; }
.map-frame { padding: 6px; }
#map { position: relative; width: 100%; min-height: 300px; -webkit-tap-highlight-color: transparent; }
#map svg { display: block; width: 100%; height: auto; user-select: none; -webkit-user-select: none; }
.noscript { padding: 24px; color: var(--ink-2); font-size: 14px; }

#map .ring { fill: none; stroke: rgba(255, 255, 255, .085); stroke-width: 1; }
#map .ring.centre { stroke-dasharray: 2 3; stroke: rgba(255, 255, 255, .16); }
#map .tick { stroke: rgba(255, 255, 255, .24); stroke-width: 1; }
#map .port { stroke: var(--orange); stroke-width: 1.5; opacity: .6; }
#map .axon { fill: none; stroke: rgba(255, 255, 255, .28); stroke-width: 1.1; }
#map .ray { fill: rgba(255, 255, 255, .32); }
#map .ray.pv { fill: rgba(255, 255, 255, .17); }
#map .bead { fill: rgba(255, 255, 255, .9); }
#map .bead.pv { fill: rgba(255, 255, 255, .40); }
#map .mem { fill: none; stroke: rgba(255, 255, 255, .22); stroke-width: 1; }
#map .mem.pv { stroke: rgba(255, 255, 255, .10); }
#map .body { fill: var(--ink); }
#map .body.pv { fill: rgba(255, 255, 255, .06); stroke: rgba(255, 255, 255, .52); stroke-width: 1; }
#map .hglow { opacity: 0; transition: opacity .25s; }
#map .dm { transition: opacity .25s; }
#map svg.focus .dm:not(.on) { opacity: .16; }
#map .l-query { transition: opacity .25s; }
#map svg.focus .l-query { opacity: .3; }
#map .axon.on { stroke: var(--blue-hi); stroke-width: 1.4; }
#map .ray.on { fill: rgba(111, 176, 255, .7); }
#map .bead.on { fill: var(--blue-hi); }
#map .body.on { fill: var(--blue-hi); stroke: var(--blue-hi); }
#map .mem.on { stroke: rgba(111, 176, 255, .85); }
#map .hglow.on { opacity: 1; }
#map .sec { font-family: var(--mono); fill: rgba(255, 255, 255, .40); transition: fill .45s; }
#map .sec.pub { fill: rgba(255, 255, 255, .92); }
#map .sec.live { fill: var(--blue-hi); }
#map .rl { font-family: var(--mono); fill: rgba(255, 255, 255, .36); }
#map .pulse { fill: var(--blue-hi); }
#map .q-beam { fill: none; stroke: var(--orange); stroke-width: 1.2; stroke-opacity: .9; }
#map .q-halo { fill: none; stroke: var(--orange); stroke-width: 1.5; }
#map .q-badge rect { fill: #000; stroke: var(--orange); stroke-width: 1; }
#map .q-badge text { font-family: var(--mono); fill: var(--orange-hi); }
#map .q-dot { fill: var(--orange-hi); }

.readout { margin-top: 12px; padding: 14px 18px 16px; }
.ro-head { font-size: 10.5px; letter-spacing: 2.2px; color: var(--ink-3); }
.ro-q { font: 300 18px/1.35 var(--sans); color: var(--ink); margin: 6px 0 10px; }
.ro-list { list-style: none; padding: 0; display: grid; gap: 7px; }
.ro-list li { display: grid; grid-template-columns: 30px minmax(0, 1fr) 84px 34px; gap: 12px;
  align-items: center; font: 12px/1.4 var(--mono); color: var(--ink-2); opacity: .1; transition: opacity .35s; }
.ro-list li.shown { opacity: 1; }
.ro-list .rk { color: var(--orange-hi); }
.ro-list .pid { color: var(--ink); overflow-wrap: anywhere; }
.ro-list .pid code { background: none; padding: 0; font-size: 12px; }
.ro-list .ty { color: var(--ink-3); margin-left: 10px; text-transform: uppercase; font-size: 10px; letter-spacing: 1.4px; }
.ro-list .sc { text-align: right; color: var(--ink); }
.bar { display: block; height: 2px; background: rgba(255, 255, 255, .09); }
.bar i { display: block; height: 100%; background: var(--orange); }
.tag { font-size: 9.5px; line-height: 1; letter-spacing: 1.4px; color: var(--ink-3);
  border: 1px solid var(--line-2); padding: 2px 5px; margin-right: 7px; vertical-align: 1px; }

.panel { padding: 20px 20px 22px; min-height: 250px; }
.p-k { font-size: 10.5px; letter-spacing: 2.6px; color: var(--blue); }
.p-k.pv { color: var(--ink-3); }
.panel h3 { font: 300 21px/1.3 var(--sans); color: var(--ink); margin: 10px 0 8px; overflow-wrap: anywhere; }
.p-meta { font-size: 10.5px; letter-spacing: 1.5px; line-height: 1.7; color: var(--ink-3); }
.panel p { font-size: 14px; color: var(--ink-2); margin-top: 10px; }
.panel .quote { font-size: 15px; color: var(--ink); line-height: 1.55; }
.panel .links { font: 11.5px/1.75 var(--mono); color: var(--ink-2); }
.panel .links span { color: var(--ink-3); }

.legend { margin-top: 18px; padding: 0 2px; }
.legend ul { list-style: none; padding: 0; display: grid; gap: 10px; }
.legend li { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 10px; align-items: start;
  font-size: 13px; line-height: 1.45; color: var(--ink-2); }
.legend b { color: var(--ink); font-weight: 500; }
.sw { position: relative; display: block; width: 24px; height: 18px; }
.sw::before, .sw::after { content: ""; position: absolute; }
.sw-soma::after { left: 6px; top: 3px; width: 12px; height: 12px; border-radius: 50%; background: var(--ink);
  box-shadow: 0 0 0 2.5px var(--bg), 0 0 0 3.5px rgba(255, 255, 255, .25); }
.sw-soma.pv::after { background: rgba(255, 255, 255, .06); box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .55); }
.sw-fact::after { left: 1px; top: 7px; width: 22px; height: 4px;
  background: radial-gradient(circle, rgba(255, 255, 255, .85) 1.4px, transparent 1.9px) 0 0 / 5.5px 4px repeat-x; }
.sw-axon::after { left: 1px; right: 1px; top: 9px; height: 1px; background: rgba(255, 255, 255, .45); }
.sw-pulse::before { left: 1px; right: 1px; top: 9px; height: 1px; background: rgba(255, 255, 255, .18); }
.sw-pulse::after { left: 12px; top: 6.5px; width: 6px; height: 6px; border-radius: 50%; background: var(--blue-hi);
  box-shadow: 0 0 7px 1px rgba(74, 141, 255, .8); }
.sw-query::before { left: 4px; top: 2px; width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--orange); }
.sw-query::after { left: 9px; top: 7px; width: 5px; height: 5px; border-radius: 50%; background: var(--orange-hi); }
.legend-rings { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line);
  font-size: 12.5px; line-height: 1.6; color: var(--ink-2); }
.legend-rings p + p { margin-top: 6px; }
.lk { font-size: 10px; letter-spacing: 2.2px; color: var(--ink-3); margin-right: 6px; }

/* style A pipeline */
.pipe { display: grid; grid-template-columns: minmax(0, 1fr) 30px minmax(0, 1fr) 30px minmax(0, 1fr) 30px minmax(0, 1fr); }
.stage { padding: 18px 18px 16px; animation: lit 9s linear infinite; animation-delay: var(--d, 0s); }
.stage.q { animation-name: lit-q; }
.st-n { font-size: 11px; letter-spacing: 2.6px; color: var(--blue); }
.stage.q .st-n { color: var(--orange); }
.st-t { font: 600 14.5px/1.3 var(--sans); letter-spacing: 1.6px; text-transform: uppercase; color: var(--ink); margin: 8px 0; }
.stage p { font-size: 13.5px; line-height: 1.55; color: var(--ink-2); }
.stage code { display: inline-block; margin-top: 12px; color: var(--blue-hi); background: none; padding: 0; font-size: 11.5px; }
.stage.q code { color: var(--orange-hi); }
.wire { align-self: center; height: 1.5px;
  background: repeating-linear-gradient(90deg, var(--blue) 0 3px, transparent 3px 12px);
  animation: current 1s linear infinite; }
@keyframes current { from { background-position: 0 0; } to { background-position: 12px 0; } }
@keyframes current-v { from { background-position: 0 0; } to { background-position: 0 12px; } }
@keyframes lit {
  0% { border-color: var(--line); --bracket: rgba(255, 255, 255, .55); }
  3%, 17% { border-color: rgba(74, 141, 255, .9); --bracket: #4a8dff; }
  23%, 100% { border-color: var(--line); --bracket: rgba(255, 255, 255, .55); } }
@keyframes lit-q {
  0% { border-color: var(--line); --bracket: rgba(255, 255, 255, .55); }
  3%, 17% { border-color: rgba(255, 138, 31, .9); --bracket: #ff8a1f; }
  23%, 100% { border-color: var(--line); --bracket: rgba(255, 255, 255, .55); } }
.ops { margin-top: 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.op { font-size: 11px; line-height: 1; letter-spacing: 1.4px; color: var(--ink-2); border: 1px solid var(--line-2); padding: 7px 10px; }
.op b { color: var(--blue-hi); font-weight: 400; }

/* tiles */
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.tile { padding: 18px 18px 16px; }
.t-k { font-size: 10.5px; letter-spacing: 2.6px; color: var(--ink-3); }
.t-v { font: 200 42px/1.1 var(--sans); color: var(--blue-hi); font-variant-numeric: tabular-nums; margin: 10px 0 6px; }
.t-s { font-size: 13px; line-height: 1.45; color: var(--ink-2); }

/* retrieval demos */
.demos { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.demo { padding: 18px 18px 16px; display: flex; flex-direction: column; }
.d-k { font-size: 10.5px; letter-spacing: 2.6px; color: var(--orange); }
.d-q { font: 300 18px/1.35 var(--sans); color: var(--ink); margin: 8px 0 12px; }
.demo table { width: 100%; border-collapse: collapse; font: 12px/1.4 var(--mono); }
.demo th { font-weight: 400; font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: var(--ink-3);
  text-align: left; padding: 0 0 6px; border-bottom: 1px solid var(--line); }
.demo td { padding: 9px 0; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--ink-2); }
.demo td.rk { color: var(--orange-hi); width: 28px; }
.demo td code { background: none; padding: 0; color: var(--ink); font-size: 12px; overflow-wrap: anywhere; }
.demo .ty { display: block; font-size: 10px; letter-spacing: 1.4px; text-transform: uppercase; color: var(--ink-3); margin-top: 2px; }
.demo .num { text-align: right; color: var(--ink); width: 70px; }
.demo .num .bar { margin: 7px 0 0 auto; width: 56px; }
.d-play { margin-top: 16px; align-self: flex-start; text-transform: uppercase; letter-spacing: 1.6px; font-size: 10.5px; }

/* public pages */
details.page { margin-top: 10px; }
details.page > summary { list-style: none; cursor: pointer; display: block; position: relative; padding: 16px 52px 16px 18px; }
details.page > summary::-webkit-details-marker { display: none; }
details.page > summary::after { content: "+"; position: absolute; right: 20px; top: 50%; transform: translateY(-50%);
  font: 200 26px/1 var(--sans); color: var(--ink-3); }
details.page[open] > summary::after { content: "\2212"; }
.pg-k { display: block; font-size: 10.5px; letter-spacing: 2px; color: var(--ink-3); }
.pg-k a { text-transform: uppercase; margin-left: 4px; }
.pg-t { display: block; font: 300 19px/1.35 var(--sans); color: var(--ink); margin-top: 4px; }
.page-body { border-top: 1px solid var(--line); padding: 14px 18px 20px; font-size: 15px; color: var(--ink-2); overflow-wrap: anywhere; }
.page-body h2, .page-body h3, .page-body h4 { color: var(--ink); font-weight: 400; margin: 18px 0 6px; }
.page-body h2 { font-size: 21px; } .page-body h3 { font-size: 17px; } .page-body h4 { font-size: 15px; font-weight: 600; }
.page-body p { margin: 6px 0; }
.page-body ul { padding-left: 20px; margin: 6px 0; }
.page-body li { margin: 3px 0; }
.page-body strong { color: var(--ink); font-weight: 600; }
.page-body pre { margin: 10px 0; }
.fm { margin: 4px 0 12px; }
.fm > summary { cursor: pointer; font: 10.5px/1.6 var(--mono); letter-spacing: 2px; text-transform: uppercase; color: var(--ink-3); }
.fm pre { margin-top: 8px; max-height: 300px; overflow: auto; white-space: pre; }

/* for agents */
.card { padding: 20px 20px 18px; }
.card > p { color: var(--ink-2); font-size: 15px; }
.endpoints { list-style: none; padding: 0; margin: 14px 0 16px; display: grid; gap: 9px; }
.endpoints li { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 12px; align-items: baseline; font-size: 14px; color: var(--ink-2); }
.endpoints code { color: var(--blue-hi); background: none; padding: 0; }
.note { font-size: 13.5px; color: var(--ink-3) !important; margin-top: 12px; }

footer { margin-top: 72px; padding-top: 18px; border-top: 1px solid var(--line); display: flex; flex-wrap: wrap;
  gap: 6px 24px; font-size: 10.5px; line-height: 1.7; letter-spacing: 1.6px; color: var(--ink-3); }
footer code { background: none; padding: 0; color: var(--ink-2); font-size: 10.5px; text-transform: none; }

@media (max-width: 960px) {
  header { grid-template-columns: minmax(0, 1fr); }
  header .h-text { padding-top: 14px; }
  .map-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  /* one column: a tap on the map shows its details right under the map */
  .map-col, .side-col { display: contents; }
  .map-frame { order: 1; } .panel { order: 2; min-height: 0; } .readout { order: 3; margin-top: 0; }
  .legend { order: 4; margin-top: 6px; }
  .pipe { grid-template-columns: minmax(0, 1fr); }
  .wire { justify-self: center; width: 1.5px; height: 26px;
    background: repeating-linear-gradient(180deg, var(--blue) 0 3px, transparent 3px 12px); animation-name: current-v; }
  .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .demos { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 560px) {
  header { padding-top: 40px; }
  .wordmark { font-size: 40px; letter-spacing: 12px; margin: 18px 0 12px; }
  .tagline { font-size: 18px; }
  .sec-head h2 { font-size: 21px; white-space: normal; }
  section { margin-top: 60px; }
  .motion { margin-left: 0; }
  .chip { padding: 6px 9px; font-size: 11px; }
  .controls { gap: 6px; }
  .ro-list li { grid-template-columns: 26px minmax(0, 1fr) 30px; gap: 10px; }
  .ro-list .bar { display: none; }
  .ro-list .ty { display: block; margin: 2px 0 0; }
  .endpoints li { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .t-v { font-size: 34px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
"""


_JS = r"""
(() => {
"use strict";
const DATA = JSON.parse(document.getElementById("brain-data").textContent);
const G = DATA.graph, LAY = DATA.layout, DEMOS = DATA.demos, EXPLAIN = DATA.explain;
const NS = "http://www.w3.org/2000/svg";
const DEG = Math.PI / 180, PAD = 12;
const host = document.getElementById("map");
const panel = document.getElementById("panel");
const roHead = document.getElementById("ro-head");
const roQ = document.getElementById("ro-q");
const roList = document.getElementById("ro-list");
const motionBtn = document.getElementById("motion");
const qchips = Array.from(document.querySelectorAll(".qchip"));
const reducedMQ = window.matchMedia("(prefers-reduced-motion: reduce)");
if (!host || !panel) return;

/* ---------- helpers ---------- */
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const easeIO = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);   // easeInOutCubic
const easeOut = t => 1 - Math.pow(1 - t, 3);
const smooth = (a, b, t) => { const x = clamp((t - a) / (b - a), 0, 1); return x * x * (3 - 2 * x); };
const r1 = v => Math.round(v * 10) / 10;
const pad2 = n => String(n).padStart(2, "0");
const fmtScore = s => (Number.isInteger(s) ? String(s) : String(Math.round(s * 100) / 100));
const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
const cleanText = s => String(s || "").replace(/\*\*/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
function svgEl(tag, attrs, parent) {
  const e = document.createElementNS(NS, tag);
  if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function htmlEl(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function quad(S, C, T, t) {
  const u = 1 - t;
  return [u * u * S[0] + 2 * u * t * C[0] + t * t * T[0], u * u * S[1] + 2 * u * t * C[1] + t * t * T[1]];
}
const qd = (S, C, T) => "M" + r1(S[0]) + " " + r1(S[1]) + "Q" + r1(C[0]) + " " + r1(C[1]) + " " + r1(T[0]) + " " + r1(T[1]);
function taper(r) {
  // a dendrite: a quadratic spine drawn as a filled outline, wide at the soma,
  // a hair at the tip
  const nrm = (a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || 1; return [-dy / d, dx / d]; };
  const n0 = nrm(r.S, r.C), n1 = nrm(r.C, r.T), nc = nrm(r.S, r.T);
  const w0 = r.w0, wc = r.w0 * 0.55, w1 = 0.22;
  const P = (p, n, w) => r1(p[0] + n[0] * w) + " " + r1(p[1] + n[1] * w);
  return "M" + P(r.S, n0, w0) + "Q" + P(r.C, nc, wc) + " " + P(r.T, n1, w1) +
    "L" + P(r.T, n1, -w1) + "Q" + P(r.C, nc, -wc) + " " + P(r.S, n0, -w0) + "Z";
}
function rectGap(a, b) {
  const dx = Math.max(a[0] - b[2], 0, b[0] - a[2]), dy = Math.max(a[1] - b[3], 0, b[1] - a[3]);
  return Math.hypot(dx, dy);
}
function pointGap(b, x, y) {
  const dx = Math.max(b[0] - x, 0, x - b[2]), dy = Math.max(b[1] - y, 0, y - b[3]);
  return Math.hypot(dx, dy);
}
const setOp = (e, v) => { if (e && e._op !== v) { e.setAttribute("opacity", v); e._op = v; } };
const setXY = (e, p) => { e.setAttribute("cx", r1(p[0])); e.setAttribute("cy", r1(p[1])); };

/* ---------- the data, as the map reads it ---------- */
const byId = new Map(G.nodes.map(n => [n.id, n]));
const pages = G.nodes.filter(n => (n.kind || "page") === "page" && LAY.pages[n.id]);
const factsOf = new Map();
for (const n of G.nodes) {
  if (n.kind !== "claim" || !LAY.pages[n.parent]) continue;
  if (!factsOf.has(n.parent)) factsOf.set(n.parent, []);
  factsOf.get(n.parent).push(n);
}
const axons = G.links.filter(l => l.rel !== "claim")
  .map(l => ({ s: byId.get(l.source), t: byId.get(l.target), rel: l.rel }))
  .filter(l => l.s && l.t && LAY.pages[l.s.id] && LAY.pages[l.t.id]);
const receivers = new Set([...factsOf.keys(), ...axons.map(l => l.t.id)]);
const liveSectors = LAY.sectors.map((s, k) => k).filter(k =>
  pages.some(p => LAY.pages[p.id].sector === k && receivers.has(p.id)));
const demoHits = DEMOS.map(d => d.results.map((r, i) => ({ ...r, rank: i + 1,
  node: r.public && r.page_id && LAY.pages[r.page_id] ? byId.get(r.page_id) : null })));

/* ---------- geometry: the declared polar layout, in pixels ---------- */
function sectorLines(sc, narrow) {
  if (!narrow) return [sc.public ? sc.label : sc.short];
  if (!sc.public) return [];             // private lobes are named in the legend instead
  const w = sc.label.split(" ");
  if (sc.label.length <= 10 || w.length < 2) return [sc.label];
  let best = null;
  for (let i = 1; i < w.length; i++) {
    const a = w.slice(0, i).join(" "), b = w.slice(i).join(" "), m = Math.max(a.length, b.length);
    if (!best || m < best.m) best = { m, lines: [a, b] };
  }
  return best.lines;
}

// the dashed membrane round the centre pages
const selfR = self => Math.max(...self.map(g => Math.hypot(g.x, g.y) + g.s)) + 5;

function geometry(R, narrow) {
  const ks = clamp(R / 240, 0.82, 1.2), kd = clamp(R / 240, 0.74, 1.2), kb = Math.max(kd, 0.86);
  const P = new Map();
  for (const p of pages) {
    const lp = LAY.pages[p.id], a = lp.a * DEG;
    P.set(p.id, { node: p, a, sector: lp.sector, ring: lp.ring,
      x: lp.r * R * Math.cos(a), y: lp.r * R * Math.sin(a),
      s: (4 + 1.35 * Math.sqrt(p.claims || 0)) * ks });
  }
  // dendrites: a page's facts sit on tapered rays fanned outward, dealt to
  // the rays round-robin in claim order (fact i -> ray i mod n, slot i div n)
  const rays = [], beads = [];
  for (const [pid, list] of factsOf) {
    const g = P.get(pid), n = list.length;
    const nr = n <= 3 ? n : clamp(Math.round(Math.sqrt(n * 1.4)), 2, 8);
    const spread = Math.min(150, 24 * (nr - 1)) * DEG;
    const step = 6.2 * kd, gap = 8.5 * kd, tip = 4.5 * kd, r0 = g.s + 1.2;
    const first = rays.length;
    for (let j = 0; j < nr; j++) {
      const cnt = Math.ceil((n - j) / nr);
      const off = nr === 1 ? 0 : (j / (nr - 1) - 0.5) * spread;
      const a0 = g.a + off, a1 = g.a + off * 1.3;
      const len = g.s + gap + (cnt - 1) * step + tip, mid = r0 + (len - r0) * 0.55;
      const S = [g.x + Math.cos(a0) * r0, g.y + Math.sin(a0) * r0];
      const C = [g.x + Math.cos(a0) * mid, g.y + Math.sin(a0) * mid];
      const T = [g.x + Math.cos(a1) * len, g.y + Math.sin(a1) * len];
      rays.push({ pid, pub: !!g.node.public, r0, len, S, C, T, w0: Math.min(1.6, 0.34 + g.s * 0.09) * kb });
    }
    list.forEach((f, i) => {
      const ri = first + (i % nr), ray = rays[ri];
      const t = (g.s + gap + Math.floor(i / nr) * step - ray.r0) / (ray.len - ray.r0);
      const xy = quad(ray.S, ray.C, ray.T, t);
      beads.push({ node: f, pid, ri, t, x: xy[0], y: xy[1], r: (f.public ? 2.05 : 1.8) * kb });
    });
  }
  // axons: part_of links as gently bowed curves, rim to rim
  const rim = (g, C) => {
    const dx = C[0] - g.x, dy = C[1] - g.y, d = Math.hypot(dx, dy) || 1;
    return [g.x + dx / d * (g.s + 2.5), g.y + dy / d * (g.s + 2.5)];
  };
  const ax = axons.map(l => {
    const A = P.get(l.s.id), B = P.get(l.t.id);
    const dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy) || 1, bow = 0.13 * d;
    const C = [(A.x + B.x) / 2 - dy / d * bow, (A.y + B.y) / 2 + dx / d * bow];
    return { l, C, S: rim(A, C), T: rim(B, C) };
  });
  const axonPts = [];
  for (const a of ax) for (let i = 1; i < 10; i++) axonPts.push(quad(a.S, a.C, a.T, i / 10));
  // obstacles: everything that carries data; labels never sit on these
  const obstacles = [];
  for (const g of P.values()) obstacles.push({ pid: g.node.id, box: [g.x - g.s - 3, g.y - g.s - 3, g.x + g.s + 3, g.y + g.s + 3] });
  for (const b of beads) obstacles.push({ pid: null, box: [b.x - b.r - 1.5, b.y - b.r - 1.5, b.x + b.r + 1.5, b.y + b.r + 1.5] });
  // sector labels just outside how far each lobe reaches
  const ringR = Math.max(...LAY.rings.map(r => r.r)) * R;
  const reach = LAY.sectors.map(() => ringR);
  for (const g of P.values()) if (g.sector != null) reach[g.sector] = Math.max(reach[g.sector], Math.hypot(g.x, g.y) + g.s + 3);
  for (const b of beads) { const sc = P.get(b.pid).sector; if (sc != null) reach[sc] = Math.max(reach[sc], Math.hypot(b.x, b.y) + b.r + 1); }
  const fs = narrow ? 9 : 10, ls = narrow ? 1.3 : 2, lh = fs + 4, cw = fs * 0.62 + ls;
  const labels = [];
  LAY.sectors.forEach((sc, k) => {
    const lines = sectorLines(sc, narrow);
    if (!lines.length) return;
    const a = sc.a * DEG, c = Math.cos(a), s = Math.sin(a);
    const rr = reach[k] + (narrow ? 8 : 11), x = rr * c, y = rr * s;
    const anchor = c > 0.3 ? "start" : c < -0.3 ? "end" : "middle";
    const w = Math.max(...lines.map(t => t.length)) * cw, h = lines.length * lh;
    const top = s < -0.3 ? y - h : s > 0.3 ? y : y - h / 2;
    const left = anchor === "start" ? x : anchor === "end" ? x - w : x - w / 2;
    labels.push({ k, lines, x, top, anchor, fs, ls, lh, pub: sc.public, box: [left, top, left + w, top + h] });
  });
  // ring names, printed along the empty bearing between two lobes: on the
  // ring line if that is clear, else just outside it, else just inside it,
  // else not at all (the legend names every ring) -- never on top of data
  const beta = LAY.ring_label_bearing * DEG, rfs = narrow ? 8.5 : 9, rls = narrow ? 1.4 : 2;
  const ringLabels = [];
  LAY.rings.forEach((ring, ri) => {
    const w = ring.label.length * (rfs * 0.62 + rls) + 8, h = rfs + 6;
    let spots;
    if (ring.centre) {
      const self = [...P.values()].filter(g => g.ring === ri);
      if (!self.length) return;
      spots = [[0, selfR(self) + h / 2 + 3, false]];
    } else {
      const r = ring.r * R, c = Math.cos(beta), s = Math.sin(beta), o = h / 2 + 3;
      spots = [[r * c, r * s, true], [(r + o) * c, (r + o) * s, false], [(r - o) * c, (r - o) * s, false]];
    }
    for (const [x, y, onLine] of spots) {
      const box = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      if (obstacles.some(ob => rectGap(ob.box, box) < 1.5)) continue;
      if (labels.some(L => rectGap(L.box, box) < 1.5)) continue;
      if (ringLabels.some(L => rectGap(L.box, box) < 1.5)) continue;
      ringLabels.push({ text: ring.label, x, y, fs: rfs, ls: rls, box, onLine });
      break;
    }
  });
  const bb = [-ringR, -ringR, ringR, ringR];
  const grow = b => { bb[0] = Math.min(bb[0], b[0]); bb[1] = Math.min(bb[1], b[1]); bb[2] = Math.max(bb[2], b[2]); bb[3] = Math.max(bb[3], b[3]); };
  obstacles.forEach(o => grow(o.box)); labels.forEach(L => grow(L.box)); ringLabels.forEach(L => grow(L.box));
  return { R, narrow, kd, P, rays, beads, ax, axonPts, obstacles, labels, ringLabels, ringR, bbox: bb };
}

function fitLayout(W, Hmax, narrow) {
  // the largest radius at which every neuron, bead and label fits inside the
  // frame with a margin: nothing is ever clipped at the edge
  let lo = 24, hi = Math.min(W, Hmax) / 2, best = null;
  for (let i = 0; i < 26; i++) {
    const mid = (lo + hi) / 2, g = geometry(mid, narrow);
    if (g.bbox[2] - g.bbox[0] <= W - 2 * PAD && g.bbox[3] - g.bbox[1] <= Hmax - 2 * PAD) { lo = mid; best = g; }
    else hi = mid;
  }
  return best || geometry(lo, narrow);
}

/* ---------- drawing ---------- */
let geo = null, svg = null, W = 0, H = 0, OX = 0, OY = 0;
const refs = {};
function gradient(defs, id, rgb) {
  const g = svgEl("radialGradient", { id }, defs);
  svgEl("stop", { offset: "0%", "stop-color": "rgb(" + rgb + ")", "stop-opacity": "0.55" }, g);
  svgEl("stop", { offset: "45%", "stop-color": "rgb(" + rgb + ")", "stop-opacity": "0.15" }, g);
  svgEl("stop", { offset: "100%", "stop-color": "rgb(" + rgb + ")", "stop-opacity": "0" }, g);
}

function build() {
  const w = Math.floor(host.clientWidth);
  if (!w || w === W) return false;
  W = w;
  const narrow = W < 560;
  const Hmax = narrow ? Math.round(W * 1.25) : Math.round(clamp(W * 0.8, 460, 680));
  geo = fitLayout(W, Hmax, narrow);
  H = Math.min(Hmax, Math.ceil(geo.bbox[3] - geo.bbox[1] + 2 * PAD + (narrow ? 20 : 30)));
  OX = Math.round(W / 2 - (geo.bbox[0] + geo.bbox[2]) / 2);
  OY = Math.round(H / 2 - (geo.bbox[1] + geo.bbox[3]) / 2);
  draw();
  return true;
}

function draw() {
  host.textContent = "";
  svg = svgEl("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, "aria-hidden": "true", focusable: "false" }, host);
  const defs = svgEl("defs", null, svg);
  gradient(defs, "glowB", "111,176,255");
  const root = svgEl("g", { transform: "translate(" + OX + " " + OY + ")" }, svg);
  const layer = name => svgEl("g", { class: name }, root);
  const gRings = layer("l-rings"), gAx = layer("l-axons"), gRays = layer("l-rays"), gGlow = layer("l-glow"),
    gBeads = layer("l-beads"), gSoma = layer("l-somas"), gPulse = layer("l-pulses"), gLab = layer("l-labels");
  // the query lives in a wrapper so a hover can dim it without touching the
  // replay's own fade (opacities multiply)
  refs.gQuery = svgEl("g", null, layer("l-query"));

  // ring guides; the centre ring is a dashed membrane round the self pages
  LAY.rings.forEach((ring, ri) => {
    let r = ring.r * geo.R;
    if (ring.centre) {
      const self = [...geo.P.values()].filter(g => g.ring === ri);
      if (!self.length) return;
      r = selfR(self);
    }
    svgEl("circle", { class: "ring" + (ring.centre ? " centre" : ""), cx: 0, cy: 0, r: r1(r) }, gRings);
  });
  // sector boundaries as ticks on the outer ring (one sector = one project)
  const stepA = 360 / Math.max(1, LAY.sectors.length);
  LAY.sectors.forEach(sc => {
    const b = sc.a + stepA / 2;
    const gapTo = x => Math.abs(((b - x + 540) % 360) - 180);
    if (gapTo(LAY.query_port) < 1 || gapTo(LAY.ring_label_bearing) < 1) return;
    const a = b * DEG, c = Math.cos(a), s = Math.sin(a);
    svgEl("line", { class: "tick", x1: r1(c * (geo.ringR - 4)), y1: r1(s * (geo.ringR - 4)), x2: r1(c * (geo.ringR + 4)), y2: r1(s * (geo.ringR + 4)) }, gRings);
  });
  // where queries come in from: the frame's edge on the port bearing
  const pa = LAY.query_port * DEG, dir = [Math.cos(pa), Math.sin(pa)];
  const ts = [];
  if (dir[0] > 1e-9) ts.push((W - OX - 1) / dir[0]); if (dir[0] < -1e-9) ts.push((-OX + 1) / dir[0]);
  if (dir[1] > 1e-9) ts.push((H - OY - 1) / dir[1]); if (dir[1] < -1e-9) ts.push((-OY + 1) / dir[1]);
  const te = Math.min(...ts.filter(t => t > 0));
  refs.E = [dir[0] * te, dir[1] * te];
  refs.Q = [dir[0] * geo.ringR, dir[1] * geo.ringR];
  svgEl("line", { class: "port", x1: r1(refs.E[0]), y1: r1(refs.E[1]), x2: r1(refs.E[0] - dir[0] * 9), y2: r1(refs.E[1] - dir[1] * 9) }, gRings);

  refs.axon = geo.ax.map(a => svgEl("path", { class: "axon dm", d: qd(a.S, a.C, a.T) }, gAx));
  refs.ray = geo.rays.map(r => svgEl("path", { class: "ray dm" + (r.pub ? "" : " pv"), d: taper(r) }, gRays));
  refs.bead = geo.beads.map(b => svgEl("circle", { class: "bead dm" + (b.node.public ? "" : " pv"), cx: r1(b.x), cy: r1(b.y), r: r1(b.r), "data-id": b.node.id }, gBeads));
  refs.page = new Map();
  for (const g of geo.P.values()) {
    const pv = g.node.public ? "" : " pv", c = { cx: r1(g.x), cy: r1(g.y) };
    const glowS = svgEl("circle", { ...c, r: r1(g.s * 2.4 + 12), fill: "url(#glowB)", opacity: 0 }, gGlow);
    const glowH = svgEl("circle", { ...c, class: "hglow", r: r1(g.s * 2.4 + 12), fill: "url(#glowB)" }, gGlow);
    const mem = svgEl("circle", { ...c, class: "mem dm" + pv, r: r1(g.s + 2.6) }, gSoma);
    const body = svgEl("circle", { ...c, class: "body dm" + pv, r: r1(g.s), "data-id": g.node.id }, gSoma);
    refs.page.set(g.node.id, { g, glowS, glowH, mem, body, glow: 0 });
  }
  // indexes for highlighting
  refs.raysOf = new Map(); refs.beadsOf = new Map(); refs.beadIdx = new Map(); refs.axOf = new Map();
  geo.rays.forEach((r, i) => { if (!refs.raysOf.has(r.pid)) refs.raysOf.set(r.pid, []); refs.raysOf.get(r.pid).push(i); });
  geo.beads.forEach((b, i) => { if (!refs.beadsOf.has(b.pid)) refs.beadsOf.set(b.pid, []); refs.beadsOf.get(b.pid).push(i); refs.beadIdx.set(b.node.id, i); });
  geo.ax.forEach((a, i) => { for (const id of [a.l.s.id, a.l.t.id]) { if (!refs.axOf.has(id)) refs.axOf.set(id, []); refs.axOf.get(id).push(i); } });

  // pulses: one per real edge, idle until its project's turn
  const pr = r1(1.9 * Math.max(geo.kd, 0.85));
  refs.factPulses = [];
  for (const [pid, list] of refs.beadsOf) {
    const sector = geo.P.get(pid).sector;
    list.forEach((bi, i) => refs.factPulses.push({ e: svgEl("circle", { class: "pulse", r: pr, opacity: 0 }, gPulse), bi, sector, i, n: list.length }));
  }
  refs.axPulses = geo.ax.map((a, i) => ({
    halo: svgEl("circle", { r: 7, fill: "url(#glowB)", opacity: 0 }, gPulse),
    e: svgEl("circle", { class: "pulse", r: 2.4, opacity: 0 }, gPulse),
    ai: i, sector: geo.P.get(a.l.t.id).sector }));

  refs.sec = new Map();
  for (const L of geo.labels) {
    const t = svgEl("text", { class: "sec" + (L.pub ? " pub" : ""), "text-anchor": L.anchor, "font-size": L.fs, "letter-spacing": L.ls }, gLab);
    L.lines.forEach((line, i) => { svgEl("tspan", { x: r1(L.x), y: r1(L.top + i * L.lh + L.fs * 0.82) }, t).textContent = line; });
    refs.sec.set(L.k, t);
  }
  for (const L of geo.ringLabels) {
    if (L.onLine) svgEl("rect", { x: r1(L.box[0]), y: r1(L.box[1]), width: r1(L.box[2] - L.box[0]), height: r1(L.box[3] - L.box[1]), fill: "#000" }, gLab);
    const t = svgEl("text", { class: "rl", x: r1(L.x + L.ls / 2), y: r1(L.y + L.fs * 0.36), "text-anchor": "middle", "font-size": L.fs, "letter-spacing": L.ls }, gLab);
    t.textContent = L.text;
  }
  onEls = [];
}

/* ---------- the retrieval replay (orange: the query signal) ---------- */
function badgeSpot(g, text, placed, extra) {
  const fsb = geo.narrow ? 9 : 10, w = text.length * fsb * 0.63 + 11, h = fsb + 5;
  const lim = [-OX + 2, -OY + 2, W - OX - 2, H - OY - 2];
  let best = null, bestScore = -Infinity;
  for (let i = 0; i < 24; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 12;
    const d = g.s + 6 + Math.abs(Math.cos(a)) * w / 2 + Math.abs(Math.sin(a)) * h / 2;
    const cx = g.x + Math.cos(a) * d, cy = g.y + Math.sin(a) * d;
    const box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2];
    if (box[0] < lim[0] || box[1] < lim[1] || box[2] > lim[2] || box[3] > lim[3]) continue;
    let clear = 99;
    for (const o of geo.obstacles) if (o.pid !== g.node.id) clear = Math.min(clear, rectGap(box, o.box));
    for (const L of geo.labels) clear = Math.min(clear, rectGap(box, L.box));
    for (const L of geo.ringLabels) clear = Math.min(clear, rectGap(box, L.box));
    for (const p of placed) clear = Math.min(clear, rectGap(box, p) - 2);
    for (const pt of geo.axonPts) clear = Math.min(clear, pointGap(box, pt[0], pt[1]));
    for (const pt of extra) clear = Math.min(clear, pointGap(box, pt[0], pt[1]));
    const score = Math.min(clear, 10) - d * 0.03;
    if (score > bestScore + 1e-9) { bestScore = score; best = { cx, cy, w, h, box }; }
  }
  if (!best) { const cy = g.y - g.s - 14; best = { cx: g.x, cy, w, h, box: [g.x - w / 2, cy - h / 2, g.x + w / 2, cy + h / 2] }; }
  best.text = text;
  return best;
}

function buildQuery(i) {
  const gq = refs.gQuery;
  gq.textContent = "";
  setOp(gq, 1);
  const hits = demoHits[i] || [];
  const Q = refs.Q, beams = [], halos = [], badges = [], beamPts = [];
  hits.forEach(h => {
    if (!h.node) { beams.push(null); return; }
    const g = geo.P.get(h.node.id);
    const C = [(Q[0] + g.x) / 2 * 0.8, (Q[1] + g.y) / 2 * 0.8];   // a gentle sag toward the centre
    const dx = C[0] - g.x, dy = C[1] - g.y, d = Math.hypot(dx, dy) || 1;
    const T = [g.x + dx / d * (g.s + 6), g.y + dy / d * (g.s + 6)];
    const path = svgEl("path", { class: "q-beam", d: qd(Q, C, T) }, gq);
    const len = path.getTotalLength() || 1;
    path.style.strokeDasharray = len + " " + len;
    path.style.strokeDashoffset = len;
    beams.push({ path, len, S: Q, C, T });
    for (let k = 1; k < 10; k++) beamPts.push(quad(Q, C, T, k / 10));
  });
  const placed = [];
  hits.forEach((h, k) => {
    if (!h.node) { halos.push(null); badges.push(null); return; }
    const g = geo.P.get(h.node.id);
    halos.push(svgEl("circle", { class: "q-halo", cx: r1(g.x), cy: r1(g.y), r: r1(g.s + 6), opacity: 0 }, gq));
    const b = badgeSpot(g, h.rank + " · " + fmtScore(h.score), placed, beamPts);
    placed.push(b.box);
    const bg = svgEl("g", { class: "q-badge", opacity: 0 }, gq);
    svgEl("rect", { x: r1(b.box[0]), y: r1(b.box[1]), width: r1(b.w), height: r1(b.h) }, bg);
    const fsb = geo.narrow ? 9 : 10;
    svgEl("text", { x: r1(b.cx + 0.3), y: r1(b.cy + fsb * 0.35), "text-anchor": "middle", "font-size": fsb, "letter-spacing": 0.5 }, bg).textContent = b.text;
    badges.push(bg);
  });
  beams.forEach(b => { if (b) b.head = svgEl("circle", { class: "q-dot", r: 2.3, opacity: 0 }, gq); });
  const trail = [0.5, 0.3, 0.16].map(() => svgEl("circle", { class: "q-dot", r: 2.1, opacity: 0 }, gq));
  const qdot = svgEl("circle", { class: "q-dot", r: 3.2, opacity: 0 }, gq);
  const flash = svgEl("circle", { class: "q-halo", cx: r1(Q[0]), cy: r1(Q[1]), r: 3, opacity: 0 }, gq);
  refs.q = { beams, halos, badges, trail, qdot, flash, n: hits.length };
}

function renderReadout(i) {
  const d = DEMOS[i];
  if (!d || !roList) return;
  roHead.textContent = "query " + pad2(i + 1) + " / " + pad2(DEMOS.length) + " · ranked by the real retrieval engine";
  roQ.textContent = "“" + d.query + "”";
  roList.textContent = "";
  const top = Math.max(0, ...d.results.map(r => r.score));
  d.results.forEach((r, k) => {
    const li = htmlEl("li");
    li.append(htmlEl("span", "rk", "#" + (k + 1)));
    const pid = htmlEl("span", "pid");
    if (r.public && r.page_id) pid.append(htmlEl("code", null, r.page_id));
    else pid.append(htmlEl("span", "tag", "private"), document.createTextNode("private page"));
    pid.append(htmlEl("span", "ty", r.type));
    const bar = htmlEl("span", "bar"), fill = htmlEl("i");
    fill.style.width = (top > 0 ? clamp(100 * r.score / top, 0, 100) : 0).toFixed(1) + "%";
    bar.append(fill);
    li.append(pid, bar, htmlEl("span", "sc", fmtScore(r.score)));
    roList.append(li);
  });
}
const showRow = (k, on) => { const li = roList && roList.children[k]; if (li && li._on !== on) { li.classList.toggle("shown", on); li._on = on; } };

let cur = 0;
function setDemo(i) {
  cur = i;
  qchips.forEach((c, j) => c.setAttribute("aria-pressed", j === i ? "true" : "false"));
  renderReadout(i);
  if (svg) buildQuery(i);
}

/* ---------- motion: every pulse runs along a real edge ---------- */
// Blue: one project at a time, its facts stream into their pages and its
// pages into their overview (2.4 s a project, like the orbit's dwell).
// Orange: a real retrieval demo enters from the edge and the pages it
// returned light up in rank order with their scores.
const SECTOR_MS = 2400, WINDOW_MS = 2950, FACT_SPREAD = 650, FACT_MS = 950, AX_AT = 1050, AX_MS = 1150;
const Q_ENTER = 900, Q_STEP = 420, Q_BEAM = 650, Q_HOLD = 2600, Q_FADE = 600, Q_GAP = 700;
const CYCLE = Math.max(1, liveSectors.length) * SECTOR_MS;
// the sweep opens on the first private lobe, so a first-time viewer sees the
// orange query on the public pages and the blue facts elsewhere, not both at once
const SWEEP_AT = Math.max(0, liveSectors.findIndex(k => !LAY.sectors[k].public)) * SECTOR_MS;
const qLen = i => Q_ENTER + Math.max(0, (demoHits[i] || []).length - 1) * Q_STEP + Q_BEAM + Q_HOLD + Q_FADE + Q_GAP;
let raf = 0, running = false, paused = false, visible = true, t0 = 0, tHeld = 0, qStart = 0;

function tint(pr, g) {
  // white -> bright blue (#6fb0ff) as the facts arrive; cleared at rest so the
  // hover classes own the colour again
  if (g <= 0) { pr.body.style.fill = ""; pr.body.style.stroke = ""; return; }
  const mix = (a, b) => Math.round(a + (b - a) * g);
  if (pr.g.node.public) pr.body.style.fill = "rgb(" + mix(255, 111) + "," + mix(255, 176) + "," + mix(255, 255) + ")";
  else pr.body.style.stroke = "rgba(111,176,255," + (0.52 + 0.48 * g).toFixed(2) + ")";
}
function sweep(t) {
  const tc = (t + SWEEP_AT) % CYCLE, tau = new Map();
  liveSectors.forEach((k, j) => { let lt = tc - j * SECTOR_MS; if (lt < 0) lt += CYCLE; if (lt < WINDOW_MS) tau.set(k, lt); });
  for (const fp of refs.factPulses) {
    const lt = tau.get(fp.sector);
    let op = 0;
    if (lt !== undefined) {
      const p = (lt - (fp.n > 1 ? fp.i / (fp.n - 1) * FACT_SPREAD : 0)) / FACT_MS;
      if (p > 0 && p < 1) {
        const b = geo.beads[fp.bi], ray = geo.rays[b.ri];
        setXY(fp.e, quad(ray.S, ray.C, ray.T, b.t * (1 - easeIO(p))));
        op = r1(p < 0.18 ? p / 0.18 : p > 0.82 ? (1 - p) / 0.18 : 1);
      }
    }
    setOp(fp.e, op);
  }
  for (const ap of refs.axPulses) {
    const lt = tau.get(ap.sector);
    let op = 0;
    if (lt !== undefined) {
      const p = (lt - AX_AT) / AX_MS;
      if (p > 0 && p < 1) {
        const a = geo.ax[ap.ai], xy = quad(a.S, a.C, a.T, easeIO(p));
        setXY(ap.e, xy); setXY(ap.halo, xy);
        op = r1(p < 0.12 ? p / 0.12 : p > 0.9 ? (1 - p) / 0.1 : 1);
      }
    }
    setOp(ap.e, op); setOp(ap.halo, r1(op * 0.6));
  }
  for (const [id, pr] of refs.page) {
    if (!receivers.has(id)) continue;
    const lt = pr.g.sector == null ? undefined : tau.get(pr.g.sector);
    const glow = lt === undefined ? 0 : Math.round(100 * smooth(700, 1450, lt) * (1 - smooth(2150, 2900, lt))) / 100;
    if (glow !== pr.glow) {
      setOp(pr.glowS, r1(glow * 0.95));
      pr.body.setAttribute("r", r1(pr.g.s * (1 + 0.3 * glow)));
      tint(pr, glow);
      pr.glow = glow;
    }
  }
  for (const [k, el] of refs.sec) {
    const lt = tau.get(k), live = lt !== undefined && lt < SECTOR_MS;
    if (el._live !== live) { el.classList.toggle("live", live); el._live = live; }
  }
}

function replay(lt) {
  const q = refs.q;
  if (!q) return;
  const fadeAt = Q_ENTER + Math.max(0, q.n - 1) * Q_STEP + Q_BEAM + Q_HOLD;
  setOp(refs.gQuery, r1(lt < fadeAt ? 1 : clamp(1 - (lt - fadeAt) / Q_FADE, 0, 1)));
  if (lt < Q_ENTER) {
    const f = lt / Q_ENTER, at = x => { const e = easeIO(clamp(x, 0, 1)); return [refs.E[0] + (refs.Q[0] - refs.E[0]) * e, refs.E[1] + (refs.Q[1] - refs.E[1]) * e]; };
    setXY(q.qdot, at(f)); setOp(q.qdot, 1);
    q.trail.forEach((tr, i) => { const back = f - (i + 1) * 0.045; setXY(tr, at(back)); setOp(tr, back > 0 ? [0.5, 0.3, 0.16][i] : 0); });
  } else { setOp(q.qdot, 0); q.trail.forEach(tr => setOp(tr, 0)); }
  const fl = (lt - Q_ENTER) / 520;
  if (fl > 0 && fl < 1) { q.flash.setAttribute("r", r1(3 + 13 * easeOut(fl))); setOp(q.flash, r1(0.9 * (1 - fl))); } else setOp(q.flash, 0);
  for (let k = 0; k < q.n; k++) {
    const st = Q_ENTER + k * Q_STEP, b = q.beams[k];
    showRow(k, lt >= st + Q_BEAM);
    if (!b) continue;
    const p = clamp((lt - st) / Q_BEAM, 0, 1), e = easeIO(p);
    b.path.style.strokeDashoffset = r1(b.len * (1 - e));
    if (p > 0 && p < 1) { setXY(b.head, quad(b.S, b.C, b.T, e)); setOp(b.head, 1); } else setOp(b.head, 0);
    const hp = r1(clamp((lt - st - Q_BEAM) / 260, 0, 1));
    setOp(q.halos[k], hp); setOp(q.badges[k], hp);
  }
}

function staticFrame() {
  // the map at rest is complete: every neuron, bead and link drawn, no pulse,
  // and the current query's answer shown in full (beams, ranks, scores)
  if (!svg) return;
  for (const fp of refs.factPulses) setOp(fp.e, 0);
  for (const ap of refs.axPulses) { setOp(ap.e, 0); setOp(ap.halo, 0); }
  for (const pr of refs.page.values()) { setOp(pr.glowS, 0); pr.body.setAttribute("r", r1(pr.g.s)); tint(pr, 0); pr.glow = 0; }
  for (const el of refs.sec.values()) { el.classList.remove("live"); el._live = false; }
  const q = refs.q;
  if (!q) return;
  setOp(refs.gQuery, 1); setOp(q.qdot, 0); setOp(q.flash, 0); q.trail.forEach(tr => setOp(tr, 0));
  q.beams.forEach(b => { if (b) { b.path.style.strokeDashoffset = 0; setOp(b.head, 0); } });
  q.halos.forEach(h => setOp(h, 1)); q.badges.forEach(b => setOp(b, 1));
  for (let k = 0; k < q.n; k++) showRow(k, true);
}

function tick(now) {
  raf = requestAnimationFrame(tick);
  const t = now - t0;
  sweep(t);
  if (DEMOS.length) {
    if (t - qStart >= qLen(cur)) { qStart = t; setDemo((cur + 1) % DEMOS.length); }
    replay(t - qStart);
  }
}
const wantMotion = () => !reducedMQ.matches && !paused && visible && !!svg;
function updateMotion() {
  const want = wantMotion();
  if (want && !running) {
    running = true;
    const now = performance.now();
    t0 = now - tHeld; qStart = tHeld;          // resume the sweep; replay the current query from its start
    raf = requestAnimationFrame(tick);
  } else if (!want && running) {
    running = false;
    cancelAnimationFrame(raf);
    tHeld = performance.now() - t0;
  }
  if (!want) staticFrame();
}
function play(i) {
  setDemo(i);
  if (running) qStart = performance.now() - t0; else staticFrame();
}

/* ---------- hover, tap, and the detail panel ---------- */
const DEFAULT_PANEL = panel.innerHTML;
let pinned = null, hovered = null, onEls = [], lastPointer = "mouse";
function focusOn(n) {
  for (const e of onEls) e.classList.remove("on");
  onEls = [];
  if (!svg) return;
  svg.classList.toggle("focus", !!n);
  if (!n) return;
  const mark = e => { if (e) { e.classList.add("on"); onEls.push(e); } };
  const markPage = id => { const p = refs.page.get(id); if (p) { mark(p.body); mark(p.mem); mark(p.glowH); } };
  if (n.kind === "claim") {
    const bi = refs.beadIdx.get(n.id);
    if (bi !== undefined) { mark(refs.bead[bi]); mark(refs.ray[geo.beads[bi].ri]); }
    markPage(n.parent);
    return;
  }
  markPage(n.id);
  (refs.raysOf.get(n.id) || []).forEach(i => mark(refs.ray[i]));
  (refs.beadsOf.get(n.id) || []).forEach(i => mark(refs.bead[i]));
  (refs.axOf.get(n.id) || []).forEach(i => { mark(refs.axon[i]); const a = geo.ax[i]; markPage(a.l.s === n ? a.l.t.id : a.l.s.id); });
}
function hitTest(x, y, touch) {
  let best = null, bd = Infinity;
  for (const g of geo.P.values()) {
    const d = Math.hypot(x - g.x, y - g.y) - g.s;
    if (d < (touch ? 14 : 7) && d < bd) { bd = d; best = g.node; }
  }
  if (best) return best;
  for (const b of geo.beads) {
    const d = Math.hypot(x - b.x, y - b.y);
    if (d < (touch ? 11 : 6) && d < bd) { bd = d; best = b.node; }
  }
  return best;
}
function local(ev) {
  const r = svg.getBoundingClientRect();
  return [(ev.clientX - r.left) * (W / r.width) - OX, (ev.clientY - r.top) * (H / r.height) - OY];
}
function showPanel(n) {
  if (!n) { panel.innerHTML = DEFAULT_PANEL; return; }
  panel.textContent = "";
  if (n.kind === "claim") {
    const parent = byId.get(n.parent), list = factsOf.get(n.parent) || [];
    if (n.public && n.text) {
      panel.append(htmlEl("div", "p-k", "Fact · " + (list.indexOf(n) + 1) + " of " + list.length));
      panel.append(htmlEl("div", "p-meta", "on " + (parent && parent.public ? parent.title : "a public page")));
      // the export keeps the first 280 characters of a fact; say so when it bit
      const txt = cleanText(n.text).trim() + (n.text.length >= 280 ? "…" : "");
      panel.append(htmlEl("p", "quote", "“" + txt + "”"));
      panel.append(htmlEl("p", null, "Each bead is one atomic fact its page holds, cited back to its source at ingest time."));
    } else {
      panel.append(htmlEl("div", "p-k pv", "Private fact"));
      panel.append(htmlEl("h3", null, "Private fact"));
      panel.append(htmlEl("p", null, "A verified fact inside a private page. It is on the map so the brain's density is honest; its content never leaves the local machine."));
    }
    return;
  }
  const nf = n.claims || 0, ax = refs.axOf.get(n.id) || [];
  const explain = EXPLAIN[n.type] || "A knowledge page.";
  if (n.public) {
    panel.append(htmlEl("div", "p-k", "Page · " + n.type));
    panel.append(htmlEl("h3", null, n.title));
    panel.append(htmlEl("div", "p-meta", [n.project, plural(nf, "fact"), plural(ax.length, "link")].join(" · ")));
    panel.append(htmlEl("p", null, explain));
    if (ax.length) {
      const links = htmlEl("p", "links");
      ax.forEach(i => {
        const a = geo.ax[i], out = a.l.s === n, o = out ? a.l.t : a.l.s;
        if (links.childNodes.length) links.append(document.createElement("br"));
        links.append(htmlEl("span", null, out ? "part of → " : "← part: "), document.createTextNode(o.public ? o.title : "private page"));
      });
      panel.append(links);
    }
    const p = htmlEl("p"), a = htmlEl("a", null, "Read the full page ↓");
    a.href = "#page-" + n.id;
    a.addEventListener("click", () => { const d = document.getElementById("page-" + n.id); if (d) d.open = true; });
    p.append(a);
    panel.append(p);
  } else {
    panel.append(htmlEl("div", "p-k pv", "Private page"));
    panel.append(htmlEl("h3", null, "Private page"));
    panel.append(htmlEl("div", "p-meta", [n.project || "personal", n.type, plural(nf, "fact")].join(" · ")));
    panel.append(htmlEl("p", null, explain));
    panel.append(htmlEl("p", null, "Private pages are on the map so the brain's true shape is visible; their titles and contents are excluded from this export by construction."));
  }
}
host.addEventListener("pointerdown", ev => { lastPointer = ev.pointerType || "mouse"; });
host.addEventListener("pointermove", ev => {
  if (!svg || ev.pointerType === "touch") return;
  const xy = local(ev), n = hitTest(xy[0], xy[1], false);
  host.style.cursor = n ? "pointer" : "default";
  if (n === hovered) return;
  hovered = n;
  focusOn(n || pinned); showPanel(n || pinned);
});
host.addEventListener("pointerleave", () => { hovered = null; host.style.cursor = "default"; focusOn(pinned); showPanel(pinned); });
host.addEventListener("click", ev => {
  if (!svg) return;
  const xy = local(ev);
  pinned = hitTest(xy[0], xy[1], lastPointer === "touch");
  focusOn(pinned); showPanel(pinned);
});

/* ---------- wiring ---------- */
document.querySelectorAll("[data-demo]").forEach(b => b.addEventListener("click", () => {
  play(Number(b.getAttribute("data-demo")));
  if (!b.classList.contains("qchip")) {
    const s = document.getElementById("map-section");
    if (s) s.scrollIntoView({ behavior: reducedMQ.matches ? "auto" : "smooth", block: "start" });
  }
}));
function syncMotionButton() {
  if (!motionBtn) return;
  motionBtn.disabled = reducedMQ.matches;
  motionBtn.textContent = reducedMQ.matches ? "Motion off · system setting" : paused ? "Resume motion" : "Pause motion";
  motionBtn.setAttribute("aria-pressed", String(paused && !reducedMQ.matches));
}
if (motionBtn) motionBtn.addEventListener("click", () => { paused = !paused; syncMotionButton(); updateMotion(); });
const onReduced = () => { syncMotionButton(); updateMotion(); };
if (reducedMQ.addEventListener) reducedMQ.addEventListener("change", onReduced);
if ("IntersectionObserver" in window) {
  new IntersectionObserver(es => { visible = es[es.length - 1].isIntersecting; updateMotion(); }).observe(host);
}
let rz = 0;
window.addEventListener("resize", () => {
  clearTimeout(rz);
  rz = setTimeout(() => {
    if (!build()) return;
    buildQuery(cur);
    if (!running) staticFrame();
    focusOn(hovered || pinned);
    updateMotion();
  }, 120);
});

build();
setDemo(0);
syncMotionButton();
updateMotion();
})();
"""


def render_html(stats: dict, pages: list[dict], demos: list[dict],
                graph: dict, commit: str, built_at: str) -> str:
    """The human page. A pure function of its arguments (no clock, no
    randomness), so the same brain.json always renders the same bytes."""
    esc = html.escape
    layout = map_layout(graph)
    nodes = graph["nodes"]
    page_nodes = [n for n in nodes if n.get("kind", "page") == "page"]
    n_facts = sum(1 for n in nodes if n.get("kind") == "claim")
    n_axons = sum(1 for link in graph["links"] if link["rel"] != "claim")
    has_private = any(not n["public"] for n in page_nodes)
    n_projects = len(layout["sectors"])

    # ── header ──
    header = (
        '<header>\n'
        '  <div class="h-id"><div class="kicker">Optimus<span class="sep">/</span>public brain snapshot</div>\n'
        '  <h1 class="wordmark">OPTIMUS</h1>\n'
        '  <p class="tagline">The memory layer behind Aegis Finance.</p></div>\n'
        '  <div class="h-text"><p class="lede">Everything Optimus knows lives in plain markdown '
        '<em>pages</em>, and this map draws every one of them. <strong>Each page '
        'is a neuron</strong>, placed on a ring by what it is for and at a '
        'bearing by the project it belongs to; <strong>each bead on its dendrites '
        'is one verified fact</strong> it holds; the lines between pages are '
        'part-of links. <span class="b">Blue pulses</span> are facts feeding '
        'their pages. <span class="o">Orange</span> is a real query from the '
        'retrieval demo, lighting the pages it returned in rank order.'
        + (" Dim neurons are private: you can see they exist, never what is "
           "inside." if has_private else "")
        + "</p></div>\n"
        '  <div class="metarow">'
        f'<span>snapshot <b>{esc(built_at)}</b></span>'
        f'<span>brain @ <b>{esc(commit)}</b></span>'
        f'<span><b>{stats["pages"]}</b> pages</span>'
        f'<span><b>{stats["claims"]}</b> facts</span>'
        '<span>read-only export</span></div>\n'
        '</header>'
    )

    # ── 01 the map ──
    chips = "".join(
        f'<button type="button" class="chip qchip" data-demo="{i}" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{esc(d["query"])}</button>'
        for i, d in enumerate(demos))
    controls = (
        '<div class="controls">'
        + (f'<span class="ctl-label">Retrieval replay</span>{chips}' if demos else "")
        + '<button type="button" class="chip motion" id="motion" '
          'aria-pressed="false">Pause motion</button></div>')
    default_panel = (
        '<div class="p-k">Select a neuron</div>'
        '<h3>Hover or tap a page</h3>'
        '<p>Pages are the neurons; the beads on their dendrites are the facts '
        'each one holds. Hover or tap to light a page and everything wired to '
        'it; click to keep it selected.</p>'
        f'<div class="p-meta">{_plural(len(page_nodes), "page")} · '
        f'{_plural(n_facts, "fact")} · {_plural(n_axons, "part-of link")} · '
        f'{_plural(n_projects, "project")}</div>')
    legend_items = [("sw-soma", "Page",
                     "one neuron per knowledge page; it grows with the facts it holds")]
    if has_private:
        legend_items.append(("sw-soma pv", "Private page",
                             "anonymized: the shape is visible, never the content"))
    if n_facts:
        legend_items.append(("sw-fact", "Fact",
                             "one verified claim, a bead on its page's dendrite"))
    if n_axons:
        legend_items.append(("sw-axon", "Part-of link",
                             "a page that belongs to its project's overview"))
    if n_facts or n_axons:
        legend_items.append(("sw-pulse", "Blue pulse",
                             "a fact feeding its page, a page feeding its overview; "
                             "one project at a time"))
    if demos:
        legend_items.append(("sw-query", "Orange",
                             "a real query from the demo below and the pages it "
                             "returned, in rank order, with their scores"))
    legend_list = "".join(
        f'<li><i class="sw {cls}" aria-hidden="true"></i><span><b>{esc(name)}</b> '
        f'· {esc(text)}</span></li>' for cls, name, text in legend_items)
    centre = [r for r in MAP_RINGS if r.get("centre")]
    outer = [r for r in MAP_RINGS if not r.get("centre")]
    ring_text = " → ".join(
        [f'centre {esc(r["label"])} ({esc(" · ".join(r["types"]))})' for r in centre]
        + [esc(r["label"]) for r in outer])
    private_note = (", then the private ones clockwise (named "
                    "<em>private project N</em> on hover)") if has_private else ""
    legend = (
        f'<div class="legend"><ul>{legend_list}</ul>'
        f'<div class="legend-rings"><p><span class="lk">Rings</span>{ring_text}</p>'
        '<p><span class="lk">Bearing</span>one sector per project: the public '
        f'projects at the top{private_note}.</p></div></div>')
    map_label = (f"Neural map of the Optimus brain: {_plural(len(page_nodes), 'page')} "
                 f"on {len(MAP_RINGS)} rings, {_plural(n_facts, 'fact')}, "
                 f"{_plural(n_axons, 'part-of link')}. The same data is in the "
                 "tables below and in brain.json.")
    map_section = f"""<section id="map-section">
  <div class="sec-head"><span class="sec-n">01</span><h2>The brain, mapped</h2><span class="rule"></span></div>
  {controls}
  <div class="map-grid">
    <div class="map-col">
      <div class="hud map-frame">
        <div id="map" role="img" aria-label="{esc(map_label)}"></div>
        <noscript><p class="noscript">The neural map needs JavaScript. Every number it draws is in the sections below and in <a href="brain.json">brain.json</a>.</p></noscript>
      </div>
      <div class="hud readout" id="readout" aria-live="polite">{_readout_html(demos)}</div>
    </div>
    <div class="side-col">
      <div class="hud panel" id="panel" aria-live="polite">{default_panel}</div>
      {legend}
    </div>
  </div>
</section>"""

    # ── 02 how it digests information (style A blackline) ──
    stages = []
    for i, (title, text, module, is_query) in enumerate(PIPELINE):
        stages.append(
            f'<div class="stage hud{" q" if is_query else ""}" style="--d:{i * 2.25:g}s">'
            f'<div class="st-n">{i + 1:02d}</div><div class="st-t">{esc(title)}</div>'
            f'<p>{esc(text)}</p><code>{esc(module)}</code></div>')
        if i < len(PIPELINE) - 1:
            stages.append('<div class="wire" aria-hidden="true"></div>')
    ops = "".join(f'<span class="op">{esc(op)} <b>× {n}</b></span>'
                  for op, n in sorted(stats["events_by_op"].items()))
    pipeline_section = f"""<section>
  <div class="sec-head"><span class="sec-n">02</span><h2>How it digests information</h2><span class="rule"></span></div>
  <div class="pipe">{"".join(stages)}</div>
  <div class="ops"><span class="ctl-label">Operations recorded so far</span>{ops}</div>
</section>"""

    # ── 03 corpus at a glance ──
    tiles = "".join(
        f'<div class="tile hud"><div class="t-k">{esc(label)}</div>'
        f'<div class="t-v">{stats[key]}</div><div class="t-s">{esc(sub)}</div></div>'
        for label, key, sub in TILES)
    tiles_section = f"""<section>
  <div class="sec-head"><span class="sec-n">03</span><h2>Corpus at a glance</h2><span class="rule"></span></div>
  <div class="tiles">{tiles}</div>
</section>"""

    # ── 04 retrieval, demonstrated ──
    demo_cards = []
    for i, d in enumerate(demos):
        top = max((r["score"] for r in d["results"]), default=0)
        rows = "".join(
            f'<tr><td class="rk">{k + 1}</td><td>{_result_label(r)}'
            f'<span class="ty">{esc(r["type"])}</span></td>'
            f'<td class="num">{r["score"]:g}{_score_bar(r["score"], top)}</td></tr>'
            for k, r in enumerate(d["results"]))
        demo_cards.append(
            f'<div class="demo hud"><div class="d-k">query {i + 1:02d}</div>'
            f'<div class="d-q">“{esc(d["query"])}”</div>'
            '<table><thead><tr><th>#</th><th>page</th><th class="num">score</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
            f'<button type="button" class="chip d-play" data-demo="{i}">'
            'replay on the map ↑</button></div>')
    demos_section = f"""<section>
  <div class="sec-head"><span class="sec-n">04</span><h2>Retrieval, demonstrated</h2><span class="rule"></span></div>
  <p class="sec-sub">Each query below was run through the actual retrieval engine at build time. Higher score means a better match. A page marked <span class="tag">private</span> can be <em>found</em>, but its content is never exported here.</p>
  <div class="demos">{"".join(demo_cards)}</div>
</section>"""

    # ── 05 public pages ──
    pages_html = "".join(
        f'<details class="page hud" id="page-{esc(p["id"])}"><summary>'
        f'<span class="pg-k">{esc(p["project"])} · {esc(p["type"])} · updated '
        f'{esc(str(p["updated"])[:10])} · <a href="pages/{esc(p["id"])}.md">raw</a></span>'
        f'<span class="pg-t">{esc(p["title"])}</span></summary>'
        f'<div class="page-body">{page_body_html(p["markdown"])}</div></details>'
        for p in pages)
    pages_section = f"""<section>
  <div class="sec-head"><span class="sec-n">05</span><h2>Public knowledge pages</h2><span class="rule"></span></div>
  <p class="sec-sub">The full text of every public page, as the brain holds it. Open one to read it; the front-matter at the top of each lists its claims and the source span each was cited from.</p>
  {pages_html}
</section>"""

    # ── 06 for AI agents ──
    agents_section = """<section>
  <div class="sec-head"><span class="sec-n">06</span><h2>For AI agents</h2><span class="rule"></span></div>
  <div class="hud card">
    <p>Everything public on this page is machine-readable, English and CORS-open:</p>
    <ul class="endpoints">
      <li><code>GET /brain.json</code><span>stats, graph, public pages (full markdown), retrieval demos</span></li>
      <li><code>GET /llms.txt</code><span>plain-text index of what is here and how to use it</span></li>
      <li><code>GET /pages/&lt;id&gt;.md</code><span>each public page, raw</span></li>
    </ul>
    <pre><code>curl -s https://optimus-brain-alpha.vercel.app/brain.json | jq '.stats'</code></pre>
    <p class="note">This export is a static snapshot: it changes only when the showcase is rebuilt, and the build ONLY reads the brain (the store is opened read-only).</p>
  </div>
</section>"""

    footer = (
        '<footer>'
        f'<span>snapshot of brain @ <code>{esc(commit)}</code></span>'
        f'<span>built {esc(built_at)}</span>'
        '<span>Optimus is read-only here; the live brain runs locally with Aegis Finance</span>'
        '</footer>')

    data = {
        "graph": graph,
        "layout": layout,
        # what the replay needs, and no more: a private hit carries no id
        "demos": [{"query": d["query"], "results": [
            {"page_id": r["page_id"] if r.get("public") else None,
             "type": r["type"], "score": r["score"], "public": bool(r.get("public"))}
            for r in d["results"]]} for d in demos],
        "explain": TYPE_EXPLAIN,
    }

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Optimus Brain — Neural Map</title>
<meta name="description" content="A neural map of Optimus, the memory layer behind Aegis Finance: every page a neuron, every fact a bead, a real query replayed. English-only, machine-readable.">
<meta name="theme-color" content="#000000">
<style>{_CSS}</style>
</head>
<body>
<main>
{header}

{map_section}

{pipeline_section}

{tiles_section}

{demos_section}

{pages_section}

{agents_section}

{footer}
</main>
<script type="application/json" id="brain-data">{_json_for_script(data)}</script>
<script>{_JS}</script>
</body>
</html>
"""


def render_from_json(path: Path) -> str:
    """index.html rendered from a brain.json snapshot alone — no brain DB.

    brain.json carries everything the page shows, and main() renders the
    page from the very objects it writes there, so this reproduces the page
    of the build that wrote the snapshot."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return render_html(data["stats"], data["public_pages"],
                       data["retrieval_demos"], data["graph"],
                       data["brain_commit"], data["built_at"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--from-json", nargs="?", const=str(OUT / "brain.json"), default=None,
        metavar="BRAIN_JSON",
        help="re-render ONLY index.html from a committed brain.json (default: "
             "showcase/optimus-brain/brain.json); the brain DB is not opened "
             "and nothing else is written")
    args = parser.parse_args(argv)

    if args.from_json is not None:
        src = Path(args.from_json)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "index.html").write_text(render_from_json(src), encoding="utf-8")
        print(f"index.html re-rendered from {src} -> {OUT / 'index.html'}")
        return

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
