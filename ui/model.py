"""Pure data-model builders for the read-only brain viewer.

These functions turn a (read-only) Store + an AuditReport into the JSON payloads
the frontend renders. They are deliberately free of HTTP so they can be tested
directly. Nothing here mutates the brain — the only Store calls are reads, and
the visual mapping (tier→shape, state→color) lives in the frontend.

Node audit aggregation (a page summarizes its claims' three audit states):
  drifted           — ANY claim drifted. Loud red. "the brain believes something wrong."
  verified          — no drift, at least one claim verified. Confirmed-true, nothing wrong.
  unverifiable-here — no drift, no verified, but something uncheckable from this machine.
  skipped           — only un-auditable (malformed-span) claims.
  none              — page carries no claims (e.g. the identity seed).
"""

from __future__ import annotations

from core.audit import (
    STATE_DRIFTED,
    STATE_SKIPPED,
    STATE_UNVERIFIABLE,
    STATE_VERIFIED,
    AuditReport,
)
from core.store import Store

NODE_NONE = "none"

# Priority for collapsing many claim states into one node color. Drift dominates
# (it is the one state that means "wrong"); a confirmed-true page beats a merely
# uncheckable one. Order is load-bearing — see module docstring.
_PRIORITY = [STATE_DRIFTED, STATE_VERIFIED, STATE_UNVERIFIABLE, STATE_SKIPPED]


def aggregate_state(states: list[str]) -> str:
    if not states:
        return NODE_NONE
    present = set(states)
    for s in _PRIORITY:
        if s in present:
            return s
    return NODE_NONE


def _audit_index(report: AuditReport) -> dict[str, object]:
    """claim_id -> ClaimAudit, for binding audit results onto claims/pages."""
    return {r.claim_id: r for r in report.results}


def build_graph(store: Store, report: AuditReport) -> dict:
    """Nodes = pages (all statuses), edges = typed edges. Each node carries its
    aggregate audit state plus per-state counts so the frontend can color + filter."""
    idx = _audit_index(report)
    nodes = []
    page_ids = set()
    for p in store.all_pages_any_status():
        pid = p["id"]
        page_ids.add(pid)
        claims = store.claims_for(pid)
        counts = {STATE_VERIFIED: 0, STATE_DRIFTED: 0, STATE_UNVERIFIABLE: 0, STATE_SKIPPED: 0}
        states = []
        for c in claims:
            r = idx.get(c.id)
            st = r.state if r else STATE_SKIPPED
            states.append(st)
            counts[st] = counts.get(st, 0) + 1
        nodes.append({
            "id": pid,
            "title": p["title"],
            "tier": p["tier"],
            "type": p["type"],
            "project": p["project"],
            "status": p["status"],
            "claim_count": len(claims),
            "audit_state": aggregate_state(states),
            "audit_counts": counts,
        })

    edges = [
        {"source": e["src_page_id"], "target": e["dst_page_id"], "rel": e["rel"]}
        for e in store.all_edges()
        # only edges whose endpoints are real nodes (defensive; FKs already enforce)
        if e["src_page_id"] in page_ids and e["dst_page_id"] in page_ids
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "pages": len(nodes),
            "edges": len(edges),
            "verified": report.verified,
            "drifted": report.drifted,
            "unverifiable": report.unverifiable,
            "skipped": report.skipped,
            "claims": len(report.results),
            "tombstones": len(store.list_tombstones()),
        },
    }


def page_detail(store: Store, report: AuditReport, page_id: str) -> dict | None:
    """Full page + its claims, each with kind/text/rationale/quote/source/status and
    its three-state audit result (with as_of for unverifiable last-known-good)."""
    page = store.read_page(page_id)
    if page is None:
        return None
    idx = _audit_index(report)
    claims = []
    for c in store.claims_for(page_id):
        r = idx.get(c.id)
        claims.append({
            "id": c.id,
            "kind": c.kind,
            "text": c.text,
            "rationale": c.rationale,
            "quote": c.quote,
            "source": c.source,
            "status": c.status,
            "tier": c.tier,
            "created": c.created,
            "audit": {
                "state": r.state if r else STATE_SKIPPED,
                "detail": r.detail if r else "no audit result",
                "as_of": r.as_of if r else None,
            },
        })
    return {
        "id": page.id,
        "title": page.title,
        "tier": int(page.tier),
        "type": page.type,
        "project": page.project,
        "status": page.status,
        "aliases": page.aliases,
        "tags": page.tags,
        "sources": page.sources,
        "source_root": page.source_root,
        "created": page.created,
        "updated": page.updated,
        "body": page.body,
        "claims": claims,
    }


def tombstones(store: Store) -> list[dict]:
    """Deprecated entities: reason + when + the aliases/pages they touched."""
    return store.list_tombstones()


def search(store: Store, query: str) -> list[dict]:
    """Alias-resolving search. Exact alias hits rank first, then substring matches
    across aliases, page titles, and ids. Returns page stubs (deduped, ordered)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    exact = set(store.resolve_alias(q))
    hits: dict[str, dict] = {}
    title_by_id = {p["id"]: p["title"] for p in store.all_pages_any_status()}
    # exact alias matches first
    for pid in exact:
        hits[pid] = {"page_id": pid, "title": title_by_id.get(pid, pid), "via": "alias", "matched": query}
    # substring matches across aliases
    for row in store.all_aliases():
        if q in row["alias"].lower():
            pid = row["page_id"]
            if pid not in hits:
                hits[pid] = {"page_id": pid, "title": title_by_id.get(pid, pid),
                             "via": "alias~", "matched": row["alias"]}
    # substring matches across titles / ids
    for pid, title in title_by_id.items():
        if q in pid.lower() or q in title.lower():
            if pid not in hits:
                hits[pid] = {"page_id": pid, "title": title, "via": "title", "matched": title}
    # exact first, then the rest by title
    ordered = [hits[pid] for pid in exact if pid in hits]
    ordered += sorted((v for pid, v in hits.items() if pid not in exact),
                      key=lambda h: h["title"].lower())
    return ordered
