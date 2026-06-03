"""audit — verify each claim against its cited source (CLAUDE.md §4.4, report-only).

Deterministic, no LLM. For every claim that carries a re-readable provenance span
(`git:<repo>@<sha>:<path>#L<a>-L<b>` or `folder:<slug>:<path>#L<a>-L<b>`), re-read
the cited lines from the actual source and check the claim text is still supported
by them. The source location is resolved from the ingest event log (it records the
absolute path the project was read from).

This is the tool that lets you TRUST what the brain learned before anything relies
on it — the prerequisite for safely connecting the brain to a live app. It reports;
it never auto-fixes. The semantic (LLM-assisted) version comes later; this checks
span existence + text presence, which is enough to catch drift, stale spans, and
broken provenance.

Findings (a claim is flagged, not silently trusted):
    source-root-unknown  — no ingest event records where the project was read from
    source-unreadable    — the file/sha/line-range no longer exists
    claim-not-supported  — the cited lines exist but don't contain the claim text
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .store import Store

# git:<repo>@<sha>:<path>#L<a>-L<b>   |   folder:<slug>:<path>#L<a>-L<b>
_GIT = re.compile(r"^git:([^@]+)@([0-9a-fA-F]+):(.+?)#L(\d+)-L(\d+)$")
_FOLDER = re.compile(r"^folder:([^:]+):(.+?)#L(\d+)(?:-L(\d+))?$")


@dataclass
class AuditFinding:
    claim_id: str
    page_id: str
    source: str
    reason: str
    detail: str


@dataclass
class AuditReport:
    checked: int = 0
    ok: int = 0
    skipped: int = 0
    findings: list[AuditFinding] = field(default_factory=list)

    def summary(self) -> str:
        return (f"audit: {self.ok}/{self.checked} claims verified, "
                f"{len(self.findings)} finding(s), {self.skipped} skipped (no span)")


@dataclass
class _Span:
    channel: str        # "git" | "folder"
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
    return None             # e.g. "folder:slug:." , "git:...:<git-log>", "raw:..."


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _read_git_span(repo: str, sha: str, path: str, a: int, b: int) -> list[str] | None:
    out = subprocess.run(
        ["git", "-C", repo, "show", f"{sha}:{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        return None
    lines = out.stdout.splitlines()
    return lines[a - 1:b] if a <= len(lines) else None


def _read_file_span(root: str, path: str, a: int, b: int) -> list[str] | None:
    fp = Path(root) / path
    if not fp.exists():
        return None
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[a - 1:b] if a <= len(lines) else None


def _supported(claim_text: str, span_lines: list[str], path: str) -> bool:
    src = _norm(" ".join(span_lines))
    txt = _norm(claim_text)
    # Doc claims are stored as "path: text" — strip the path prefix before matching.
    prefix = _norm(path + ":")
    if txt.startswith(prefix):
        txt = txt[len(prefix):].strip()
    return bool(txt) and txt in src


def audit(store: Store) -> AuditReport:
    # Resolve project -> source path from the ingest event log (latest wins).
    source_by_project: dict[str, str] = {}
    for ev in store.events("ingest"):
        detail = json.loads(ev["detail"] or "{}")
        if ev["target"] and detail.get("source"):
            source_by_project[ev["target"]] = detail["source"]
    project_of = {
        r["id"]: r["project"]
        for r in store._conn.execute("SELECT id, project FROM pages").fetchall()
    }

    report = AuditReport()
    for claim in store.all_claims():
        span = _parse_span(claim.source)
        if span is None:
            report.skipped += 1
            continue
        report.checked += 1
        root = source_by_project.get(project_of.get(claim.page_id))
        if not root:
            report.findings.append(AuditFinding(
                claim.id, claim.page_id, claim.source, "source-root-unknown",
                "no ingest event records the source path for this project"))
            continue
        if span.channel == "git":
            lines = _read_git_span(root, span.sha, span.path, span.a, span.b)
        else:
            lines = _read_file_span(root, span.path, span.a, span.b)
        if lines is None:
            report.findings.append(AuditFinding(
                claim.id, claim.page_id, claim.source, "source-unreadable",
                "cited file / sha / line-range not found at the source"))
            continue
        if _supported(claim.text, lines, span.path):
            report.ok += 1
        else:
            report.findings.append(AuditFinding(
                claim.id, claim.page_id, claim.source, "claim-not-supported",
                f"cited lines do not contain the claim text: {claim.text[:80]!r}"))

    store.log_event("audit", target="brain", detail={
        "checked": report.checked, "ok": report.ok, "skipped": report.skipped,
        "findings": [{"claim": f.claim_id, "reason": f.reason} for f in report.findings],
    })
    return report
