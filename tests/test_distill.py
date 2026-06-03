"""Tests for distill — fixture-based so the extraction LOGIC is deterministic even
though the model call isn't. The fixture (tests/fixtures/distill_design.json) is a
recorded model response; a StaticCompleter replays it, no live API call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.audit import audit
from core.distill import distill_docs
from core.llm import StaticCompleter
from core.store import Store

# A synthetic decision doc. The fixture's quotes are copied verbatim from lines
# 3, 5, 7 — so audit can verify them against this exact text.
SYNTH_DOC = (
    "# Design Notes\n"                                                            # 1
    "\n"                                                                          # 2
    "We chose SQLite over Postgres to keep deployment free and laptop-local.\n"   # 3
    "\n"                                                                          # 4
    "The crash overlay is defensive-only: it never increases risk exposure.\n"    # 5
    "\n"                                                                          # 6
    "We validate with walk-forward backtesting, not a single train/test split.\n" # 7
)
FIXTURE = (Path(__file__).parent / "fixtures" / "distill_design.json").read_text(encoding="utf-8")
PREFIX = "folder:proj:DESIGN.md"


def _distill(store, mode="expensive", source_root=None):
    return distill_docs(store, project="proj", docs=[(PREFIX, SYNTH_DOC)],
                        completer=StaticCompleter(default=FIXTURE), mode=mode,
                        source_root=source_root)


def test_extracts_decision_claims_with_rationale_and_quote(optimus_root):
    with Store(optimus_root) as store:
        result = _distill(store)
        assert result.kinds.get("decision") == 3
        claims = store.claims_for("proj-decisions")
        d0 = claims[0]
        assert d0.kind == "decision"
        assert "SQLite" in d0.text
        assert d0.rationale and "free" in d0.rationale
        assert d0.quote.startswith("We chose SQLite over Postgres")
        assert d0.source == "folder:proj:DESIGN.md#L3-L3"


def test_decision_claims_survive_reindex(optimus_root):
    """kind/rationale/quote persist in front-matter and rebuild from markdown."""
    with Store(optimus_root) as store:
        _distill(store)
        store.reindex()
        d0 = store.claims_for("proj-decisions")[0]
        assert d0.kind == "decision" and d0.rationale and d0.quote


def test_audit_verifies_distilled_quotes_and_catches_drift(tmp_path, optimus_root):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "DESIGN.md").write_text(SYNTH_DOC, encoding="utf-8")
    with Store(optimus_root) as store:
        _distill(store, source_root=str(proj))       # source_root makes decisions verifiable
        assert audit(store).drift == []              # quotes verbatim → no drift

        # Drift the quote to something the source never says — audit must catch it.
        page = store.read_page("proj-decisions")
        page.claims[0].quote = "We chose MySQL for raw speed."
        store.write_page(page)
        assert any(r.claim_id == "proj-dec-000" for r in audit(store).drift)


def test_cheap_mode_tags_raw_never_decision(optimus_root):
    """The non-negotiable: cheap claims are tagged raw/un-distilled, distinct from
    decisions, with no rationale — so they can't masquerade as understood decisions."""
    with Store(optimus_root) as store:
        result = distill_docs(store, project="proj",
                              docs=[(PREFIX, SYNTH_DOC)], mode="cheap")
        claims = store.claims_for("proj-decisions")
        assert claims
        assert all(c.kind == "raw" for c in claims)
        assert all(c.rationale is None and c.quote is None for c in claims)
        assert result.kinds.get("decision") is None


def test_expensive_mode_requires_a_completer(optimus_root):
    with Store(optimus_root) as store:
        with pytest.raises(ValueError, match="requires a completer"):
            distill_docs(store, project="proj", docs=[(PREFIX, SYNTH_DOC)], mode="expensive")


def test_cheap_page_can_be_upgraded_to_expensive_in_place(optimus_root):
    """Re-running expensive distill replaces raw claims with decision claims."""
    with Store(optimus_root) as store:
        distill_docs(store, project="proj", docs=[(PREFIX, SYNTH_DOC)], mode="cheap")
        assert all(c.kind == "raw" for c in store.claims_for("proj-decisions"))
        _distill(store, mode="expensive")               # upgrade
        upgraded = store.claims_for("proj-decisions")
        assert upgraded and all(c.kind == "decision" for c in upgraded)


def test_parse_tolerates_code_fenced_json(optimus_root):
    fenced = "```json\n" + FIXTURE + "\n```"
    with Store(optimus_root) as store:
        distill_docs(store, project="proj", docs=[(PREFIX, SYNTH_DOC)],
                     completer=StaticCompleter(default=fenced), mode="expensive")
        assert store.claims_for("proj-decisions")
