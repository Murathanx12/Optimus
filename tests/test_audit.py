"""Tests for three-state audit + durable, portable verifiability.

VERIFIED / DRIFTED (loud, = wrong) / UNVERIFIABLE-HERE (quiet, = uncheckable).
Source root lives in page front-matter, so verifiability survives index deletion
and a moved brain degrades gracefully instead of looking 100% broken."""

from __future__ import annotations

import re
from pathlib import Path

from core.audit import (
    STATE_DRIFTED,
    STATE_UNVERIFIABLE,
    STATE_VERIFIED,
    audit,
)
from core.ingest import ingest_folder, ingest_git
from core.store import Store

README = (
    "# Proj\n"                                       # 1
    "\n"                                             # 2
    "> a small project\n"                            # 3
    "\n"                                             # 4
    "## What It Does\n"                              # 5
    "\n"                                             # 6
    "- The widget subsystem does the thing.\n"       # 7
)


def _state(report, claim_id):
    return next((r.state for r in report.results if r.claim_id == claim_id), None)


def _capability_claim(store):
    return next(c for c in store.claims_for("proj-overview") if "widget" in c.text.lower())


def test_freshly_ingested_brain_is_all_verified(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        report = audit(store)
        assert report.verified > 0
        assert report.drifted == 0
        assert report.unverifiable == 0


def test_three_states_verified_unverifiable_drifted(tmp_path, optimus_root):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text(README, encoding="utf-8")
    with Store(optimus_root) as store:
        ingest_folder(store, str(folder), project="proj")
        cap = _capability_claim(store)

        # 1. VERIFIED — source reachable, quote present.
        assert _state(audit(store), cap.id) == STATE_VERIFIED

        # 2. UNVERIFIABLE-HERE — delete the source file; NOT a failure.
        (folder / "README.md").unlink()
        report = audit(store)
        assert _state(report, cap.id) == STATE_UNVERIFIABLE
        rec = next(r for r in report.results if r.claim_id == cap.id)
        assert rec.as_of and rec.quote                # last-known-good still reported
        assert report.drifted == 0                    # nothing is "wrong"

        # 3. DRIFTED — restore the file but change the cited line; loud.
        line_no = int(re.search(r"#L(\d+)", cap.source).group(1))
        lines = README.splitlines()
        lines[line_no - 1] = "- The gadget does something unrelated now."
        (folder / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = audit(store)
        assert _state(report, cap.id) == STATE_DRIFTED
        assert any(r.claim_id == cap.id for r in report.drift)


def test_source_ref_survives_full_index_deletion(tmp_path, optimus_root):
    """Verifiability is durable: source_root rebuilds from front-matter, so audit
    still VERIFIES after the entire index.db is deleted — no events dependency."""
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text(README, encoding="utf-8")
    store = Store(optimus_root)
    ingest_folder(store, str(folder), project="proj")
    cap_id = _capability_claim(store).id
    assert _state(audit(store), cap_id) == STATE_VERIFIED
    store.close()

    (Path(optimus_root) / "brain" / "index.db").unlink()      # nuke the derived index
    store2 = Store(optimus_root)
    store2.reindex()                                          # rebuild from markdown alone
    assert _state(audit(store2), cap_id) == STATE_VERIFIED, \
        "source_root must survive index deletion (durable verifiability)"
    store2.close()


def test_moved_brain_is_unverifiable_not_broken(tmp_path, optimus_root):
    """The teardown scenario: source repo absent → UNVERIFIABLE-HERE, never DRIFTED."""
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "README.md").write_text(README, encoding="utf-8")
    with Store(optimus_root) as store:
        ingest_folder(store, str(folder), project="proj")
        import shutil
        shutil.rmtree(folder)                                 # whole source root gone
        report = audit(store)
        assert report.drifted == 0                            # not "wrong"
        assert report.unverifiable >= 1                       # just uncheckable here


def test_tampered_claim_text_is_drifted(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        page = store.read_page("test-project-overview")
        page.claims[1].text = "This project cures cancer."     # source never says this
        store.write_page(page)
        report = audit(store)
        assert any(r.claim_id == page.claims[1].id for r in report.drift)
