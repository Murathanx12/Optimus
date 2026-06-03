"""deprecate — propagate fact removal across every reference (CLAUDE.md §4.5).

The "buzzer fix": a component is removed, but stale mentions persist across many
pages and keep resurfacing. deprecate kills that class of bug:

  1. Resolve an entity through the alias graph → canonical + all aliases.
  2. Find every referencing page (body lines) and every claim mentioning an alias.
     Produces a dry-run preview before anything changes.
  3. Stage a strike-through diff per matching line (+ a why/when note). Staged,
     not applied — a human confirms (y / N / review).
  4. On confirm, atomically: strike the lines in markdown, mark matching claims
     deprecated (weight → 0), deprecate any page that *is* the entity, and write
     a tombstone (markdown + index). Roll back everything if any write fails.

Blocking silent re-ingestion (step 4 of the brief) and the hypothesis property
test (step 5) are the next session — the tombstone storage written here is their
foundation. Reuses query's alias resolution + the page/claim index; no new
retrieval machinery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .schema import STATUS_ACTIVE, STATUS_DEPRECATED, Page, utcnow_iso
from .store import Store


@dataclass
class PageRef:
    page_id: str
    matched_lines: list[tuple[int, str]]   # (1-based line no, line text)
    is_entity_page: bool                   # the page's own entity IS the deprecated thing


@dataclass
class ReferenceSet:
    entity: str
    aliases: list[str]
    page_refs: list[PageRef] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.page_refs)

    @property
    def line_count(self) -> int:
        return sum(len(p.matched_lines) for p in self.page_refs)

    @property
    def is_empty(self) -> bool:
        return not self.page_refs and not self.claim_ids

    def preview(self) -> str:
        head = (f'Found {self.line_count} reference(s) + {len(self.claim_ids)} claim(s) '
                f'across {self.page_count} page(s) for "{self.entity}" '
                f'(aliases: {", ".join(self.aliases)})')
        lines = [head]
        for pr in self.page_refs:
            tag = "  [ENTITY PAGE]" if pr.is_entity_page else ""
            lines.append(f"  {pr.page_id}{tag}")
            for ln, text in pr.matched_lines:
                lines.append(f"    L{ln}: {text.strip()}")
        return "\n".join(lines)


@dataclass
class DeprecateResult:
    refset: ReferenceSet
    applied: bool
    note: str = ""


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def alias_pattern(aliases: list[str]) -> re.Pattern:
    # Longest-first so multi-word aliases win; whole-token match to avoid substrings.
    parts = sorted({re.escape(a.strip()) for a in aliases if a.strip()}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def _strike(line: str, note: str) -> str:
    """Strike a markdown line's content, preserving any leading list marker, + a note."""
    m = re.match(r"^(\s*(?:[-*]\s+|>\s*)?)(.*)$", line)
    marker, content = m.group(1), m.group(2)
    return f"{marker}~~{content}~~ _{note}_"


def find_references(store: Store, entity: str, extra_aliases: tuple[str, ...] = ()) -> ReferenceSet:
    """Resolve `entity` to its alias set and locate every reference (read-only)."""
    entity_pages = set(store.resolve_alias(entity))
    aliases: set[str] = {entity, *extra_aliases}
    # Pull in aliases of any page the entity directly names (alias-graph closure).
    for row in store.all_aliases():
        if row["page_id"] in entity_pages:
            aliases.add(row["alias"])
    pattern = alias_pattern(sorted(aliases))

    # Claims whose text mentions an alias (and the pages that hold them).
    claim_matches = [
        (c.id, c.page_id) for c in store.all_claims(status=STATUS_ACTIVE)
        if pattern.search(c.text)
    ]
    claim_ids = [cid for cid, _ in claim_matches]
    claim_pages = {pid for _, pid in claim_matches}

    page_refs: list[PageRef] = []
    for prow in store.all_pages():                      # active pages only
        page = store.read_page(prow["id"])
        if page is None:
            continue
        matched = [
            (i, ln) for i, ln in enumerate(page.body.splitlines(), start=1)
            if pattern.search(ln)
        ]
        is_entity = prow["id"] in entity_pages
        # Include a page if its body mentions the entity, it IS the entity, or it
        # holds a matching claim (so a claim with no body line still gets deprecated).
        if matched or is_entity or prow["id"] in claim_pages:
            page_refs.append(PageRef(prow["id"], matched, is_entity))

    return ReferenceSet(entity=entity, aliases=sorted(aliases),
                        page_refs=page_refs, claim_ids=claim_ids)


def stage_diffs(store: Store, refset: ReferenceSet, reason: str, date: str) -> dict[str, str]:
    """Return {page_id: unified-ish diff text} for the strike-throughs (not applied)."""
    note = f"(deprecated {date}: {reason})"
    diffs: dict[str, str] = {}
    for pr in refset.page_refs:
        if not pr.matched_lines:
            continue
        out = [f"--- {pr.page_id}"]
        for ln, text in pr.matched_lines:
            out.append(f"- L{ln}: {text.strip()}")
            out.append(f"+ L{ln}: {_strike(text, note).strip()}")
        diffs[pr.page_id] = "\n".join(out)
    return diffs


def _apply(store: Store, refset: ReferenceSet, reason: str, date: str) -> None:
    """Atomic apply: strike body lines, deprecate matching claims + entity pages,
    write a tombstone. Claim status is edited on the page and persisted via
    write_page, so it lands in markdown. Snapshots each page's markdown and
    restores it if any step raises (claims ride with the page — no special-casing)."""
    note = f"(deprecated {date}: {reason})"
    claim_ids = set(refset.claim_ids)
    md_snapshots: dict[str, str] = {}

    try:
        for pr in refset.page_refs:
            page = store.read_page(pr.page_id)
            md_snapshots[pr.page_id] = page.to_markdown()

            matched_nos = {ln for ln, _ in pr.matched_lines}
            page.body = "\n".join(
                _strike(line, note) if (i in matched_nos and line.strip() and "~~" not in line)
                else line
                for i, line in enumerate(page.body.splitlines(), start=1)
            )
            for c in page.claims:                       # deprecate matching claims in front-matter
                if c.id in claim_ids:
                    c.status = STATUS_DEPRECATED
            page.updated = utcnow_iso()
            if pr.is_entity_page:
                page.status = STATUS_DEPRECATED
            store.write_page(page)                      # md + index, claims included

        store.write_tombstone(
            entity=refset.entity, aliases=refset.aliases, reason=reason,
            pages=[pr.page_id for pr in refset.page_refs], created=date,
        )
        store.log_event("deprecate", target=refset.entity, detail={
            "reason": reason, "pages": [pr.page_id for pr in refset.page_refs],
            "claims": refset.claim_ids, "lines": refset.line_count,
        })
    except Exception:
        # Roll back: restore each page's markdown via write_page. Claims and their
        # status are inside that markdown now, so this restores them too.
        for pid, md in md_snapshots.items():
            store.write_page(Page.from_markdown(md))
        store.remove_tombstone(refset.entity)
        raise


def deprecate(
    store: Store, entity: str, reason: str, *,
    extra_aliases: tuple[str, ...] = (), date: str | None = None,
    confirm=None, dry_run: bool = False,
) -> DeprecateResult:
    """Resolve → find → (preview) → confirm → atomic apply.

    `confirm(refset, diffs) -> bool` gates the write; if None, applies directly
    (used by tests). The CLI supplies an interactive y/N/review confirm.
    """
    date = date or _today()
    refset = find_references(store, entity, extra_aliases)
    if refset.is_empty:
        return DeprecateResult(refset, applied=False, note="no references found")
    if dry_run:
        return DeprecateResult(refset, applied=False, note="dry-run")

    diffs = stage_diffs(store, refset, reason, date)
    if confirm is not None and not confirm(refset, diffs):
        return DeprecateResult(refset, applied=False, note="declined")

    _apply(store, refset, reason, date)
    return DeprecateResult(refset, applied=True, note="applied")
