"""Tests for the git-channel ingest path (Session 1 task 3)."""

from __future__ import annotations

import re

import pytest

from core.ingest import ingest_git
from core.store import Store


def test_ingest_produces_three_project_pages(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        result = ingest_git(store, str(synthetic_repo))
        assert result.project == "test-project"
        assert set(result.pages) == {
            "test-project-overview",
            "test-project-structure",
            "test-project-history",
        }
        assert store.page_count(project="test-project") == 3


def test_ingest_excludes_gitignored_secrets(synthetic_repo, optimus_root):
    """The .env secret must never reach a brain page (we read `git ls-files`)."""
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        structure = store.read_page("test-project-structure")
        assert structure is not None
        assert ".env" not in structure.body
        assert "super-secret" not in structure.body
        # Sanity: tracked source files DID make it into the module map.
        assert "backend" in structure.body
        assert "engine" in structure.body


def test_claims_have_line_level_provenance(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        result = ingest_git(store, str(synthetic_repo))
        claims = store.claims_for("test-project-overview")
        assert claims, "expected capability claims from README"
        # Every claim source is a git span pointing at README with a line range.
        span = re.compile(r"^git:test-project@[0-9a-f]{7}:README\.md#L\d+-L\d+$")
        assert all(span.match(c.source) for c in claims)
        texts = [c.text for c in claims]
        assert any("Widget engine" in t for t in texts)


def test_overview_captures_title_and_description(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        overview = store.read_page("test-project-overview")
        assert "Test Project" in overview.body
        assert "synthetic repo" in overview.body
        assert overview.tier == 2  # Tier.PROJECTS


def test_display_title_used_across_all_pages_not_slug(synthetic_repo, optimus_root):
    """title = README H1 (display) on every page; id stays the slug (machine key)."""
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        for pid, suffix in [
            ("test-project-structure", "Structure"),
            ("test-project-history", "Commit History"),
        ]:
            page = store.read_page(pid)
            assert page.title == f"Test Project — {suffix}"   # display name, not "test-project"
            assert page.id == pid                              # id is the immutable slug key
            assert f"# Test Project — {suffix}" in page.body


def test_project_aliases_resolve_to_overview(synthetic_repo, optimus_root):
    """Slug, display name, and short form all resolve to the canonical overview page."""
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        for alias in ("test-project", "Test Project", "test", "TEST PROJECT"):
            assert store.resolve_alias(alias) == ["test-project-overview"], alias


def test_history_counts_commits(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        result = ingest_git(store, str(synthetic_repo))
        assert result.commit_count == 2
        history = store.read_page("test-project-history")
        assert "Total commits: **2**" in history.body
        assert "feat: bump return value" in history.body


def test_provenance_sha_matches_head(synthetic_repo, optimus_root):
    import subprocess

    head = subprocess.run(
        ["git", "-C", str(synthetic_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    with Store(optimus_root) as store:
        result = ingest_git(store, str(synthetic_repo))
        assert result.sha == head
        overview = store.read_page("test-project-overview")
        assert head[:7] in overview.sources[0]


def test_edges_link_structure_and_history_to_overview(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        rows = store._conn.execute(
            "SELECT src_page_id, dst_page_id, rel FROM edges ORDER BY src_page_id"
        ).fetchall()
        edges = {(r["src_page_id"], r["dst_page_id"], r["rel"]) for r in rows}
        assert ("test-project-structure", "test-project-overview", "part_of") in edges
        assert ("test-project-history", "test-project-overview", "part_of") in edges


def test_ingest_logs_event(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        events = store.events("ingest")
        assert len(events) == 1
        assert events[0]["target"] == "test-project"


def test_rejects_non_git_path(tmp_path, optimus_root):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with Store(optimus_root) as store:
        with pytest.raises(ValueError, match="not a git repository"):
            ingest_git(store, str(plain))
