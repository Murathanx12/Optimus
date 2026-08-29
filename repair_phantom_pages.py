"""Remove index rows whose FILE DOES NOT EXIST, and say what was removed.

    python repair_phantom_pages.py           # dry run, prints what it would do
    python repair_phantom_pages.py --apply   # backs up index.db, then deletes

WHY (measured 2026-08-29)
=========================
`brain_query` crashed on any query that ranked one of 33 rows in the
`aegis-health` project:

    No such file or directory:
    brain/projects/aegis-health/aegis-health-aegis-health-... (x18) ...-latest.md

The ingest had re-ingested its OWN OUTPUT, prefixing the project slug each
pass, so `aegis-health-latest` spawned `aegis-health-aegis-health-latest` and
so on eighteen deep. The DB got a row every time; the file was only ever
written once. 33 of 428 pages (7.7%) therefore point at nothing.

The cost was not the 33 pages. It was that a CRASHING retrieval tool reads,
from the outside, exactly like a brain that does not contain the answer. On
2026-08-29 a session spent an hour rediscovering `TRIAL-LLM-AMNESIA-1` by
grepping the filesystem, while a page titled "Can you tell an LLM to forget? --
measured, 2026-08-08" sat in the index the whole time, pre-registered, with six
declared predictions and their outcomes.

`brain/projects/_quarantine_self_ingest_20260815/` shows this class of bug was
caught once before, on 15 Aug. It came back. So this script is written to be
re-runnable rather than as a one-off fix.

SAFETY
======
- dry run by default;
- copies `index.db` to `index.db.bak-<stamp>` before touching it;
- deletes ONLY rows whose `path` resolves to a file that does not exist -- a
  page whose file is present is never removed, whatever its name looks like;
- prints every id removed, so the deletion is auditable.

It does NOT fix the ingest. That is the real repair and it belongs in
`core/ingest.py`: a page whose id already starts with `{project}-` must not be
re-prefixed. Until that lands, this script cleans up after it.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "brain" / "index.db"


def phantoms(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    out = []
    for pid, project, path in conn.execute("select id, project, path from pages"):
        if not path or not (ROOT / path).exists():
            out.append((pid, project or "?", path or "<no path>"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    if not DB.exists():
        print(f"no index at {DB}")
        return 1

    conn = sqlite3.connect(DB)
    total = conn.execute("select count(*) from pages").fetchone()[0]
    bad = phantoms(conn)
    if not bad:
        print(f"{total} pages indexed, 0 phantom rows. Nothing to do.")
        return 0

    print(f"{total} pages indexed, {len(bad)} point at a file that does not exist "
          f"({100 * len(bad) / total:.1f}%)")
    for proj, n in Counter(b[1] for b in bad).most_common():
        print(f"  {proj:<28}{n:>4}")
    print("\nsample:")
    for pid, proj, path in bad[:5]:
        print(f"  {pid[:70]}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to delete these rows "
              "(index.db is backed up first).")
        return 0

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = DB.with_suffix(f".db.bak-{stamp}")
    shutil.copy2(DB, backup)
    print(f"\nbacked up index -> {backup.name}")

    ids = [b[0] for b in bad]
    conn.executemany("delete from pages where id = ?", [(i,) for i in ids])
    # Orphaned aliases/edges would keep pointing at the removed ids.
    for table, col in (("aliases", "page_id"), ("edges", "src"), ("edges", "dst")):
        try:
            conn.executemany(f"delete from {table} where {col} = ?", [(i,) for i in ids])
        except sqlite3.OperationalError:
            pass                       # schema differs; the pages row is the one that matters
    conn.commit()
    left = conn.execute("select count(*) from pages").fetchone()[0]
    print(f"removed {len(ids)} phantom rows; {left} pages remain")
    print("Re-run brain_query to confirm it no longer raises FileNotFoundError.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
