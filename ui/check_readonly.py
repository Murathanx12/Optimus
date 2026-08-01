"""Quick guard check, run FROM the real brain:

  1. The viewer opens the brain read-only — every write method raises and even a
     raw INSERT through the handle is refused by SQLite (mode=ro).
  2. Building the graph + every page detail mutates nothing (event count unchanged
     via a separate writable handle before/after).
  3. Drift renders red — demonstrated on a *throwaway copy* of the brain with one
     decision-claim's quote corrupted, so the real brain is never touched.

Usage:  python -m ui.check_readonly [--root .]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import tempfile
from pathlib import Path

from core.audit import audit
from core.schema import Page
from core.store import Store
from ui import model


def check_real_brain(root: str) -> None:
    print(f"[1] opening real brain read-only: {Path(root).resolve()}")
    ro = Store(root, read_only=True)
    assert ro.read_only is True

    # event count, observed through an independent read-only count, must not change.
    def event_count() -> int:
        return len(Store(root, read_only=True).events())

    before = event_count()

    failures = []
    page = Page(id="__probe__", title="x", tier=2, type="overview", project="p")
    for name, fn in [
        ("write_page", lambda: ro.write_page(page)),
        ("add_edge", lambda: ro.add_edge("a", "b", "part_of")),
        ("write_tombstone", lambda: ro.write_tombstone("z", ["z"], "r", [], "2026-01-01")),
        ("reindex", lambda: ro.reindex()),
    ]:
        try:
            fn(); failures.append(f"{name} did NOT raise")
        except RuntimeError:
            pass
    try:
        ro._conn.execute("INSERT INTO events (ts, op) VALUES ('t', 'hack')")
        failures.append("raw INSERT did NOT raise")
    except sqlite3.OperationalError:
        pass
    assert not failures, failures
    print("    [ok] all write paths refused (4 methods raise RuntimeError, raw INSERT blocked by mode=ro)")

    # full read path used by the server — must not write.
    report = audit(ro)
    graph = model.build_graph(ro, report)
    for n in graph["nodes"]:
        model.page_detail(ro, report, n["id"])
    model.tombstones(ro)
    after = event_count()
    assert after == before, f"event log changed: {before} -> {after}"
    print(f"    [ok] graph + {len(graph['nodes'])} page details + tombstones built; "
          f"event log unchanged ({before} rows)")
    print(f"    audit: {report.summary()}")
    drift_nodes = [n["id"] for n in graph["nodes"] if n["audit_state"] == "drifted"]
    print(f"    drifted nodes in real brain: {drift_nodes or 'none (brain is healthy)'}")
    ro.close()


def check_drift_renders_red(root: str) -> None:
    print("[2] demonstrating drift->red on a throwaway copy (real brain untouched)")
    src_brain = Path(root) / "brain"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp) / "opt"
        shutil.copytree(src_brain, tmp_root / "brain")
        # corrupt one decision-claim's quote so its source no longer supports it.
        w = Store(tmp_root)
        target = None
        for c in w.all_claims():
            if c.kind == "decision":
                target = c.page_id
                break
        assert target, "no decision claim found to corrupt"
        page = w.read_page(target)
        victim = next(c for c in page.claims if c.kind == "decision")
        victim.quote = "ZZZ_DEFINITELY_NOT_IN_SOURCE_ZZZ"
        w.write_page(page)            # writes only into the TEMP copy
        w.close()

        ro = Store(tmp_root, read_only=True)
        report = audit(ro)
        graph = model.build_graph(ro, report)
        node = next(n for n in graph["nodes"] if n["id"] == target)
        print(f"    corrupted claim {victim.id!r} on page {target!r}")
        print(f"    -> page audit_state: {node['audit_state']}  (frontend fill = #f85149 red)")
        assert node["audit_state"] == "drifted", node
        assert report.drifted >= 1
        # confirm the detail panel exposes the loud DRIFTED claim
        detail = model.page_detail(ro, report, target)
        drifted = [c for c in detail["claims"] if c["audit"]["state"] == "drifted"]
        print(f"    -> {len(drifted)} drifted claim(s) surfaced in detail panel, "
              f"e.g. {drifted[0]['id']}")
        ro.close()
    print(f"    [ok] real brain at {src_brain} never modified (temp copy discarded)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    check_real_brain(args.root)
    check_drift_renders_red(args.root)
    print("\nALL READ-ONLY GUARANTEES HOLD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
