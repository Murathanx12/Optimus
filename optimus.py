#!/usr/bin/env python
"""Optimus CLI.

Session 1 implements one channel:

    python optimus.py ingest --git <url|local-path> [--project <slug>]

Run from the repo root; the brain lives in ./brain (override with --root).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.audit import audit as run_audit
from core.deprecate import deprecate as run_deprecate
from core.ingest import ingest_folder, ingest_git
from core.query import format_answer, retrieve
from core.store import Store


def cmd_ingest(args: argparse.Namespace) -> int:
    if not (args.git or args.folder):
        print("pass --git <repo> or --folder <path>.", file=sys.stderr)
        return 2
    with Store(args.root) as store:
        if args.git:
            result = ingest_git(store, args.git, project=args.project)
        else:
            result = ingest_folder(store, args.folder, project=args.project)
    print(result.summary())
    for pid in result.pages:
        print(f"  page: brain/projects/{result.project}/{pid}.md")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    with Store(args.root) as store:
        result = retrieve(store, args.text, k=args.k)
        print(format_answer(store, result))
    return 0 if result.pages else 1


def cmd_deprecate(args: argparse.Namespace) -> int:
    def _show(refset, diffs) -> None:
        print(refset.preview())
        print("\nStaged diffs (not yet applied):")
        for diff in diffs.values():
            print(diff)
            print()

    def confirm(refset, diffs) -> bool:
        _show(refset, diffs)
        while True:
            ans = input("Apply deprecation? [y/N/review]: ").strip().lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("r", "review"):
                _show(refset, diffs)
                continue
            return False

    with Store(args.root) as store:
        result = run_deprecate(
            store, args.entity, reason=args.reason,
            extra_aliases=tuple(args.alias or ()),
            dry_run=args.dry_run,
            confirm=None if args.yes else confirm,
        )
    if args.dry_run or args.yes or not result.applied:
        print(result.refset.preview())
    print(f"\n{'APPLIED' if result.applied else 'NOT APPLIED'}: {result.note}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    with Store(args.root) as store:
        report = run_audit(store)
    print(report.summary())
    # DRIFTED is loud — these claims are now WRONG.
    for r in report.drift:
        print(f"  DRIFTED  {r.claim_id} ({r.page_id})")
        print(f"      source: {r.source}")
        print(f"      {r.detail}")
    # UNVERIFIABLE-HERE is quiet — not wrong, just uncheckable on this machine.
    unver = [r for r in report.results if r.state == "unverifiable-here"]
    if unver:
        print(f"  ({len(unver)} unverifiable-here — source not reachable; "
              f"last verified as of ingest, see brain front-matter)")
    # Non-zero exit only on real drift (wrong facts), never on unverifiable.
    return 1 if report.drift else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(prog="optimus", description="Optimus memory engine")
    parser.add_argument("--root", default=str(Path(__file__).parent),
                        help="Optimus repo root (default: this directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest a source into the brain")
    p_ingest.add_argument("--git", metavar="SRC", help="git repo: local path or remote URL")
    p_ingest.add_argument("--folder", metavar="PATH", help="local folder (structure + text files)")
    p_ingest.add_argument("--project", metavar="SLUG", help="override project slug")
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = sub.add_parser("query", help="retrieve brain pages for a question (LLM-free)")
    p_query.add_argument("text", help="the question, e.g. \"what is Aegis\"")
    p_query.add_argument("-k", type=int, default=3, help="max pages to return (default 3)")
    p_query.set_defaults(func=cmd_query)

    p_dep = sub.add_parser("deprecate", help="deprecate an entity across every reference")
    p_dep.add_argument("entity", help="entity to deprecate, e.g. \"buzzer\"")
    p_dep.add_argument("--reason", required=True, help="why / when it was removed")
    p_dep.add_argument("--alias", action="append", help="extra alias to match (repeatable)")
    p_dep.add_argument("--yes", action="store_true", help="skip the confirm prompt")
    p_dep.add_argument("--dry-run", action="store_true", help="preview references only, no changes")
    p_dep.set_defaults(func=cmd_deprecate)

    p_audit = sub.add_parser("audit", help="verify every claim against its cited source (report-only)")
    p_audit.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
