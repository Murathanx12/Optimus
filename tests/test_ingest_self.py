"""The brain's output is never its input (core/ingest.py, 2026-08-29).

Measured failure: `refresh_aegis` once listed `brain/projects/aegis-health/` as
a notes SOURCE. Each pass read `aegis-health-latest.md` and wrote
`aegis-health-aegis-health-latest.md` beside it, eighteen deep, leaving 33 of
428 index rows pointing at files that never existed and `brain_query` raising
FileNotFoundError whenever one ranked. Two invariants pin the fix:

1. re-ingesting a page whose stem already carries the project prefix keeps the
   SAME id (idempotent prefixing);
2. a file under the brain's own page tree is skipped, whatever its name.
"""

from __future__ import annotations

from core.ingest import _note_page_id, ingest_notes
from core.store import Store


def test_note_page_id_never_double_prefixes():
    assert _note_page_id("aegis-health", "latest") == "aegis-health-latest"
    assert _note_page_id("aegis-health", "aegis-health-latest") == "aegis-health-latest"
    assert _note_page_id("aegis-health", "aegis-health") == "aegis-health"
    # the prefix is matched on a segment boundary: a stem that merely shares
    # leading characters is still prefixed
    assert _note_page_id("aegis-health", "aegis-healthy") == "aegis-health-aegis-healthy"


def test_reingest_twice_keeps_id_stable(tmp_path, optimus_root):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "aegis-health-latest.md").write_text(
        "# Health\n\nsnapshot body\n", encoding="utf-8")
    (notes / "plain.md").write_text("# Plain\n\nordinary note\n", encoding="utf-8")
    with Store(optimus_root) as store:
        first = ingest_notes(store, str(notes), project="aegis-health")
        second = ingest_notes(store, str(notes), project="aegis-health")
        assert sorted(first.pages) == sorted(second.pages)
        assert "aegis-health-latest" in first.pages
        assert "aegis-health-plain" in first.pages
        assert "aegis-health-aegis-health-latest" not in first.pages
        ids = {r["id"] for r in store.all_pages()}
        assert not any(i.startswith("aegis-health-aegis-health-") for i in ids)
        # every indexed row resolves to a file that exists
        for r in store.all_pages():
            assert (store.root / r["path"]).exists(), r["id"]


def test_brain_output_dir_is_skipped_as_input(optimus_root):
    with Store(optimus_root) as store:
        out_dir = store.brain / "projects" / "aegis-health"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "aegis-health-latest.md").write_text(
            "# Health\n\nwritten by the brain itself\n", encoding="utf-8")
        before = {r["id"] for r in store.all_pages()}
        result = ingest_notes(store, str(out_dir), project="aegis-health")
        # only the index hub is produced; the output page is not re-ingested
        assert result.pages == ["aegis-health-overview"]
        assert result.file_count == 1
        after = {r["id"] for r in store.all_pages()}
        assert after - before <= {"aegis-health-overview"}
        assert not any("aegis-health-aegis-health" in i for i in after)
        for r in store.all_pages():
            assert (store.root / r["path"]).exists(), r["id"]
