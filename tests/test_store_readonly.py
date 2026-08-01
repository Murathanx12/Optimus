"""Read-only Store mode + graph read methods — the rails behind the view surface.

The web UI (ui/) opens the brain strictly read-only. These tests pin that contract:
mode=ro forbids OS-level writes, every write method raises, log_event no-ops (so
audit() can run against a read-only handle), and the graph readers return the
edges + all-status pages the UI needs.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.audit import audit
from core.schema import Page, Tier
from core.store import Store


def _seed(root) -> Store:
    """A small writable brain: two pages, an edge, a tombstone."""
    store = Store(root)
    overview = Page(
        id="proj-overview", title="Proj Overview", tier=Tier.PROJECTS,
        type="overview", project="proj", aliases=["proj"],
        sources=["folder:proj:README.md#L1-L1"], source_root=str(root),
    )
    structure = Page(
        id="proj-structure", title="Proj Structure", tier=Tier.PROJECTS,
        type="structure", project="proj",
    )
    store.write_page(overview)
    store.write_page(structure)
    store.add_edge("proj-structure", "proj-overview", "part_of")
    store.write_tombstone(
        "buzzer", ["buzzer", "piezo"], "removed in v2", ["proj-overview"], "2026-01-01"
    )
    store.close()
    return Store(root)  # fresh writable handle


def test_readonly_open_forbids_writes(optimus_root):
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    assert ro.read_only is True

    page = Page(id="x", title="X", tier=Tier.PROJECTS, type="overview", project="p")
    with pytest.raises(RuntimeError):
        ro.write_page(page)
    with pytest.raises(RuntimeError):
        ro.add_edge("a", "b", "part_of")
    with pytest.raises(RuntimeError):
        ro.write_tombstone("z", ["z"], "why", [], "2026-01-01")
    with pytest.raises(RuntimeError):
        ro.remove_tombstone("buzzer")
    with pytest.raises(RuntimeError):
        ro.reindex()
    ro.close()


def test_readonly_connection_is_os_level_readonly(optimus_root):
    """Even a raw write through the underlying handle is refused by SQLite itself."""
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        ro._conn.execute("INSERT INTO events (ts, op) VALUES ('t', 'hack')")
    ro.close()


def test_readonly_log_event_is_noop(optimus_root):
    """log_event must silently no-op read-only so audit() can run on the handle."""
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    before = len(ro.events())
    ro.log_event("audit", target="brain", detail={"x": 1})  # must not raise, must not write
    assert len(ro.events()) == before
    ro.close()


def test_audit_runs_against_readonly_store(optimus_root):
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    report = audit(ro)  # calls log_event internally; must not raise
    assert report.verified + report.skipped + report.drifted + report.unverifiable == len(
        ro.all_claims()
    )
    ro.close()


def test_readonly_missing_brain_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Store(tmp_path / "no-such-root", read_only=True)


def test_reads_work_readonly(optimus_root):
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    assert ro.page_count() == 2
    assert {p["id"] for p in ro.all_pages()} == {"proj-overview", "proj-structure"}
    assert ro.resolve_alias("proj") == ["proj-overview"]
    assert len(ro.list_tombstones()) == 1
    ro.close()


def test_all_edges(optimus_root):
    _seed(optimus_root).close()
    ro = Store(optimus_root, read_only=True)
    edges = ro.all_edges()
    assert len(edges) == 1
    e = edges[0]
    assert (e["src_page_id"], e["dst_page_id"], e["rel"]) == (
        "proj-structure", "proj-overview", "part_of"
    )
    ro.close()


def test_all_pages_any_status_includes_deprecated(optimus_root):
    """all_pages() hides non-active; all_pages_any_status() must surface them so the
    graph can render deprecated nodes struck-through rather than dropping them."""
    store = _seed(optimus_root)
    # Deprecate one page directly in markdown + reindex (writable handle).
    page = store.read_page("proj-structure")
    page.status = "deprecated"
    store.write_page(page)
    store.close()

    ro = Store(optimus_root, read_only=True)
    active_ids = {p["id"] for p in ro.all_pages()}
    all_ids = {p["id"] for p in ro.all_pages_any_status()}
    assert "proj-structure" not in active_ids
    assert "proj-structure" in all_ids
    by_id = {p["id"]: p["status"] for p in ro.all_pages_any_status()}
    assert by_id["proj-structure"] == "deprecated"
    ro.close()
