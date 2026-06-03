"""Snapshot + behavior tests for deterministic query retrieval (Session 2).

Runs against the synthetic brain (ingest the conftest repo), so it's fully
reproducible and never touches the real Aegis repo. The ranked page-id lists
below are the locked snapshot — a retrieval regression changes them and fails.
"""

from __future__ import annotations

import re

import pytest

from core.ingest import ingest_git
from core.query import format_answer, retrieve
from core.schema import Page
from core.store import Store

# Locked retrieval snapshot: query → ordered page ids expected back.
SNAPSHOTS = {
    "what is Test Project": ["test-project-overview", "test-project-history", "test-project-structure"],
    "test structure":       ["test-project-structure", "test-project-overview", "test-project-history"],
    "test commit history":  ["test-project-history", "test-project-overview", "test-project-structure"],
    "test":                 ["test-project-overview", "test-project-history", "test-project-structure"],
}


@pytest.fixture
def aegis_like(synthetic_repo, optimus_root):
    with Store(optimus_root) as store:
        ingest_git(store, str(synthetic_repo))
        yield store


@pytest.mark.parametrize("query,expected", SNAPSHOTS.items())
def test_retrieval_snapshot(aegis_like, query, expected):
    result = retrieve(aegis_like, query)
    assert [p.page_id for p in result.pages] == expected


def test_intent_routes_to_the_right_page(aegis_like):
    assert retrieve(aegis_like, "test structure").top.page_id == "test-project-structure"
    assert retrieve(aegis_like, "test history").top.page_id == "test-project-history"
    assert retrieve(aegis_like, "what is test project").top.page_id == "test-project-overview"


def test_top_result_carries_provenance(aegis_like):
    top = retrieve(aegis_like, "what is test project").top
    assert top.citations, "expected at least one citation"
    # Page-level provenance is a git span back to a real file.
    assert any(re.match(r"^git:test-project@[0-9a-f]{7}:", c.source) for c in top.citations)


def test_content_term_pulls_in_claim_citation(aegis_like):
    # "widget" appears only in a capability claim → its line-cited source surfaces.
    top = retrieve(aegis_like, "widget").top
    assert top.page_id == "test-project-overview"
    assert any("README.md#L" in c.source and c.text and "Widget" in c.text
               for c in top.citations)


def test_unknown_query_returns_nothing(aegis_like):
    assert retrieve(aegis_like, "quantum chromodynamics tax law").pages == []


def test_format_answer_is_coherent_and_cited(aegis_like):
    answer = format_answer(aegis_like, retrieve(aegis_like, "what is test project"))
    assert "Test Project" in answer
    assert "synthetic repo" in answer
    assert "Sources:" in answer
    assert "git:test-project@" in answer


def test_retrieval_makes_no_llm_call(aegis_like, monkeypatch):
    """Hard guarantee: the retrieval path never imports/touches the model seam."""
    import core.llm as llm

    def boom(*a, **k):
        raise AssertionError("retrieval must be LLM-free")

    monkeypatch.setattr(llm.NotConfiguredCompleter, "complete", boom)
    monkeypatch.setattr(llm.StaticCompleter, "complete", boom)
    result = retrieve(aegis_like, "what is test project")
    assert result.top is not None  # produced a useful answer with the seam untouched


def test_written_page_is_immediately_queryable_without_reindex(optimus_root):
    """Pins 'every written page is immediately queryable' — guards the seed-not-
    indexed regression (write_page must auto-index; no manual reindex required)."""
    with Store(optimus_root) as store:
        store.write_page(Page(
            id="acme-identity", title="Acme Identity", tier=1, type="identity",
            aliases=["Acme"], body="# Acme\n\n> the operative identity\n",
        ))
        # Deliberately NO store.reindex() here.
        top = retrieve(store, "Acme").top
        assert top is not None and top.page_id == "acme-identity"


def test_query_logs_event(aegis_like):
    retrieve(aegis_like, "test structure")
    events = aegis_like.events("query")
    assert events and events[-1]["target"] == "test structure"
