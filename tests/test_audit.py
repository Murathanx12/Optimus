"""Tests for deterministic audit: verify claims against their cited source spans."""

from __future__ import annotations

from core.audit import audit
from core.ingest import ingest_folder, ingest_git
from core.store import Store


def test_audit_passes_a_freshly_ingested_brain(synthetic_repo, optimus_root):
    """Every claim from a fresh git ingest is supported by its cited span."""
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        report = audit(store)
        assert report.checked > 0
        assert report.findings == []
        assert report.ok == report.checked


def test_audit_catches_a_drifted_claim(synthetic_repo, optimus_root):
    """A claim whose text no longer matches its cited source is flagged."""
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        page = store.read_page("test-project-overview")
        target = page.claims[1]                       # a capability claim
        target.text = "This project cures cancer."    # not present at the cited span
        store.write_page(page)

        report = audit(store)
        flagged = [f for f in report.findings if f.reason == "claim-not-supported"]
        assert any(f.claim_id == target.id for f in flagged), "drifted claim must be caught"
        # Only the tampered claim drifts; the rest still verify.
        assert report.ok == report.checked - 1


def test_audit_flags_unreadable_source(synthetic_repo, optimus_root, tmp_path):
    """A folder claim whose source file is gone is reported, not silently trusted."""
    src = tmp_path / "proj"
    src.mkdir()
    (src / "README.md").write_text(
        "# Proj\n\n> desc\n\n## What It Does\n\n- The widget does a thing.\n", encoding="utf-8")
    with Store(optimus_root) as store:
        ingest_folder(store, str(src), project="proj")
        assert audit(store).findings == []            # clean while source exists
        (src / "README.md").unlink()                  # source disappears
        report = audit(store)
        assert any(f.reason == "source-unreadable" for f in report.findings)


def test_audit_skips_claims_without_a_span(synthetic_repo, optimus_root):
    """Tool/desc claims with no line range (folder:slug:.) are skipped, not failed."""
    src = synthetic_repo
    with Store(optimus_root) as store:
        ingest_folder(store, str(src), project="probe")
        report = audit(store)
        # nothing crashes; skipped count is tracked and non-span claims aren't findings
        assert report.skipped >= 1
        assert all(f.reason != "claim-not-supported" or f.claim_id for f in report.findings)
