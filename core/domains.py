"""domains — corpus partitioning, so a robotics file can never answer a finance
question (Optimus audit 2026-07-29, fix #2).

The measured defect: querying *"control arm invalidated trial pseudo-event
placebo"* returned `frc-plane-school-overview` (an FRC robotics project, with
mojibake'd UTF-16 text) at score **4.0**, above `aegis-finance-overview` at
**2.0**. The corpus is mixed-domain — a live finance program, its two dead
ancestor codebases, a robotics project, 3D art, coursework — and retrieval
treated all of it as one flat pool.

**Where the domain tag lives.** The tag is *derived*, not stored: this module is
a declarative registry mapping a page's ``project`` slug → a domain. That is
deliberate — the SQLite index is a derived artifact opened **mode=ro** by the MCP
server, so adding a column would need a migration the read-only path cannot run.
A registry needs no migration, is reviewable in one screen, and reindex-proof.

**Registering a new project is a one-line edit here.** An *unregistered* project
resolves to ``unscoped``: it is never preferred, and — importantly — it is never
*dropped* either. Forgetting to register a project degrades ranking; it never
silently deletes a project from every scoped query.

Domains:
  finance           the live program (aegis-finance and its knowledge base)
  finance-ancestor  V5/V7 market engines — superseded code, kept for lineage
  robotics / art / school / personal   other life domains
  core              identity + dispositions (no project) — context, never the answer
  unscoped          registered nowhere yet
"""

from __future__ import annotations

FINANCE = "finance"
FINANCE_ANCESTOR = "finance-ancestor"
ROBOTICS = "robotics"
ART = "art"
SCHOOL = "school"
PERSONAL = "personal"
CORE = "core"          # identity / dispositions — pages with no project
UNSCOPED = "unscoped"  # project not registered below

# project slug → domain. ADD NEW PROJECTS HERE (see module docstring).
PROJECT_DOMAIN: dict[str, str] = {
    "aegis-finance": FINANCE,
    "aegis-quant-knowledge": FINANCE,
    "aegis-module": FINANCE,
    "aegis-research": FINANCE,
    "market-engine-v5": FINANCE_ANCESTOR,
    "market-prediction-engine": FINANCE_ANCESTOR,
    "frc-plane-school": ROBOTICS,
    "blender-art": ART,
    "hku-coursework": SCHOOL,
    "portfolio": PERSONAL,
}

# domain → domains that may still appear, but always ranked BELOW it.
# `core` is related to everything: identity/disposition pages are useful context
# for any question and must never out-rank the project docs that answer it.
RELATED: dict[str, tuple[str, ...]] = {
    FINANCE: (FINANCE_ANCESTOR, CORE),
    FINANCE_ANCESTOR: (FINANCE, CORE),
    ROBOTICS: (CORE,),
    ART: (CORE,),
    SCHOOL: (CORE,),
    PERSONAL: (CORE,),
    CORE: (),
}

# Distinctive terms that signal a query's domain. Only used when the caller does
# NOT pass an explicit domain (soft preference — see query.retrieve). Kept
# deliberately narrow: a word that could plausibly appear in two domains
# ("model", "data", "test", "control") is NOT a marker.
DOMAIN_MARKERS: dict[str, frozenset[str]] = {
    FINANCE: frozenset({
        "portfolio", "sharpe", "sortino", "backtest", "volatility", "sector",
        "ticker", "trial", "hedge", "drawdown", "equity", "equities", "cvar",
        "monte", "carlo", "garch", "regime", "rebalance", "nav", "trading",
        "market", "markets", "stock", "stocks", "etf", "yield", "fred",
        "earnings", "insider", "purged", "deflated", "overfitting", "pbo",
        "dsr", "spy", "vix", "bond", "bonds", "valuation", "fama", "french",
        "hrp", "cointegration", "prereg", "placebo", "13f", "edgar", "quant",
        "finance", "financial", "investing", "investment",
    }),
    ROBOTICS: frozenset({
        "robot", "robotics", "frc", "servo", "motor", "motors", "encoder",
        "chassis", "arduino", "pcb", "kicad", "drone", "plane", "airframe",
        "actuator", "gyro", "odometry", "firmware", "mecanum", "gearbox",
        "solidworks", "sensor", "sensors", "cad", "wiring", "buzzer",
    }),
    ART: frozenset({
        "blender", "render", "rendering", "mesh", "sculpt", "shader", "texture",
        "uv", "animation", "rig", "rigging", "substance", "zbrush", "topology",
    }),
    SCHOOL: frozenset({
        "coursework", "lecture", "lectures", "exam", "exams", "assignment",
        "hku", "semester", "homework", "syllabus", "midterm", "gpa",
    }),
}

_ALL_DOMAINS = (FINANCE, FINANCE_ANCESTOR, ROBOTICS, ART, SCHOOL, PERSONAL,
                CORE, UNSCOPED)


def domain_for(project: str | None) -> str:
    """Domain of a page, from its project slug. No project → `core`."""
    if not project:
        return CORE
    return PROJECT_DOMAIN.get(project, UNSCOPED)


def is_known_domain(domain: str) -> bool:
    return domain in _ALL_DOMAINS


def rank_for(page_domain: str, requested: str | None) -> int:
    """Rank tier of a page under a requested domain. Lower sorts first.

        0  in the requested domain            (primary)
        1  related, `core`, or `unscoped`     (allowed, always below primary)
        2  a different, registered domain     (out of scope)

    Tier is the FIRST sort key, so no tier-1/2 page can ever out-rank a tier-0
    page no matter how high it scores. `unscoped` sits at tier 1 on purpose: an
    unregistered project degrades to "demoted", never to "deleted".
    """
    if requested is None:
        return 0
    if page_domain == requested:
        return 0
    if page_domain in RELATED.get(requested, ()) or page_domain == UNSCOPED:
        return 1
    return 2


def infer_domain(tokens: list[str]) -> str | None:
    """Guess a query's domain from distinctive markers, or None if unclear.

    Requires a *strict* winner: ties and zero-hit queries return None (→ no
    scoping at all). Ancestor domains are never inferred as primary — they exist
    only as the demoted `RELATED` tier of `finance`.
    """
    counts: dict[str, int] = {}
    seen = set(tokens)
    for domain, markers in DOMAIN_MARKERS.items():
        hits = len(seen & markers)
        if hits:
            counts[domain] = hits
    if not counts:
        return None
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return None                      # ambiguous → don't scope
    return ordered[0][0]
