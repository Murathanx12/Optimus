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

from core.ingest import ingest_git
from core.store import Store


def cmd_ingest(args: argparse.Namespace) -> int:
    if not args.git:
        print("Session 1 supports only --git <source>.", file=sys.stderr)
        return 2
    with Store(args.root) as store:
        result = ingest_git(store, args.git, project=args.project)
    print(result.summary())
    for pid in result.pages:
        print(f"  page: brain/projects/{result.project}/{pid}.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optimus", description="Optimus memory engine")
    parser.add_argument("--root", default=str(Path(__file__).parent),
                        help="Optimus repo root (default: this directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest a source into the brain")
    p_ingest.add_argument("--git", metavar="SRC", help="git repo: local path or remote URL")
    p_ingest.add_argument("--project", metavar="SLUG", help="override project slug")
    p_ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
