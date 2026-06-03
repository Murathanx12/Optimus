#!/usr/bin/env python
"""Minimal off-machine backup for the private brain (CLAUDE.md §4.1).

The brain is gitignored — it deliberately does NOT travel with the engine repo.
That means it has no backup by default: if this laptop dies, the brain is gone.
This is the cheap mitigation (the real sync story is Phase 2): snapshot brain/
to a second location as a timestamped zip.

    python tools/backup_brain.py --dest "D:/backups"
    python tools/backup_brain.py            # uses $OPTIMUS_BACKUP_DIR

Markdown is source of truth, so the derived index (index.db / -wal / -shm) is
skipped — restore by unzipping and running `Store.reindex()`.

Point --dest at something already off-machine AND encrypted (an encrypted drive,
OneDrive/Drive folder, or a separate PRIVATE git repo). The brain holds the
identity tier; do not back it up somewhere public.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

_SKIP = {"index.db", "index.db-wal", "index.db-shm"}


def backup(root: Path, dest: Path) -> Path:
    brain = root / "brain"
    if not brain.exists():
        raise SystemExit(f"no brain to back up at {brain}")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = dest / f"optimus-brain-{stamp}.zip"

    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(brain.rglob("*")):
            if path.is_dir() or path.name in _SKIP:
                continue
            zf.write(path, path.relative_to(root).as_posix())
            count += 1
    print(f"backed up {count} file(s) → {archive}")
    return archive


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Snapshot the private brain off-machine")
    p.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                   help="Optimus repo root (default: this repo)")
    p.add_argument("--dest", default=os.environ.get("OPTIMUS_BACKUP_DIR"),
                   help="backup destination dir (or set $OPTIMUS_BACKUP_DIR)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    args = p.parse_args(argv)
    if not args.dest:
        print("error: pass --dest or set $OPTIMUS_BACKUP_DIR", file=sys.stderr)
        return 2
    backup(Path(args.root), Path(args.dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
