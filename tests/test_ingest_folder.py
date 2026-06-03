"""Tests for the folder-ingest channel (Tier A structure/tools + Tier B text)."""

from __future__ import annotations

from core.deprecate import deprecate
from core.ingest import ingest_folder
from core.query import retrieve
from core.schema import STATUS_ACTIVE, STATUS_FLAGGED
from core.store import Store


def _folder_with(tmp_path, name, *capabilities):
    """Folder with a README whose 'What It Does' bullets become per-bullet claims."""
    d = tmp_path / name
    d.mkdir()
    caps = "\n".join(f"- {c}" for c in capabilities)
    (d / "README.md").write_text(
        f"# {name}\n\n> generated source\n\n## What It Does\n\n{caps}\n", encoding="utf-8")
    return d


def test_detects_tools_from_extensions(synthetic_folder, optimus_root):
    """The 'what is he using' signal — from extensions, not file contents."""
    with Store(optimus_root) as store:
        result = ingest_folder(store, str(synthetic_folder))
        overview = store.read_page(f"{result.project}-overview")
        assert "Blender" in overview.body       # .blend
        assert "Fusion 360" in overview.body    # .f3d
        assert "Python" in overview.body        # .py


def test_ignores_junk_dirs_and_never_ingests_secrets(synthetic_folder, optimus_root):
    with Store(optimus_root) as store:
        ingest_folder(store, str(synthetic_folder))
        structure = store.read_page("my-art-structure")
        # node_modules skipped; .env dotfile never read; secret never present anywhere.
        assert "node_modules" not in structure.body
        for pid in ("my-art-overview", "my-art-structure"):
            assert "do-not-ingest" not in store.read_page(pid).body
        for c in store.claims_for("my-art-overview"):
            assert "do-not-ingest" not in c.text


def test_reads_docs_but_not_binaries(synthetic_folder, optimus_root):
    with Store(optimus_root) as store:
        ingest_folder(store, str(synthetic_folder))
        overview = store.read_page("my-art-overview")
        assert "3D experiments" in overview.body          # README description read
        claim_text = " ".join(c.text for c in store.claims_for("my-art-overview"))
        assert "hard-surface modeling" in claim_text      # notes.txt read
        # No binary noise leaked from .blend/.png into pages or claims.
        assert "BLENDER" not in overview.body and "PNG" not in overview.body


def test_claims_have_folder_provenance(synthetic_folder, optimus_root):
    with Store(optimus_root) as store:
        result = ingest_folder(store, str(synthetic_folder))
        claims = store.claims_for(f"{result.project}-overview")
        assert claims
        assert all(c.source.startswith("folder:my-art:") for c in claims)


def test_two_pages_and_edge(synthetic_folder, optimus_root):
    with Store(optimus_root) as store:
        result = ingest_folder(store, str(synthetic_folder))
        assert set(result.pages) == {"my-art-overview", "my-art-structure"}
        edges = store._conn.execute(
            "SELECT src_page_id, dst_page_id, rel FROM edges"
        ).fetchall()
        assert ("my-art-structure", "my-art-overview", "part_of") in {
            (r["src_page_id"], r["dst_page_id"], r["rel"]) for r in edges
        }


def test_folder_pages_are_queryable(synthetic_folder, optimus_root):
    with Store(optimus_root) as store:
        ingest_folder(store, str(synthetic_folder))
        assert retrieve(store, "my-art").top.page_id == "my-art-overview"


def test_folder_channel_respects_tombstones(tmp_path, optimus_root):
    """The hole check: a tombstoned entity must NOT silently revive via the folder
    channel — it routes through the same _flag_tombstoned guard as git."""
    with Store(optimus_root) as store:
        ingest_folder(store, str(_folder_with(tmp_path, "src-a", "The buzzer alerts on crash.")),
                      project="src-a")
        assert any("buzzer" in c.text.lower() for c in store.all_claims(status=STATUS_ACTIVE))

        deprecate(store, "buzzer", reason="removed from hardware", date="2026-06-03", confirm=None)

        # A new folder source repeating the stale fact must come back flagged.
        result = ingest_folder(
            store, str(_folder_with(tmp_path, "src-b", "The buzzer still beeps here.")),
            project="src-b")
        assert result.flagged_claims, "folder channel must flag tombstoned mentions"
        assert not any("buzzer" in c.text.lower() for c in store.all_claims(status=STATUS_ACTIVE))
        assert any("buzzer" in c.text.lower() for c in store.all_claims(status=STATUS_FLAGGED))


def test_rejects_non_folder(tmp_path, optimus_root):
    import pytest
    missing = tmp_path / "nope"
    with Store(optimus_root) as store:
        with pytest.raises(ValueError, match="not a folder"):
            ingest_folder(store, str(missing))
