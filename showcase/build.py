"""Build the PUBLIC Optimus brain showcase — a static site for Vercel.

Reads the brain STRICTLY read-only and exports ONLY the public slice:
  - aggregate corpus stats (counts by tier/type/project, event log ops)
  - the aegis-finance + aegis-quant-knowledge project pages (full text)
  - real retrieval-demo output (deterministic, LLM-free scoring)

NEVER exported: identity, dispositions, conversations, and every non-aegis
project (coursework, personal portfolio, hobbies) — those exist in the stats
only as anonymous counts. All output is English.

Outputs into showcase/optimus-brain/ (the Vercel deploy root):
  index.html   — human view
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
        # project names other than the public ones are anonymized
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


def demo_retrievals(store: Store) -> list[dict]:
    out = []
    for query in DEMO_QUERIES:
        res = retrieve(store, query, k=3)
        out.append({
            "query": query,
            "results": [
                {"page_id": p.page_id, "title": p.title, "type": p.type,
                 "project": p.project, "score": p.score,
                 # only public pages expose their path
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


def render_html(stats: dict, pages: list[dict], demos: list[dict],
                commit: str, built_at: str) -> str:
    tiles = [
        ("Pages", stats["pages"], "markdown knowledge pages"),
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

    proj_html = "".join(
        f'<li><code>{html.escape(p)}</code> — {c} pages'
        + (' <span class="badge-private">private, counts only</span>'
           if p == "private" else ' <span class="badge-public">public below</span>')
        + "</li>"
        for p, c in stats["pages_by_project"].items()
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
            f'<details class="page"><summary><strong>{html.escape(p["title"])}</strong>'
            f' <span class="meta">{html.escape(p["project"])} · {html.escape(p["type"])}'
            f' · updated {html.escape(str(p["updated"]))}'
            f' · <a href="pages/{html.escape(p["id"])}.md">raw</a></span></summary>'
            f'<div class="page-body">{md_to_html(p["markdown"])}</div></details>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Optimus Brain — Public Showcase</title>
<meta name="description" content="A read-only window into Optimus: the personal memory layer behind Aegis Finance. English-only, machine-readable.">
<style>
:root {{
  --bg: #FAFAF7; --surface: #FFFFFF; --ink: #1A1A1A; --ink-2: #52525B;
  --ink-3: #8E8E93; --line: #E4E4E0; --accent: #2C6E8F; --accent-ink: #1F546E;
  --good-bg: #E7F2E9; --good-ink: #276236; --lock-bg: #F1F0EC;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #121214; --surface: #1C1C1F; --ink: #ECECEA; --ink-2: #A9A9B2;
    --ink-3: #77777F; --line: #2C2C30; --accent: #6FB1D0; --accent-ink: #8FC5DE;
    --good-bg: #1E2F23; --good-ink: #8CC79A; --lock-bg: #232326; }}
}}
* {{ box-sizing: border-box; margin: 0; }}
body {{ background: var(--bg); color: var(--ink); font: 16px/1.6 ui-sans-serif,
  system-ui, "Segoe UI", sans-serif; padding: 0 16px 80px; }}
main {{ max-width: 880px; margin: 0 auto; }}
header {{ padding: 48px 0 8px; }}
h1 {{ font-size: 28px; letter-spacing: -0.02em; }}
h2 {{ font-size: 20px; margin: 40px 0 12px; letter-spacing: -0.01em; }}
p.lede {{ color: var(--ink-2); max-width: 64ch; }}
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
  font-size: 14.5px; color: var(--ink-2); }}
.flow b {{ color: var(--ink); font-weight: 600; }}
.flow .arrow {{ color: var(--ink-3); }}
.pill {{ display: inline-block; background: var(--lock-bg); border-radius: 999px;
  padding: 2px 10px; font-size: 13px; color: var(--ink-2); margin: 2px 4px 2px 0; }}
.badge-public, .badge-private {{ font-size: 11.5px; border-radius: 4px;
  padding: 1px 6px; vertical-align: 1px; }}
.badge-public {{ background: var(--good-bg); color: var(--good-ink); }}
.badge-private {{ background: var(--lock-bg); color: var(--ink-3); }}
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
  <h1>🧠 Optimus Brain — public showcase</h1>
  <p class="lede">Optimus is the persistent memory layer behind
  <strong>Aegis Finance</strong>: a file-based "brain" of markdown knowledge
  pages with a SQLite index, deterministic (LLM-free) retrieval, and MCP tools
  that AI sessions — Claude, DeepSeek, or any agent — consult instead of
  re-reading a whole repository. This page is a <strong>read-only window</strong>
  into it. All content is English. Personal pages (identity, dispositions,
  private projects) are excluded — only aggregate counts appear.</p>
</header>

<h2>How it digests information</h2>
<div class="card">
  <div class="flow">
    <b>ingest</b><span class="arrow">→</span>
    <span>git repos &amp; folders become typed pages (overview / structure / history / decisions) with provenance-cited claims</span>
  </div>
  <div class="flow" style="margin-top:8px">
    <b>index</b><span class="arrow">→</span>
    <span>pages, claims, aliases and edges land in one SQLite index; every operation appends to an event log</span>
  </div>
  <div class="flow" style="margin-top:8px">
    <b>retrieve</b><span class="arrow">→</span>
    <span>queries are scored deterministically (intent + alias + term overlap) — no model call, snapshot-testable, always cited</span>
  </div>
  <div class="flow" style="margin-top:8px">
    <b>serve</b><span class="arrow">→</span>
    <span>MCP tools (<code>brain_query</code>, <code>aegis_verified_state</code>, <code>aegis_registry</code>, <code>aegis_postmortems</code>) feed AI sessions verified project state</span>
  </div>
  <p style="margin-top:10px; color: var(--ink-2); font-size: 14px;">
  Ingest operations recorded so far: {ingest_html}</p>
</div>

<h2>Corpus at a glance</h2>
<div class="tiles">{tile_html}</div>
<div class="card">
  <p style="font-size:14px; color: var(--ink-2); margin-bottom: 8px;">
  Pages by project (private projects are counted, never shown):</p>
  <ul>{proj_html}</ul>
</div>

<h2>Retrieval, demonstrated (real output)</h2>
<div class="card">
  <p style="font-size:14px; color: var(--ink-2);">Each query below was run
  through the actual retrieval engine at build time. 🔒 marks a private page —
  it can be <em>found</em>, but its content is never exported here.</p>
  {demos_html}
</div>

<h2>Public knowledge pages</h2>
{pages_html}

<h2>For AI agents</h2>
<div class="card">
  <p>Everything public on this page is machine-readable, English, CORS-open:</p>
  <ul>
    <li><code>GET /brain.json</code> — stats, public pages (full markdown), retrieval demos</li>
    <li><code>GET /llms.txt</code> — plain-text index of what is here and how to use it</li>
    <li><code>GET /pages/&lt;id&gt;.md</code> — each public page raw</li>
  </ul>
  <pre><code>curl -s https://&lt;this-host&gt;/brain.json | jq '.stats'</code></pre>
  <p style="font-size:14px; color: var(--ink-2);">This export is a static
  snapshot — it changes only when the showcase is rebuilt, and the build ONLY
  reads the brain (the store is opened read-only).</p>
</div>

<footer>
  Snapshot of brain @ git <code>{commit}</code> · built {built_at} ·
  Optimus is read-only here; the live brain runs locally with Aegis Finance.
</footer>
</main>
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
    commit = brain_commit()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(exist_ok=True)

    for p in pages:
        (OUT / "pages" / f"{p['id']}.md").write_text(p["markdown"], encoding="utf-8")

    brain_json = {
        "what": "Public read-only snapshot of the Optimus brain (memory layer "
                "behind Aegis Finance). English-only. Private pages excluded; "
                "they appear only as counts.",
        "built_at": built_at, "brain_commit": commit,
        "stats": stats,
        "public_pages": pages,
        "retrieval_demos": demos,
        "how_to_use": {
            "for_ai_agents": "Fetch this file. `public_pages[*].markdown` is "
                             "the full knowledge text. Answer questions from "
                             "it in English; cite page ids.",
            "raw_pages": "GET /pages/<id>.md",
        },
    }
    (OUT / "brain.json").write_text(
        json.dumps(brain_json, indent=1, ensure_ascii=False), encoding="utf-8")

    llms = ["# Optimus Brain — public snapshot (English)",
            f"# built {built_at} · brain @ {commit}", "",
            "This host is a read-only export of the Optimus memory layer",
            "behind Aegis Finance. Machine endpoints:", "",
            "  /brain.json      full public snapshot (stats + pages + demos)",
            "  /pages/<id>.md   raw public knowledge pages:", ""]
    llms += [f"    /pages/{p['id']}.md  — {p['title']}" for p in pages]
    llms += ["", "Private content (identity, dispositions, personal projects)",
             "is excluded by construction — only aggregate counts exist here."]
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
        render_html(stats, pages, demos, commit, built_at), encoding="utf-8")

    store.close()
    print(f"showcase built -> {OUT}")
    print(f"  pages exported: {[p['id'] for p in pages]}")
    print(f"  stats: {stats['pages']} pages / {stats['claims']} claims")


if __name__ == "__main__":
    main()
