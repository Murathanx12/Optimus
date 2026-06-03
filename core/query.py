"""query — deterministic, LLM-free retrieval (CLAUDE.md §4.4).

The retrieval path makes **no** model call: resolve aliases → scope to a
project → score candidate pages by intent + term overlap → return ranked pages
with provenance. This keeps query fast, free, and snapshot-testable. The
LLM enters only for optional *synthesis* (composing a novel-answer page), which
lives behind the `core.llm` seam and is deferred — `retrieve()` already returns
useful, cited results with the seam refusing to run.

Aliases set the *project scope*; intent picks the *page within* it. So "aegis
structure" scopes to aegis-finance (via the "aegis" alias) and then the
"structure" intent selects the structure page — the alias does not drag every
query to the overview.

Scoring (deterministic, tie-broken by page id):
    + 50  page.type matches an intent keyword in the query ("structure", "history")
    + 30  no explicit intent given and page is the project overview (sensible default)
    + 20  page belongs to a project the query scoped to via an alias
    + 15  page is itself directly named by an alias (tiebreak / bare "aegis")
    +  5  per query term found in the page title
    +  2  per query term found in the page's claim texts
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .store import Store

# Query words that signal which page *type* the user wants.
_INTENT: dict[str, str] = {
    "structure": "structure", "structures": "structure", "modules": "structure",
    "module": "structure", "files": "structure", "layout": "structure",
    "tree": "structure", "architecture": "structure",
    "history": "history", "commits": "history", "commit": "history",
    "changelog": "history", "timeline": "history", "contributors": "history",
    "overview": "overview", "about": "overview", "summary": "overview",
    "what": "overview", "describe": "overview", "is": "overview",
}
# Tokens too common to carry retrieval signal.
_STOP = {"the", "a", "an", "of", "to", "for", "and", "in", "on", "me", "tell", "show"}


@dataclass
class Citation:
    source: str            # provenance span, e.g. git:aegis-finance@9c2a0e5:README.md#L3-L3
    text: str | None = None


@dataclass
class RetrievedPage:
    page_id: str
    title: str
    type: str
    project: str | None
    score: float
    path: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class QueryResult:
    query: str
    pages: list[RetrievedPage]

    @property
    def top(self) -> RetrievedPage | None:
        return self.pages[0] if self.pages else None


def _tokens(text: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9]+", " ", text.lower()).split() if t]


def _ngrams(tokens: list[str]) -> list[str]:
    """Full phrase first, then descending-length contiguous spans, then unigrams —
    so multi-word aliases ('aegis finance') match before single tokens ('aegis')."""
    out: list[str] = []
    n = len(tokens)
    for size in range(n, 0, -1):
        for i in range(n - size + 1):
            out.append(" ".join(tokens[i : i + size]))
    return out


def retrieve(store: Store, query: str, k: int = 3) -> QueryResult:
    tokens = _tokens(query)
    pages = {r["id"]: r for r in store.all_pages()}

    # 1. Alias resolution → directly named pages + the projects they belong to.
    alias_map: dict[str, set[str]] = defaultdict(set)
    for row in store.all_aliases():
        alias_map[row["alias"].lower()].add(row["page_id"])

    named: set[str] = set()
    for phrase in _ngrams(tokens):
        for pid in alias_map.get(phrase, set()):
            named.add(pid)

    projects = {pages[pid]["project"] for pid in named if pid in pages and pages[pid]["project"]}

    # 2. Candidate scope: the project(s) if identified, else named pages, else all.
    if projects:
        candidates = [r for r in pages.values() if r["project"] in projects]
    elif named:
        candidates = [pages[pid] for pid in named if pid in pages]
    else:
        candidates = list(pages.values())

    wanted_types = {_INTENT[t] for t in tokens if t in _INTENT}
    content_terms = {t for t in tokens if t not in _INTENT and t not in _STOP}

    # 3. Score.
    scored: list[RetrievedPage] = []
    for r in candidates:
        score = 0.0
        if wanted_types:
            if r["type"] in wanted_types:
                score += 50
        elif r["type"] == "overview" and projects:
            # No explicit intent but a project was named → default to its overview.
            # Gated on `projects` so unrelated queries don't false-match an overview.
            score += 30
        if r["project"] in projects:
            score += 20
        if r["id"] in named:
            score += 15

        title_l = r["title"].lower()
        claims = store.claims_for(r["id"])
        claim_blob = " ".join(c.text.lower() for c in claims)
        for term in content_terms:
            if term in title_l:
                score += 5
            if term in claim_blob:
                score += 2

        if score <= 0:
            continue

        # Citations: page-level provenance + any claim whose text hits a query term.
        page = store.read_page(r["id"])
        cites: list[Citation] = [Citation(source=s) for s in (page.sources if page else [])]
        for c in claims:
            if content_terms and any(t in c.text.lower() for t in content_terms):
                cites.append(Citation(source=c.source, text=c.text))
        scored.append(RetrievedPage(
            page_id=r["id"], title=r["title"], type=r["type"], project=r["project"],
            score=score, path=r["path"], citations=cites,
        ))

    scored.sort(key=lambda p: (-p.score, p.page_id))
    result = QueryResult(query=query, pages=scored[:k])
    store.log_event("query", target=query, detail={
        "results": [p.page_id for p in result.pages],
        "scores": [p.score for p in result.pages],
    })
    return result


def _snippet(store: Store, page_id: str, limit: int = 280) -> str:
    """First blockquote line, else first non-heading prose — for a coherent answer."""
    page = store.read_page(page_id)
    if page is None:
        return ""
    blockquote = None
    prose: list[str] = []
    for line in page.body.splitlines():
        s = line.strip()
        if s.startswith(">"):
            blockquote = s.lstrip("> ").strip()
            break
        if s and not s.startswith(("#", "-", "*", "|", "`")):
            prose.append(s)
    text = blockquote or " ".join(prose)
    return (text[:limit] + "…") if len(text) > limit else text


def format_answer(store: Store, result: QueryResult) -> str:
    """Render a coherent, cited answer for the CLI (no LLM)."""
    if not result.pages:
        return f'No brain pages matched "{result.query}".'
    top = result.pages[0]
    lines = [f"# {top.title}", "", _snippet(store, top.page_id), ""]
    seen: set[str] = set()
    cites = [c for c in top.citations if not (c.source in seen or seen.add(c.source))]
    if cites:
        lines.append("Sources:")
        for c in cites[:6]:
            lines.append(f"  - {c.source}")
    if len(result.pages) > 1:
        lines += ["", "Related pages:"]
        for p in result.pages[1:]:
            lines.append(f"  - {p.title}  ({p.page_id})")
    return "\n".join(lines)
