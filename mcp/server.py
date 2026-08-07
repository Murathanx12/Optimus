"""
Optimus MCP Server — the context spine (CLAUDE.md §2: MCP is surface-agnostic).

Exposes Optimus's brain AND Aegis's verified live state to any MCP client
(Claude Code session start = the primary consumer). Hard boundary, enforced
here: everything is READ-ONLY — Optimus reads Aegis; it never owns or writes
Aegis operational data, and this server never writes the brain either
(Store(read_only=True): SQLite opened mode=ro, write methods raise).

Run (stdio):
    C:\\Users\\mrthn\\optimus\\.venv\\Scripts\\python.exe mcp/server.py

Env:
    AEGIS_REPO      local Aegis checkout (default C:\\Users\\mrthn\\aegis-finance)
    AEGIS_API_BASE  live deploy (default the Railway production URL)
    OPTIMUS_ROOT    optimus repo root (default: this file's parent's parent)

NOTE on the `mcp/` directory name: it must NOT contain an __init__.py.
A regular installed package (the MCP SDK) always wins over a same-named
namespace directory, but only as long as this directory stays a plain
script folder, not a package.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

_OPTIMUS_ROOT = Path(os.getenv("OPTIMUS_ROOT", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(_OPTIMUS_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402 — installed SDK, see note above

from core.query import format_answer, retrieve  # noqa: E402
from core.store import Store  # noqa: E402

AEGIS_REPO = Path(os.getenv("AEGIS_REPO", r"C:\Users\mrthn\aegis-finance"))
AEGIS_API = os.getenv(
    "AEGIS_API_BASE", "https://aegis-finance-production.up.railway.app"
).rstrip("/")

server = FastMCP(
    "optimus",
    instructions=(
        "Optimus: Murat's personal context layer and central brain for the "
        "Aegis program. Read-only tools for Aegis Finance verified state "
        "(live deploy), the experiment registry, guardrails/canon, session "
        "postmortems, discipline skills, and the Optimus brain corpus. "
        "START every Aegis session with session_briefing() (health + working "
        "rules) + aegis_verified_state() (live deploy). Before proposing "
        "research: brain_query + aegis_postmortems — the idea may already "
        "have a corpse with receipts."
    ),
)


def _http_json(url: str, timeout: int = 45) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "optimus-mcp/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed scheme/host from env
        return json.loads(resp.read().decode("utf-8"))


@server.tool()
def aegis_verified_state() -> str:
    """Live verified state of the Aegis deploy in ONE call: deploy commit +
    uptime, scheduler + per-lane NAV freshness (nav.all_fresh), track record
    (per-lane NAV + since-inception %), data-source health (yfinance rate,
    FRED series by name), and the last <=50 WARNING+ log records. This is
    what /go Phase 0 consumes — freshness, not liveness: if nav.all_fresh
    is false, that is the session's P0."""
    return json.dumps(_http_json(f"{AEGIS_API}/api/health/full"), indent=1)


@server.tool()
def aegis_registry(limit: int = 50) -> str:
    """The Aegis experiment registry (read-only): every trial ever recorded —
    adopted AND rejected — with the cumulative trial count that DSR/PBO
    guards deflate against, and pre-registered decision rules (e.g.
    TRIAL-001 HRP-vs-EW) embedded in notes. The registry LIVES in Aegis;
    Optimus only reads it."""
    return json.dumps(
        _http_json(f"{AEGIS_API}/api/pi/registry?limit={int(limit)}"), indent=1
    )


_CANON_FILES = [
    ("V2_GOALS", "docs/V2_GOALS.md"),
    ("TRACK_RECORD_POLICY", "docs/TRACK_RECORD_POLICY.md"),
    ("TRIAL-001", "docs/TRIALS/TRIAL-001-hrp-vs-ew.md"),
]


@server.tool()
def aegis_canon(section: str = "all") -> str:
    """Aegis guardrails + canon: V2_GOALS.md (goals, Murat's additions,
    anti-goals), TRACK_RECORD_POLICY.md (what may be called 'track record'),
    and pre-registered trial decision rules. section: 'all' | 'V2_GOALS' |
    'TRACK_RECORD_POLICY' | 'TRIAL-001' | 'anti-goals'."""
    out: list[str] = []
    for name, rel in _CANON_FILES:
        if section not in ("all", name) and not (
            section == "anti-goals" and name == "V2_GOALS"
        ):
            continue
        p = AEGIS_REPO / rel
        if not p.exists():
            out.append(f"## {name}\n(missing: {rel})")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if section == "anti-goals":
            m = re.search(r"## Anti-goals.*?(?=\n## |\Z)", text, re.S)
            text = m.group(0) if m else "(anti-goals section not found)"
        out.append(f"## {name} ({rel})\n\n{text}")
    return "\n\n---\n\n".join(out) if out else f"unknown section: {section}"


@server.tool()
def aegis_postmortems(query: str = "", limit: int = 3) -> str:
    """Session postmortems from docs/postmortems/ (Optimus-ingestible session
    log: decisions, surprises, rejected approaches). Empty query → the most
    recent N in full; otherwise keyword-scored best matches. This is how a
    fresh session learns what previous sessions broke, rejected, and why."""
    pm_dir = AEGIS_REPO / "docs" / "postmortems"
    files = sorted(pm_dir.glob("*.md"), reverse=True)
    if not files:
        return f"no postmortems found under {pm_dir}"

    if not query:
        picked = files[: int(limit)]
    else:
        terms = [t for t in re.split(r"\W+", query.lower()) if t]
        scored = []
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace").lower()
            score = sum(text.count(t) for t in terms)
            if score:
                scored.append((score, f))
        scored.sort(key=lambda x: -x[0])
        picked = [f for _, f in scored[: int(limit)]]
        if not picked:
            return f"no postmortem matches for '{query}'"

    out = []
    for f in picked:
        out.append(f"## {f.name}\n\n"
                   + f.read_text(encoding="utf-8", errors="replace"))
    return "\n\n---\n\n".join(out)


@server.tool()
def session_briefing() -> str:
    """START HERE at the top of any Aegis session. One call returns: the
    auto-generated program health page (git state of both repos, pending
    attended decisions, STATUS headline, session-memory current state) plus
    the standing working rules. Static context — pair it with
    aegis_verified_state for the LIVE deploy picture. Regenerate the health
    page with `python tools/refresh_aegis.py` after a work session."""
    health = _OPTIMUS_ROOT / "brain/projects/aegis-health/aegis-health-latest.md"
    body = (health.read_text(encoding="utf-8", errors="replace")
            if health.exists()
            else "(health page not yet generated — run tools/refresh_aegis.py)")
    rules = (
        "## Standing working rules (the short canon)\n"
        "- No skill claims before 24 months of forward record.\n"
        "- Pre-register or it didn't happen; every examination leaves a "
        "ledger entry.\n"
        "- The LLM narrates; the engine computes. No LLM allocation.\n"
        "- Backtests on our data are direction checks, never alpha claims.\n"
        "- Silent fragility is the house failure mode: fail loud, verify "
        "prod live after deploys.\n"
        "- Closed families stay closed (NEGATIVE_RESULTS.md); check the "
        "ledger before proposing an idea.\n"
        "- Gates must be calibrated before their kills are trusted "
        "(NEGATIVE_RESULTS #34).\n"
        "- Research/heavy work on Opus; hard phase stops; push back on "
        "scope creep."
    )
    return body + "\n\n" + rules


@server.tool()
def aegis_skills(name: str = "") -> str:
    """The project's discipline skills (house procedures), served over MCP so
    web/remote sessions get them too. Empty name -> list all skills with
    their trigger lines; a skill name -> that skill's full SKILL.md.
    Available: verify-prod-after-deploy, lane-integrity-check, seed-a-lane,
    pre-register-trial, silent-fragility-audit."""
    skills_dir = AEGIS_REPO / ".claude" / "skills"
    if not skills_dir.exists():
        return f"no skills dir at {skills_dir}"
    if name:
        p = skills_dir / name / "SKILL.md"
        if not p.exists():
            return (f"unknown skill '{name}'; available: "
                    + ", ".join(sorted(d.name for d in skills_dir.iterdir()
                                       if d.is_dir())))
        return p.read_text(encoding="utf-8", errors="replace")
    out = []
    for d in sorted(skills_dir.iterdir()):
        f = d / "SKILL.md"
        if not (d.is_dir() and f.exists()):
            continue
        head = f.read_text(encoding="utf-8", errors="replace")
        desc = re.search(r"^description:\s*(.+)$", head, re.M)
        out.append(f"- **{d.name}** — "
                   + (desc.group(1).strip() if desc else "(no description)"))
    return ("Aegis discipline skills (call aegis_skills(name) for full "
            "text):\n" + "\n".join(out))


@server.tool()
def brain_query(
    query: str, k: int = 3, domain: str | None = None, floor: float | None = None
) -> str:
    """Query the Optimus brain corpus (markdown pages + SQLite index,
    read-only): project state, decisions, identity-safe context. Returns a
    cited answer plus a JSON result block.

    THIS TOOL ABSTAINS. If nothing scores at or above the relevance floor it
    returns status `no_match` — with the floor and the best rejected candidates
    — instead of the nearest document. `no_match` means "not in the brain", not
    "retrieval is broken": fall back to aegis_canon / aegis_registry /
    aegis_postmortems, which read live from Aegis.

    domain: optional corpus scope — 'finance', 'finance-ancestor', 'robotics',
    'art', 'school', 'personal', 'core'. Passing it HARD-scopes: pages in other
    registered domains are dropped, and related/ancestor/unregistered pages are
    demoted below in-domain ones. Omitting it soft-scopes from query wording
    (nothing is dropped; out-of-domain pages are only demoted).
    floor: override the relevance floor (default 20.0) — lower it to inspect
    near-misses."""
    store = Store(_OPTIMUS_ROOT, read_only=True)
    try:
        result = retrieve(store, query, k=int(k), domain=domain, floor=floor)
        answer = format_answer(store, result)
        return answer + "\n\nresult: " + json.dumps(result.as_dict())
    finally:
        close = getattr(store, "close", None)
        if close:
            close()


if __name__ == "__main__":
    server.run()  # stdio transport
