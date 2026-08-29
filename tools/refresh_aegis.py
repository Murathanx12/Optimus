"""refresh_aegis — bring the brain current on the Aegis program in one command.

The Optimus audit (2026-07-29) found the corpus 6 weeks stale; the 2026-08-02
session found the deeper gap — the git channel's 3 summary pages never carried
the knowledge-dense text (trial docs, NEGATIVE_RESULTS, session memories).
This script re-runs every Aegis ingest, git + notes channels, deterministically
and idempotently. Run it after any research session, or schedule it.

Usage:  python tools/refresh_aegis.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ingest import ingest_git, ingest_notes          # noqa: E402
from core.store import Store                              # noqa: E402

HOME = Path.home()
SOURCES: list[tuple[str, str, str | None]] = [
    # (channel, source, project-slug override)
    ("git",   str(HOME / "aegis-finance"), None),
    ("git",   str(HOME / "Aegis module"), None),
    ("notes", str(HOME / ".claude/projects/C--Users-mrthn-aegis-finance/memory"),
              "aegis-session-memory"),
    ("notes", str(HOME / "Aegis module/TRIALS"), "aegis-module-trials"),
    ("notes", str(HOME / "Aegis module/docs"), "aegis-module-docs"),
    ("notes", str(HOME / "aegis-finance/docs/research"), "aegis-research-docs"),
    # 2026-08-29: the main docs/ tree (INDEX, VISION, INVARIANTS, every
    # FINDING_/ROADMAP_) was never ingested -- brain_query for "portfolio farm
    # breadth" returned a Next.js README because the farm findings were not
    # in the brain at all. TIER 0/1/2 live here.
    ("notes", str(HOME / "aegis-finance/docs"), "aegis-docs"),
    ("notes", str(HOME / "aegis-alpha-terminal/docs"), "aat-docs"),
    ("notes", str(HOME / "aegis-finance/NEGATIVE_RESULTS.md"), "aegis-neg-results"),
    # REMOVED 2026-08-15 — this line ingested the brain into itself.
    #
    # `ingest_notes` writes each page to `page_dir/{slug}-{stem}.md`, and for
    # this source the page dir IS the source dir. So every run read
    # `aegis-health-latest.md` and wrote `aegis-health-aegis-health-latest.md`,
    # which the next run read and re-prefixed again — 12 characters per session,
    # 35 files accumulated, and finally a filename with the slug repeated
    # NINETEEN times that Windows refused to create. That is what
    # `refresh FINISHED WITH 1 FAILURES` had been reporting.
    #
    # Nothing is lost by removing it: `brain/projects/aegis-health/` is already
    # the brain's own page directory, so `health_snapshot` writing there IS the
    # page being in the corpus. Ingesting it was always a no-op with a
    # side effect.
]


def main() -> int:
    failures = 0
    # regenerate the health page BEFORE ingest so the notes channel picks it up
    from tools.health_snapshot import main as snapshot_main  # noqa: E402
    try:
        snapshot_main()
    except Exception as e:  # noqa: BLE001
        failures += 1
        print(f"[FAIL] health snapshot -> {type(e).__name__}: {e}")
    with Store(str(ROOT)) as store:
        for channel, source, project in SOURCES:
            try:
                fn = ingest_git if channel == "git" else ingest_notes
                result = fn(store, source, project=project)
                print(f"[ok] {channel:5s} {source} -> {result.summary()}")
            except Exception as e:                        # noqa: BLE001
                failures += 1
                print(f"[FAIL] {channel:5s} {source} -> {type(e).__name__}: {e}")
    print(f"\nrefresh {'complete' if not failures else f'FINISHED WITH {failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
