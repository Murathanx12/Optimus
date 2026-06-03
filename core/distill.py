"""distill — turn decision-doc prose into decision-claims (CLAUDE.md §4.4).

The first non-deterministic component. Triggered by the Aegis checkpoint finding:
git-ingest learns a project's *shape* (README bullets) but none of its *decisions*
(SQLite-over-Postgres, crash-overlay-defensive-only, …), which live in docs/*.md
prose. distill reads that prose and extracts decision-claims that carry a rationale
and a verbatim source quote.

Two cost modes (default = expensive, because shallow knowledge is the dangerous
failure mode — the default must actually learn):
  - expensive: LLM (via the core.llm seam) extracts {decision, rationale, quote,
    line}; claims are tagged kind="decision".
  - cheap: NO LLM. Each doc section header becomes a raw claim tagged kind="raw",
    explicitly UN-DISTILLED so it can never masquerade as an understood decision.
    Re-run expensive later to upgrade a cheap page in place.

Determinism guarantee: the extraction logic (prompt build + response parse + claim
construction + provenance) is deterministic and fixture-tested; only the model call
itself is non-deterministic, and it's quarantined behind the seam.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from .llm import Completer
from .schema import Claim, Page, Tier
from .store import Store

DECISION_SYSTEM = (
    "You extract architectural and design DECISIONS from a software project's "
    "documentation. You never invent: every decision must be stated in the document, "
    "and every quote must be copied character-for-character from it so it can be "
    "verified against the source."
)


def _build_prompt(text: str) -> str:
    numbered = "\n".join(f"{i}\t{ln}" for i, ln in enumerate(text.splitlines(), 1))
    return (
        "From the document below, extract the concrete DECISIONS it records "
        "(architecture, technology, methodology, scope, trade-offs).\n\n"
        "Return ONLY a JSON array. Each element:\n"
        '  {"decision": "<short statement of what was decided>",\n'
        '   "rationale": "<why it was decided, per the document>",\n'
        '   "quote": "<a sentence copied VERBATIM from the document stating this>",\n'
        '   "line": <line number where the quote begins>}\n\n'
        "Rules: copy the quote exactly (character-for-character). Only include "
        "decisions actually present. No prose outside the JSON array.\n\n"
        "DOCUMENT (line\\ttext):\n" + numbered
    )


def _parse_response(resp: str) -> list[dict]:
    """Robustly pull the JSON array out of a model response (tolerate code fences)."""
    s = resp.strip()
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("decision")]


_HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def _sections(text: str) -> list[tuple[str, int]]:
    out = []
    for i, ln in enumerate(text.splitlines(), 1):
        m = _HEADING.match(ln.strip())
        if m and m.group(1).strip():
            out.append((m.group(1).strip(), i))
    return out


@dataclass
class DistillResult:
    project: str
    mode: str
    page_id: str
    claim_count: int
    kinds: dict = field(default_factory=dict)

    def summary(self) -> str:
        kinds = ", ".join(f"{k}={v}" for k, v in sorted(self.kinds.items()))
        return f"distill[{self.mode}] project={self.project} claims={self.claim_count} ({kinds})"


def _claim(project: str, n: int, kind: str, *, text: str, source: str,
           rationale: str | None = None, quote: str | None = None) -> Claim:
    prefix = "dec" if kind == "decision" else "raw"
    return Claim(id=f"{project}-{prefix}-{n:03d}", page_id=f"{project}-decisions",
                 text=text, source=source, tier=int(Tier.PROJECTS), kind=kind,
                 rationale=rationale, quote=quote)


def _render_body(name: str, claims: list[Claim], mode: str) -> str:
    note = ("Distilled decision-claims (LLM-extracted, with rationale + source quote)."
            if mode == "expensive" else
            "RAW, un-distilled doc sections — not yet digested into decisions. "
            "Re-run expensive distill to upgrade.")
    lines = [f"# {name} — Decisions", "", f"> {note}", ""]
    for c in claims:
        if c.kind == "decision":
            lines += [f"## {c.text}", "",
                      f"- **Why:** {c.rationale or '(none extracted)'}",
                      f"- **Source:** `{c.source}`",
                      f"- **Quote:** “{c.quote or ''}”", ""]
        else:
            lines.append(f"- [raw] {c.text}  `{c.source}`")
    return "\n".join(lines)


def distill_docs(
    store: Store, *, project: str, docs: list[tuple[str, str]],
    completer: Completer | None = None, mode: str = "expensive",
    display_name: str | None = None,
) -> DistillResult:
    """Distill decision-claims from `docs` = [(source_prefix, text), ...] into a
    `<project>-decisions` page. source_prefix is the provenance grammar minus the
    line span, e.g. ``git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md``."""
    if mode not in ("expensive", "cheap"):
        raise ValueError(f"unknown mode: {mode}")
    if mode == "expensive" and completer is None:
        raise ValueError("expensive distill requires a completer (the LLM seam)")

    claims: list[Claim] = []
    for prefix, text in docs:
        if mode == "expensive":
            for d in _parse_response(completer.complete(_build_prompt(text), system=DECISION_SYSTEM)):
                line = d.get("line")
                src = f"{prefix}#L{line}-L{line}" if isinstance(line, int) else prefix
                claims.append(_claim(project, len(claims), "decision",
                                     text=str(d["decision"]).strip(), source=src,
                                     rationale=(d.get("rationale") or None),
                                     quote=(d.get("quote") or None)))
        else:  # cheap — raw, un-distilled section headers
            for heading, line in _sections(text):
                claims.append(_claim(project, len(claims), "raw",
                                     text=heading, source=f"{prefix}#L{line}-L{line}"))

    name = display_name or project
    page = Page(
        id=f"{project}-decisions", title=f"{name} — Decisions", tier=int(Tier.PROJECTS),
        type="decisions", project=project, aliases=[f"{project} decisions"],
        tags=["project", "decisions", mode], sources=[p for p, _ in docs],
        body=_render_body(name, claims, mode), claims=claims,
    )
    store.write_page(page)
    kinds = dict(Counter(c.kind for c in claims))
    store.log_event("distill", target=project, detail={
        "mode": mode, "docs": len(docs), "claims": len(claims), "kinds": kinds,
    })
    return DistillResult(project, mode, page.id, len(claims), kinds)
