"""Tests for deprecate (Session 3, steps 1-3): resolve+find, stage diffs, atomic
apply with tombstone. Reproduces the Artooth buzzer strike-through scenario
against a synthetic brain. Step 4 (block re-ingestion) + step 5 (hypothesis
property test) are the next session.
"""

from __future__ import annotations

import pytest

from core.deprecate import deprecate, find_references, stage_diffs
from core.query import retrieve
from core.schema import STATUS_ACTIVE, STATUS_DEPRECATED, Claim, Page
from core.store import Store

REASON = "buzzer removed from Artooth hardware"
DATE = "2026-06-03"
NOTE = f"(deprecated {DATE}: {REASON})"


@pytest.fixture
def buzzer_brain(optimus_root):
    """Five Artooth 'notes', each mentioning the buzzer in body + a claim."""
    store = Store(optimus_root)
    for i in range(1, 6):
        pid = f"artooth-note-{i:02d}"
        store.write_page(Page(
            id=pid, title=f"Artooth Note {i}", tier=2, type="note", project="artooth",
            body=f"# Note {i}\n\n- The buzzer beeps when a crash is detected (note {i}).\n",
        ))
        store.write_claims([Claim(
            id=f"{pid}-c1", page_id=pid,
            text=f"The buzzer beeps when a crash is detected (note {i}).",
            source=f"raw:notes/note{i}.md#L3-L3", tier=2,
        )])
    yield store
    store.close()


def test_find_references_locates_all_mentions(buzzer_brain):
    refset = find_references(buzzer_brain, "buzzer")
    assert refset.page_count == 5
    assert refset.line_count == 5
    assert len(refset.claim_ids) == 5
    assert "buzzer" in refset.aliases
    assert "Found 5 reference" in refset.preview()


def test_stage_diffs_shows_strikethrough_without_applying(buzzer_brain):
    refset = find_references(buzzer_brain, "buzzer")
    diffs = stage_diffs(buzzer_brain, refset, REASON, DATE)
    assert len(diffs) == 5
    sample = next(iter(diffs.values()))
    assert "~~" in sample and NOTE in sample
    # Not applied: the page on disk is untouched.
    page = buzzer_brain.read_page("artooth-note-01")
    assert "~~" not in page.body


def test_apply_strikes_all_five_pages_and_tombstones(buzzer_brain):
    result = deprecate(buzzer_brain, "buzzer", reason=REASON, date=DATE, confirm=None)
    assert result.applied

    # 1. all five pages show the struck claim + note
    for i in range(1, 6):
        page = buzzer_brain.read_page(f"artooth-note-{i:02d}")
        assert "~~" in page.body
        assert NOTE in page.body
        assert "buzzer" in page.body.lower()  # text retained, struck not deleted

    # 2. every matching claim is deprecated
    assert len(buzzer_brain.all_claims(status=STATUS_DEPRECATED)) == 5
    assert buzzer_brain.all_claims(status=STATUS_ACTIVE) == []

    # 3. tombstone written to index + markdown
    tombs = buzzer_brain.list_tombstones()
    assert len(tombs) == 1
    assert tombs[0]["entity"] == "buzzer"
    assert sorted(tombs[0]["pages"]) == [f"artooth-note-{i:02d}" for i in range(1, 6)]
    md = (buzzer_brain.brain / "tombstones.md").read_text(encoding="utf-8")
    assert "## buzzer" in md and REASON in md

    # 4. event logged
    assert buzzer_brain.events("deprecate")


def test_deprecated_content_no_longer_surfaces_in_query(buzzer_brain):
    assert retrieve(buzzer_brain, "buzzer").pages, "sanity: buzzer is findable before deprecate"
    deprecate(buzzer_brain, "buzzer", reason=REASON, date=DATE, confirm=None)
    # Weight → 0: deprecated claims excluded, so the term no longer retrieves.
    assert retrieve(buzzer_brain, "buzzer").pages == []


def test_dry_run_changes_nothing(buzzer_brain):
    result = deprecate(buzzer_brain, "buzzer", reason=REASON, date=DATE, dry_run=True)
    assert not result.applied
    assert result.refset.page_count == 5            # preview still computed
    assert "~~" not in buzzer_brain.read_page("artooth-note-01").body
    assert buzzer_brain.list_tombstones() == []


def test_declined_confirm_changes_nothing(buzzer_brain):
    result = deprecate(buzzer_brain, "buzzer", reason=REASON, date=DATE,
                       confirm=lambda refset, diffs: False)
    assert not result.applied
    assert "~~" not in buzzer_brain.read_page("artooth-note-01").body
    assert buzzer_brain.all_claims(status=STATUS_ACTIVE)


def test_apply_is_atomic_rolls_back_on_failure(buzzer_brain, monkeypatch):
    """If a late write fails, no page is struck and no claim is deprecated."""
    def boom(*a, **k):
        raise RuntimeError("injected tombstone failure")

    monkeypatch.setattr(buzzer_brain, "write_tombstone", boom)
    with pytest.raises(RuntimeError, match="injected"):
        deprecate(buzzer_brain, "buzzer", reason=REASON, date=DATE, confirm=None)

    # Everything restored: no strike-throughs, claims active, no tombstone.
    for i in range(1, 6):
        assert "~~" not in buzzer_brain.read_page(f"artooth-note-{i:02d}").body
    assert len(buzzer_brain.all_claims(status=STATUS_ACTIVE)) == 5
    assert buzzer_brain.all_claims(status=STATUS_DEPRECATED) == []
    assert buzzer_brain.list_tombstones() == []


def test_entity_page_itself_is_deprecated(optimus_root):
    """If the entity resolves to a page (alias), that page's status flips too."""
    store = Store(optimus_root)
    store.write_page(Page(
        id="buzzer-component", title="Buzzer", tier=2, type="entity", project="artooth",
        aliases=["buzzer", "piezo buzzer"], body="# Buzzer\n\nThe piezo buzzer alerts on crash.\n",
    ))
    deprecate(store, "buzzer", reason=REASON, date=DATE, confirm=None)
    row = store._conn.execute(
        "SELECT status FROM pages WHERE id='buzzer-component'"
    ).fetchone()
    assert row["status"] == STATUS_DEPRECATED
    store.close()
