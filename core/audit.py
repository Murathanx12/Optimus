"""audit — verify each claim against its cited source, three states (CLAUDE.md §4.4).

Deterministic, no LLM, report-only. For every claim with a re-readable span
(`git:<repo>@<sha>:<path>#L<a>-L<b>` or `folder:<slug>:<path>#L<a>-L<b>`), audit
re-reads the cited lines and resolves to one of THREE states — the distinction is
load-bearing:

  VERIFIED          — source reachable AND still contains the quote/text.
  DRIFTED           — source reachable BUT no longer contains it. The dangerous
                      case: the claim is now WRONG. Loud.
  UNVERIFIABLE-HERE — source not reachable from this machine (moved brain, missing
                      repo). NOT wrong, just uncheckable. Quiet/informational; the
                      stored quote + as-of date are reported as last-known-good.

Conflating DRIFTED with UNVERIFIABLE was the bug: it made a healthy *portable*
brain look 100% broken while hiding the one state that means "wrong."

Verifiability travels with the brain: the source ROOT is read from the page's
front-matter (`source_root`, durable — survives index.db deletion), not from the
ephemeral events table; the verbatim quote captured at ingest is the portable
last-known-good snapshot, reported with the page's ingest date as "as of".
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .store import Store

STATE_VERIFIED = "verified"
STATE_DRIFTED = "drifted"
STATE_UNVERIFIABLE = "unverifiable-here"
STATE_SKIPPED = "skipped"

# git:<repo>@<sha>:<path>#L<a>-L<b>   |   folder:<slug>:<path>#L<a>-L<b>
_GIT = re.compile(r"^git:([^@]+)@([0-9a-fA-F]+):(.+?)#L(\d+)-L(\d+)$")
_FOLDER = re.compile(r"^folder:([^:]+):(.+?)#L(\d+)(?:-L(\d+))?$")


@dataclass
class ClaimAudit:
    claim_id: str
    page_id: str
    source: str
    state: str
    detail: str = ""
    as_of: str | None = None
    quote: str | None = None


@dataclass
class AuditReport:
    results: list[ClaimAudit] = field(default_factory=list)

    def _count(self, state: str) -> int:
        return sum(1 for r in self.results if r.state == state)

    @property
    def verified(self) -> int: return self._count(STATE_VERIFIED)
    @property
    def drifted(self) -> int: return self._count(STATE_DRIFTED)
    @property
    def unverifiable(self) -> int: return self._count(STATE_UNVERIFIABLE)
    @property
    def skipped(self) -> int: return self._count(STATE_SKIPPED)

    @property
    def drift(self) -> list[ClaimAudit]:
        """The loud findings — claims whose source no longer supports them."""
        return [r for r in self.results if r.state == STATE_DRIFTED]

    def summary(self) -> str:
        return (f"audit: {self.verified} verified · {self.drifted} DRIFTED · "
                f"{self.unverifiable} unverifiable-here · {self.skipped} skipped")


@dataclass
class _Span:
    channel: str
    sha: str | None
    path: str
    a: int
    b: int


def _parse_span(source: str) -> _Span | None:
    m = _GIT.match(source)
    if m:
        return _Span("git", m.group(2), m.group(3), int(m.group(4)), int(m.group(5)))
    m = _FOLDER.match(source)
    if m:
        a = int(m.group(3))
        b = int(m.group(4)) if m.group(4) else a
        return _Span("folder", None, m.group(2), a, b)
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _read_span(span: _Span, root: str | None, a: int, b: int) -> tuple[bool, list[str] | None]:
    """Return (reachable, lines). reachable=False means UNVERIFIABLE-HERE (root or
    cited file/version not retrievable from this machine). reachable=True with lines
    (possibly empty) means we read the cited location and can judge VERIFIED/DRIFTED."""
    if not root or not Path(root).exists():
        return (False, None)
    if span.channel == "git":
        out = subprocess.run(
            ["git", "-C", root, "show", f"{span.sha}:{span.path}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if out.returncode != 0:                      # sha/file not in this repo → unreachable
            return (False, None)
        lines = out.stdout.splitlines()
        return (True, lines[a - 1:b])
    # folder
    fp = Path(root) / span.path
    if not fp.exists():                              # file gone → unreachable (not "wrong")
        return (False, None)
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    return (True, lines[a - 1:b])


def _supported(target: str, span_lines: list[str], path: str) -> bool:
    src = _norm(" ".join(span_lines))
    txt = _norm(target)
    prefix = _norm(path + ":")                       # doc claims are "path: text"
    if txt.startswith(prefix):
        txt = txt[len(prefix):].strip()
    return bool(txt) and txt in src


def audit(store: Store) -> AuditReport:
    pages = {
        r["id"]: r
        for r in store._conn.execute("SELECT id, source_root, created FROM pages").fetchall()
    }
    report = AuditReport()
    for claim in store.all_claims():
        span = _parse_span(claim.source)
        if span is None:
            report.results.append(ClaimAudit(
                claim.id, claim.page_id, claim.source, STATE_SKIPPED, "no re-readable span"))
            continue
        page = pages.get(claim.page_id)
        root = page["source_root"] if page else None
        as_of = page["created"] if page else None
        # Decisions are verified by their verbatim QUOTE (rationale is for human
        # grading); widen the window so a multi-line quote at the cited line still reads.
        target = claim.quote if (claim.kind == "decision" and claim.quote) else claim.text
        a, b = span.a, span.b
        if claim.kind == "decision":
            b = max(b, a + 4)

        reachable, lines = _read_span(span, root, a, b)
        if not reachable:
            report.results.append(ClaimAudit(
                claim.id, claim.page_id, claim.source, STATE_UNVERIFIABLE,
                "source not reachable from this machine; last-known-good quote shown",
                as_of=as_of, quote=target))
        elif _supported(target, lines, span.path):
            report.results.append(ClaimAudit(
                claim.id, claim.page_id, claim.source, STATE_VERIFIED, as_of=as_of))
        else:
            what = "quote" if claim.kind == "decision" else "claim text"
            report.results.append(ClaimAudit(
                claim.id, claim.page_id, claim.source, STATE_DRIFTED,
                f"source reachable but no longer contains the {what}: {target[:80]!r}",
                as_of=as_of, quote=target))

    store.log_event("audit", target="brain", detail={
        "verified": report.verified, "drifted": report.drifted,
        "unverifiable": report.unverifiable, "skipped": report.skipped,
    })
    return report
