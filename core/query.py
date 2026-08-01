"""query — deterministic, LLM-free retrieval with abstention (CLAUDE.md §4.4).

The retrieval path makes **no** model call: resolve aliases → scope to a project
and a domain → score candidate pages by intent + term overlap → return ranked
pages with provenance, **or explicitly refuse to answer**. This keeps query
fast, free, and snapshot-testable. The LLM enters only for optional *synthesis*
(composing a novel-answer page), which lives behind the `core.llm` seam.

Aliases set the *project scope*; intent picks the *page within* it. So "aegis
structure" scopes to aegis-finance (via the "aegis" alias) and then the
"structure" intent selects the structure page — the alias does not drag every
query to the overview.

Two properties added 2026-07-29 after the Optimus audit found brain_query
returning a robotics file as the best match for a finance methodology question:

**1. A relevance floor + abstention.** Below :data:`FLOOR_SCORE` the retriever
returns *nothing* and says so, with the floor and the best rejected candidate
attached so the caller can see why. Never the best of a bad lot. A retriever
that always returns its top-k regardless of distance is manufacturing confidence
out of the absence of a floor — the same failure class as a test statistic with
no control arm.

**2. Domain scoping.** See :mod:`core.domains`. A finance question can no longer
be answered by an FRC robotics page, and the dead V5/V7 ancestor engines can
never out-rank the live program.

Scoring (deterministic, tie-broken by page id):
    + 50  page.type matches an intent keyword in the query ("structure", "history")
    + 30  no explicit intent given and page is the project overview (sensible default)
    + 20  page belongs to a project the query scoped to via an alias
    + 15  page is itself directly named by an alias (tiebreak / bare "aegis")
    +  5  per query term whose *whole word* appears in the page title
    +  2  per query term appearing in the page's active claim texts
    +  1  per query term appearing in the page body (struck-through text excluded)
    + 30  × coverage — the fraction of the query's content terms the page matched

Term matching is whole-word (token-set), not substring: the old substring test
let "i" in "how do i bake sourdough bread" match essentially every claim in the
corpus and score 11 on aegis-finance-overview. Struck-through body text
(``~~...~~``, written by `deprecate`) scores 0, the body-side counterpart of
"deprecated claims have weight 0" — otherwise a deprecated fact would come back
to life through the body.

The **coverage bonus** is what makes the floor work. Raw term hits are worth
2-5 points, so a genuine content answer and an incidental one-word collision sat
in the same 2-11 band and no floor could separate them. Coverage asks a
different question — "did this page match the *whole* query?" — which is exactly
the signal that distinguishes an answer from a coincidence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .domains import domain_for, infer_domain, is_known_domain, rank_for
from .store import Store

# Query words that signal which page *type* the user wants.
_INTENT: dict[str, str] = {
    "structure": "structure", "structures": "structure", "modules": "structure",
    "module": "structure", "files": "structure", "layout": "structure",
    "tree": "structure", "architecture": "structure",
    "history": "history", "commits": "history", "commit": "history",
    "changelog": "history", "timeline": "history", "contributors": "history",
    "overview": "overview", "summary": "overview", "describe": "overview",
}
# Tokens too common to carry retrieval signal. "what"/"is"/"why" were once
# overview-INTENT, which made every natural-language question hand +50 to
# overview pages — tolerable when the corpus was only summary pages, corpus-
# distorting once the notes channel added real content pages (2026-08-02).
# A named project still defaults to its overview via the `projects` path.
_STOP = {"the", "a", "an", "of", "to", "for", "and", "in", "on", "me", "tell",
         "show", "what", "is", "why", "was", "how", "did", "does", "do",
         "about"}

# Weight of "did this page match the whole query", added on top of raw term hits.
COVERAGE_BONUS = 30.0

# ---------------------------------------------------------------------------- #
# THE FLOOR — calibrated 2026-07-29 against the real brain (25 pages, corpus
# re-ingested at aegis-finance da6b22d). Measured top score per probe query:
#
#   ANSWERABLE (must NOT abstain)                              top score
#     "what is aegis finance"                    alias            131.0
#     "aegis structure"                          alias            106.0
#     "market engine v5 structure"               alias            102.0
#     "hku coursework"                           alias             65.0
#     "pre-registered trials and paper lanes"    content           45.0
#     "monte carlo crash prediction"             content           42.0
#     "round 13 panel"                           content           36.0
#     "freeze 158"                               content           32.0
#     "control arm invalidated trial ... placebo" content          26.4
#     "belief state regime analog allocation"    content           25.1
#     "purged cross validation embargo ..."      content           21.9   <-- weakest
#
#   NOT IN THE CORPUS (must abstain)                           top score
#     "how do i bake sourdough bread"                            12.0   <-- strongest
#     "kubernetes ingress controller tls termination"             8.0
#     "servo motor gearbox wiring harness"                        7.0
#     "quantum chromodynamics tax law"                            0.0
#
# Separating band: 12.0 → 21.9. FLOOR_SCORE = 20 sits inside it, 8 points clear
# of the strongest false positive. The gap is deliberately asymmetric — the cost
# of abstaining on a weak-but-real question (caller re-asks, or reads the repo)
# is far below the cost the audit measured: an FRC robotics page returned at
# score 4.0, with a number next to it, as the answer to a finance methodology
# question. When in doubt, say nothing.
#
# Two ways this drifts and needs re-probing: a much larger corpus (more pages =
# more chances for an incidental collision to clear 20) or a change to the term
# weights / COVERAGE_BONUS above. Re-run the probe in docs/REINGEST.md if either
# happens. Callers who want to see near-misses pass an explicit `floor=`.
# ---------------------------------------------------------------------------- #
FLOOR_SCORE = 20.0


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
    domain: str = "core"
    rank: int = 0                                   # domain tier, 0 = in scope
    matched_terms: list[str] = field(default_factory=list)
    coverage: float = 0.0                           # matched / total content terms

    def diagnostic(self) -> dict:
        """Compact machine-readable form — what a caller needs to see WHY."""
        return {
            "page_id": self.page_id,
            "title": self.title,
            "domain": self.domain,
            "score": round(self.score, 3),
            "coverage": round(self.coverage, 3),
            "matched_terms": self.matched_terms,
        }


@dataclass
class QueryResult:
    query: str
    pages: list[RetrievedPage]
    floor: float = FLOOR_SCORE
    abstained: bool = False
    # Best candidates that FELL BELOW the floor. Populated only when abstaining,
    # so the caller can see what was rejected and by how much.
    rejected: list[RetrievedPage] = field(default_factory=list)
    domain: str | None = None            # the domain scope actually applied
    domain_source: str = "none"          # "requested" | "inferred" | "none"

    @property
    def top(self) -> RetrievedPage | None:
        return self.pages[0] if self.pages else None

    def as_dict(self) -> dict:
        """Structured result — this is what `no_match` looks like on the wire."""
        out: dict = {
            "query": self.query,
            "status": "no_match" if self.abstained else (
                "ok" if self.pages else "empty"),
            "floor": self.floor,
            "domain": self.domain,
            "domain_source": self.domain_source,
            "matched": [p.diagnostic() for p in self.pages],
        }
        if self.abstained:
            out["best_rejected"] = [p.diagnostic() for p in self.rejected]
            out["reason"] = (
                f"no page scored at or above the relevance floor ({self.floor}); "
                "returning nothing rather than the nearest document"
            )
        return out


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


_STRUCK = re.compile(r"~~.*?~~", re.S)


def _body_tokens(body: str) -> set[str]:
    """Whole-word tokens of a page body, with struck-through spans removed.

    `deprecate` strikes a dead fact as ``~~Buzzer — alerts the operator~~``; the
    word survives in the file. Scoring it would resurrect a fact the deprecation
    pipeline was built to kill, so struck spans carry weight 0 — the exact rule
    already applied to deprecated claims.
    """
    return set(_tokens(_STRUCK.sub(" ", body)))


def retrieve(
    store: Store,
    query: str,
    k: int = 3,
    domain: str | None = None,
    floor: float | None = None,
) -> QueryResult:
    """Retrieve up to `k` pages, or abstain.

    domain — scope semantics (documented in docs/REINGEST.md too):
      * **passed explicitly** → HARD scope. Pages in other registered domains are
        removed from the candidate set entirely. Related domains (e.g. the
        V5/V7 ancestors under `finance`), `core` identity pages, and pages whose
        project is not yet registered are kept but demoted: they can never
        out-rank an in-domain page, whatever they score.
      * **omitted** → SOFT scope. The domain is inferred from distinctive query
        terms; if inference is confident, out-of-domain pages are demoted but
        never dropped. If inference is unsure (no markers, or a tie), no scoping
        is applied at all and behaviour is exactly as before.
    Either way the floor still applies — scoping changes the *order*, abstention
    decides whether anything is good enough to return.
    """
    floor = FLOOR_SCORE if floor is None else float(floor)
    tokens = _tokens(query)
    pages = {r["id"]: r for r in store.all_pages()}

    # 0. Domain scope: explicit request wins; otherwise infer from the query.
    domain_source = "none"
    if domain:
        domain = domain.strip().lower()
        if not is_known_domain(domain):
            raise ValueError(f"unknown domain: {domain}")
        domain_source = "requested"
    else:
        inferred = infer_domain(tokens)
        if inferred:
            domain, domain_source = inferred, "inferred"

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

    # A hard (explicitly requested) scope drops out-of-domain pages outright;
    # a soft/inferred scope only demotes them (see rank_for).
    if domain_source == "requested":
        candidates = [r for r in candidates
                      if rank_for(domain_for(r["project"]), domain) < 2]

    wanted_types = {_INTENT[t] for t in tokens if t in _INTENT}
    content_terms = {t for t in tokens if t not in _INTENT and t not in _STOP}

    # Tombstoned entities carry weight 0 *everywhere* — claims (already excluded
    # by status), struck body lines, AND a body rebuilt by a later re-ingest.
    # Without this, body scoring would quietly resurrect exactly the dead facts
    # `deprecate` exists to kill: the strike-through survives only until the next
    # ingest rewrites the page from source.
    dead: set[str] = set()
    for alias in store.tombstoned_aliases():
        dead.update(_tokens(alias))
    content_terms -= dead

    # 3. Score.
    scored: list[RetrievedPage] = []
    for r in candidates:
        score = 0.0
        if r["project"] in projects:
            score += 20
        if r["id"] in named:
            score += 15

        title_terms = set(_tokens(r["title"]))
        claims = store.claims_for(r["id"], status="active")  # deprecated claims have weight 0
        claim_terms = set(_tokens(" ".join(c.text for c in claims)))
        page = store.read_page(r["id"])
        # Index pages (notes-channel hubs) are navigation: their body is a list
        # of other pages' titles, which is pure term soup. They stay findable by
        # alias/title/intent but never win on body content they merely point at.
        body_terms = (_body_tokens(page.body)
                      if page and r["type"] != "index" else set())

        matched: set[str] = set()
        for term in content_terms:
            if term in title_terms:
                score += 5
                matched.add(term)
            if term in claim_terms:
                score += 2
                matched.add(term)
            if term in body_terms:
                score += 1
                matched.add(term)

        coverage = (len(matched) / len(content_terms)) if content_terms else 0.0
        score += COVERAGE_BONUS * coverage

        # Intent selects AMONG relevant pages; it never creates relevance.
        # Before this gate (2026-08-02), "about ..." handed +50 to EVERY
        # overview in the corpus — a robotics overview scored 50, above the
        # abstention floor, on a finance query it matched zero terms of.
        anchored = bool(matched) or r["project"] in projects or r["id"] in named
        if wanted_types:
            if r["type"] in wanted_types and anchored:
                score += 50
        elif r["type"] == "overview" and r["project"] in projects:
            # No explicit intent but a project was named → default to its overview.
            score += 30

        if score <= 0:
            continue

        # Citations: page-level provenance + any claim whose text hits a query term.
        cites: list[Citation] = [Citation(source=s) for s in (page.sources if page else [])]
        for c in claims:
            if matched and set(_tokens(c.text)) & matched:
                cites.append(Citation(source=c.source, text=c.text))

        pdomain = domain_for(r["project"])
        scored.append(RetrievedPage(
            page_id=r["id"], title=r["title"], type=r["type"], project=r["project"],
            score=score, path=r["path"], citations=cites,
            domain=pdomain, rank=rank_for(pdomain, domain),
            matched_terms=sorted(matched), coverage=coverage,
        ))

    # 4. Rank: domain tier FIRST (an out-of-scope page can never out-rank an
    #    in-scope one), then score, then page id for determinism.
    scored.sort(key=lambda p: (p.rank, -p.score, p.page_id))

    # 5. The floor. Everything below it is rejected — including, deliberately,
    #    the best of a bad lot.
    kept = [p for p in scored if p.score >= floor]
    abstained = bool(scored) and not kept
    result = QueryResult(
        query=query,
        pages=kept[:k],
        floor=floor,
        abstained=abstained,
        rejected=scored[:k] if abstained else [],
        domain=domain,
        domain_source=domain_source,
    )
    store.log_event("query", target=query, detail={
        "results": [p.page_id for p in result.pages],
        "scores": [p.score for p in result.pages],
        "floor": floor,
        "abstained": abstained,
        "domain": domain,
        "domain_source": domain_source,
        "rejected": [p.page_id for p in result.rejected],
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


def format_no_match(result: QueryResult) -> str:
    """The explicit refusal. Names the floor and what was rejected, so the caller
    can tell "nothing relevant" apart from "retrieval is broken"."""
    lines = [
        f'no_match: "{result.query}"',
        "",
        f"Nothing in the brain scored at or above the relevance floor "
        f"({result.floor:g}). Returning nothing rather than the nearest document.",
    ]
    if result.domain:
        lines.append(f"Scope: {result.domain} ({result.domain_source}).")
    if result.rejected:
        lines += ["", "Best rejected candidates (below floor):"]
        for p in result.rejected:
            lines.append(
                f"  - {p.page_id}  score {p.score:g} < {result.floor:g}"
                f"  [domain: {p.domain}; matched {len(p.matched_terms)} term(s)"
                f", coverage {p.coverage:.0%}]"
            )
    lines += [
        "",
        "Try naming a project (e.g. \"aegis structure\"), narrowing the question, "
        "or use the live sources: aegis_canon / aegis_registry / aegis_postmortems.",
    ]
    return "\n".join(lines)


def format_answer(store: Store, result: QueryResult) -> str:
    """Render a coherent, cited answer for the CLI (no LLM)."""
    if result.abstained:
        return format_no_match(result)
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
