"""Deterministic public neural architecture. Never opens the brain database.

Visual grammar: .claude/skills/orbit-blackline-visuals and showcase/build.py.
Curated public modules, not a private memory export or measured query replay.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import html
import json
import math
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SOURCE = "https://github.com/Murathanx12/Optimus/blob/main/"
SECTORS = ["Capture", "Memory", "Retrieval", "Learning"]
# id, label, sector, ring, public source, purpose, source-documented responsibilities.
ROWS = [
 ("context", "DURABLE CONTEXT", -1, 0, "core/store.py", "Readable memory survives a conversation. Markdown is the source of truth; SQLite is its rebuildable search index.", ["Readable pages", "Rebuildable index", "Source references"]),
 ("repositories", "Repository history", 0, 3, "core/ingest.py", "Repository ingestion preserves selected project structure and history. It does not imply every document has been read.", ["Structure", "History", "Project scope"]),
 ("notes", "Selected notes", 0, 3, "core/ingest.py", "Explicit notes ingestion preserves selected Markdown text and source metadata. The operator chooses the material to ingest.", ["Selected text", "Source metadata"]),
 ("ingest", "Ingestion", 0, 2, "core/ingest.py", "Ingestion converts supported inputs into project-scoped memory pages with source references.", ["Source selection", "Stable records", "Project scope"]),
 ("schema", "Page + claim schema", 0, 1, "core/schema.py", "Page and claim models carry tiers, aliases, status and source information. A stored claim is a recorded assertion requiring source checks, not automatic truth.", ["Tiers", "Aliases", "Claim provenance"]),
 ("markdown", "Markdown pages", 1, 3, "core/store.py", "Plain Markdown files retain readable memory. They can be inspected independently of a particular assistant.", ["Readable files", "Source of truth", "Portable context"]),
 ("store", "Memory store", 1, 2, "core/store.py", "The store writes and reads pages, records relationships and events, and derives the SQLite index.", ["Page records", "Relationships", "Event ledger"]),
 ("index", "SQLite index", 1, 1, "core/store.py", "A derived index supplies page, claim and alias lookup. Reindexing rebuilds it from Markdown pages.", ["Lookup", "Aliases", "Reindexing"]),
 ("sources", "Source spans", 1, 2, "core/schema.py", "Sources connect remembered statements to the material from which they were recorded. Missing or stale evidence stays a review concern.", ["Source paths", "Spans", "Version context"]),
 ("client", "AI assistants", 2, 3, "mcp/server.py", "Compatible assistants request focused context through local MCP tools. The public website has no connection to the private brain.", ["Local client", "Focused context"]),
 ("mcp", "MCP interface", 2, 2, "mcp/server.py", "The local server exposes brain queries, session briefing and project-specific integrations. Tools depend on installation and configured services.", ["Brain query", "Session briefing", "Skill access"]),
 ("query", "Scoped retrieval", 2, 1, "core/query.py", "Retrieval ranks relevant memory and returns source citations. A relevance floor can produce an explicit no-match result.", ["Ranking", "Citations", "No-match result"]),
 ("domains", "Domain routing", 2, 2, "core/domains.py", "Domain rules guide a question toward relevant project scopes rather than treating all stored context as interchangeable.", ["Aliases", "Domain filters", "Project context"]),
 ("skills", "Reusable skills", 3, 3, "mcp/server.py", "The skill interface lets an assistant inspect project instructions. A skill needs to be discovered and read before it can guide the next task.", ["Discovery", "Instructions", "Reuse"]),
 ("audit", "Source audit", 3, 2, "core/audit.py", "Audit checks detect memory whose source has drifted. A finding is a reason to inspect the source, not proof the stored statement is false.", ["Source drift", "Review findings"]),
 ("deprecate", "Deprecation", 3, 1, "core/deprecate.py", "Deprecation records obsolete context and tombstones so later ingestion does not silently revive it.", ["Tombstones", "Obsolete context"]),
 ("distill", "Distillation", 3, 2, "core/distill.py", "Distillation proposes a smaller set of memory updates from selected context. It is distinct from training a new foundation model.", ["Selected context", "Proposed updates"]),
]
EDGES = [
 ("repositories", "ingest", "records structure and history"), ("notes", "ingest", "supplies selected text"),
 ("ingest", "schema", "creates typed records"), ("schema", "store", "defines stored pages and claims"),
 ("store", "markdown", "preserves readable pages"), ("store", "index", "derives searchable records"),
 ("store", "sources", "retains source metadata"), ("store", "context", "persists project context"),
 ("index", "query", "supplies indexed candidates"), ("domains", "query", "guides scoped retrieval"),
 ("query", "mcp", "returns source-linked context"), ("mcp", "client", "serves compatible assistants"),
 ("skills", "mcp", "exposes reusable instructions"), ("audit", "sources", "checks source drift"),
 ("deprecate", "store", "marks obsolete context"), ("distill", "store", "proposes memory updates"),
 ("context", "query", "makes retained context available"), ("audit", "deprecate", "informs review of stale context"),
]

def graph() -> dict:
    nodes = []
    for ident, label, sector, ring, module, purpose, capabilities in ROWS:
        if not (ROOT / module).is_file():
            raise ValueError(f"Missing public source: {module}")
        siblings = [r for r in ROWS if r[2:4] == (sector, ring)]
        ordinal = next(i for i, r in enumerate(siblings) if r[0] == ident)
        angle = -135 + 90 * sector + (ordinal - (len(siblings) - 1) / 2) * 30 if sector >= 0 else 0
        radius, a = [0, 118, 220, 322][ring], math.radians(angle)
        nodes.append(dict(id=ident, label=label, sector=sector, ring=ring, module=module,
                          purpose=purpose, capabilities=capabilities, href=SOURCE + module,
                          x=round(600 + radius * math.cos(a), 2), y=round(440 + radius * math.sin(a), 2), angle=angle))
    return dict(kind="curated-public-module-architecture", version=1, sectors=SECTORS,
                nodes=nodes, edges=[dict(source=s, target=t, relation=r) for s,t,r in EDGES],
                route=["domains", "query", "mcp", "client"], route_label="Illustrative walkthrough: choose context, retrieve sources, serve the assistant")

def edge_path(s: dict, t: dict, nodes: list) -> str:
    """Declared curves with clipped terminals and deterministic soma clearance."""
    dx, dy = t["x"]-s["x"], t["y"]-s["y"]
    best = None
    for bend in [.12, -.12, .28, -.28, .46, -.46, .7, -.7]:
        cx, cy = (s["x"]+t["x"])/2-dy*bend, (s["y"]+t["y"])/2+dx*bend
        def endpoint(n, other):
            vx,vy = other[0]-n["x"],other[1]-n["y"]
            scale = ((25 if not n["ring"] else 12)+9)/max(1,math.hypot(vx,vy))
            return n["x"]+vx*scale,n["y"]+vy*scale
        start,end = endpoint(s,(cx,cy)),endpoint(t,(cx,cy))
        penalty = abs(bend)*.01
        for k in range(1,40):
            f=k/40
            x=(1-f)**2*start[0]+2*(1-f)*f*cx+f*f*end[0]
            y=(1-f)**2*start[1]+2*(1-f)*f*cy+f*f*end[1]
            for n in nodes:
                if n["id"] in (s["id"],t["id"]): continue
                clearance=(25 if not n["ring"] else 12)+20
                penalty += max(0,clearance-math.hypot(x-n["x"],y-n["y"]))**2
        candidate=(penalty,start,end,cx,cy)
        if best is None or penalty<best[0]: best=candidate
    _,start,end,cx,cy=best
    return f'M{start[0]:.2f},{start[1]:.2f}Q{cx:.2f},{cy:.2f} {end[0]:.2f},{end[1]:.2f}'

def svg(data: dict, interactive: bool = False) -> str:
    esc = html.escape
    byid = {n["id"]: n for n in data["nodes"]}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="160 40 880 800" role="img" aria-labelledby="neural-title neural-desc" class="neural-svg">',
      '<title id="neural-title">Optimus neural architecture</title><desc id="neural-desc">A curated map of public modules: capture, durable memory, scoped retrieval and learning. Blue signals travel along module relationships. This is not a private knowledge export.</desc>',
      '<style>text{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}.label{fill:#fff;font-size:15px;paint-order:stroke fill;stroke:#000;stroke-width:6px;stroke-linejoin:round}.meta{fill:#aaa;font-size:11px;letter-spacing:2px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.edge{fill:none;stroke:#fff;stroke-opacity:.14;stroke-width:1.2}.flow{fill:none;stroke:#6fb0ff;stroke-width:2;stroke-dasharray:3 42;animation:current 9s linear infinite}.soma{fill:#000;stroke:#fff;stroke-opacity:.75;stroke-width:1.3}.membrane{fill:none;stroke:#fff;stroke-opacity:.16}.bead{fill:#fff;fill-opacity:.6}.dendrite{fill:none;stroke:#fff;stroke-opacity:.25}.sector{fill:#aaa;font-size:13px;letter-spacing:3px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}@keyframes current{to{stroke-dashoffset:-180}}@media(prefers-reduced-motion:reduce){.flow{animation:none;stroke-dasharray:none;stroke-opacity:.28}}.paused .flow{animation-play-state:paused}.node{cursor:pointer}.node.selected .soma,.node:focus .soma{stroke:#6fb0ff;fill:#000}.node.selected .label{fill:#6fb0ff}.edge.trace{stroke:#ff8a1f;stroke-opacity:.85;stroke-width:2}.node.dim{opacity:.18}</style>',
      '<rect width="1200" height="880" fill="#000"/><g id="network">']
    for radius in [118, 220, 322]:
        parts.append(f'<circle cx="600" cy="440" r="{radius}" fill="none" stroke="#fff" stroke-opacity=".08" stroke-dasharray="2 9"/>')
    for sector,label in enumerate(SECTORS):
        a = math.radians(-135 + sector * 90)
        x,y = 600 + 475 * math.cos(a), 440 + 475 * math.sin(a)
        parts.append(f'<text class="sector" text-anchor="middle" x="{x:.2f}" y="{y:.2f}">{label.upper()}</text>')
    for i, edge in enumerate(data["edges"]):
        s,t = byid[edge["source"]], byid[edge["target"]]
        path = edge_path(s,t,data["nodes"])
        parts.append(f'<path class="edge" data-source="{s["id"]}" data-target="{t["id"]}" d="{path}"/><path class="flow" data-source="{s["id"]}" data-target="{t["id"]}" style="animation-delay:-{i*.47:.2f}s" d="{path}"/>')
    for n in data["nodes"]:
        a,x,y = math.radians(n["angle"]),n["x"],n["y"]
        radius = 12 if n["ring"] else 25
        at = f' data-node="{n["id"]}" tabindex="0" role="button" aria-label="Explore {esc(n["label"])}"' if interactive else ''
        parts.append(f'<g class="node"{at}><circle class="membrane" cx="{x}" cy="{y}" r="{radius+7}"/>')
        for k,_ in enumerate(n["capabilities"]):
            theta = a+(k-(len(n["capabilities"])-1)/2)*.62
            ex,ey = x+math.cos(theta)*48,y+math.sin(theta)*48
            parts.append(f'<path class="dendrite" d="M{x},{y}Q{x+math.cos(theta)*30:.2f},{y+math.sin(theta)*30:.2f} {ex:.2f},{ey:.2f}"/><circle class="bead" cx="{ex:.2f}" cy="{ey:.2f}" r="2.6"/>')
        parts.append(f'<circle class="soma" cx="{x}" cy="{y}" r="{radius}"/>')
        if not n["ring"]:
            parts.append(f'<text class="label" text-anchor="middle" x="{x}" y="{y-58}">DURABLE CONTEXT</text><text class="meta" text-anchor="middle" x="{x}" y="{y-38}">MARKDOWN + SQLITE</text>')
        else:
            lx,ly = x-math.sin(a)*24,y+math.cos(a)*24
            anchor = "start" if lx >= 600 else "end"
            parts.append(f'<text class="label" text-anchor="{anchor}" x="{lx:.2f}" y="{ly:.2f}">{esc(n["label"])}</text>')
        parts.append('</g>')
    parts.append('</g></svg>')
    return ''.join(parts)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = graph()
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    directory = ''.join(f'<button type="button" data-pick="{n["id"]}">{html.escape(n["label"])}</button>' for n in data["nodes"])
    page = (OUT / "index.template.html").read_text(encoding="utf-8").replace("{{MAP}}",svg(data,True)).replace("{{DATA}}",serialized).replace("{{DIRECTORY}}", directory)
    embed_section = re.search(r'<section id="neural-map".*?(?=<section id="system")', page, re.S).group()
    css = (OUT / "style.css").read_text(encoding="utf-8")
    js = (OUT / "script.js").read_text(encoding="utf-8")
    embed = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Optimus neural architecture</title><style>'+css+'body.embed main{padding:20px;max-width:1440px}body.embed section{margin-top:0}body.embed .section-head h2{font-size:22px}</style></head><body class="embed"><main>'+embed_section+'</main><script type="application/json" id="architecture-data">'+serialized+'</script><script>'+js+'</script></body></html>\n'
    script_hash=base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii")
    headers={"cleanUrls":True,"rewrites":[{"source":"/favicon.ico","destination":"/mark.svg"}],"headers":[{"source":"/(.*)","headers":[
      {"key":"X-Content-Type-Options","value":"nosniff"},
      {"key":"Referrer-Policy","value":"strict-origin-when-cross-origin"},
      {"key":"Content-Security-Policy","value":f"default-src 'self'; script-src 'self' 'sha256-{script_hash}'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'self' https://murathan.info https://www.murathan.info; base-uri 'self'; object-src 'none'"}]}]}
    outputs = {"architecture.json":json.dumps(data,ensure_ascii=False,indent=2)+"\n", "neural-map.svg":svg(data)+"\n", "index.html":page, "neural-map.html":embed, "vercel.json":json.dumps(headers,indent=2)+"\n"}
    stale=[]
    for name,value in outputs.items():
        target=OUT/name
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != value: stale.append(name)
        else: target.write_text(value,encoding="utf-8",newline="\n")
    if stale: raise SystemExit("Stale public outputs: "+", ".join(stale))
    print("Public neural architecture: "+("checked" if args.check else "generated"))

if __name__ == "__main__": main()
