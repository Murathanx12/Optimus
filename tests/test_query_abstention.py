"""Abstention + domain scoping (Optimus audit 2026-07-29, fixes #1 and #2).

The bug these pin, verbatim from the audit: querying the live brain for
*"control arm invalidated trial pseudo-event placebo"* returned
``frc-plane-school-overview`` — an FRC robotics project — at score **4.0**,
above ``aegis-finance-overview`` at **2.0**. Two independent defects:

  1. no floor: the retriever always returned its top-k however far away it was,
  2. no scope: a robotics page could out-score the live finance program.

Both are reproduced here on a synthetic mixed-domain brain, so the tests fail if
either regression returns.
"""

from __future__ import annotations

import pytest

from core import domains
from core.query import FLOOR_SCORE, format_answer, retrieve
from core.schema import Claim, Page, Tier
from core.store import Store

FIN = "alpha-fin"
ROBO = "robo-bot"
NEW = "brand-new"          # a project nobody has registered in domains.py yet


def _page(pid: str, title: str, project: str, body: str,
          claims: list[str], ptype: str = "overview") -> Page:
    page = Page(
        id=pid, title=title, tier=int(Tier.PROJECTS), type=ptype, project=project,
        aliases=[project], tags=["project"], sources=[f"git:{project}@abc1234:README.md"],
        body=body,
    )
    page.claims = [
        Claim(id=f"{pid}-c{i}", page_id=pid, text=t,
              source=f"git:{project}@abc1234:README.md#L{i + 1}-L{i + 1}",
              tier=int(Tier.PROJECTS))
        for i, t in enumerate(claims)
    ]
    return page


@pytest.fixture
def mixed_brain(optimus_root, monkeypatch):
    """A finance project, a robotics project, and an unregistered one.

    The robotics page is built to WIN on raw score for "control arm crash" — its
    title carries all three terms (+5 each) while the finance page only has them
    in claims (+2 each). That is the audit's failure geometry, reproduced: if
    domain scoping stops working, robotics comes back out on top.
    """
    monkeypatch.setitem(domains.PROJECT_DOMAIN, FIN, domains.FINANCE)
    monkeypatch.setitem(domains.PROJECT_DOMAIN, ROBO, domains.ROBOTICS)
    # NEW is deliberately NOT registered.
    with Store(optimus_root) as store:
        store.write_page(_page(
            "alpha-fin-overview", "Alpha Fin — Overview", FIN,
            "# Alpha Fin\n\n> Crash probability with a control arm.\n",
            ["Crash probability model validated against a control arm",
             "Portfolio sharpe, drawdown and nav analytics"],
        ))
        store.write_page(_page(
            "robo-bot-overview", "Control Arm Crash Detection — Overview", ROBO,
            "# Control Arm Crash Detection\n\n> The control arm crash sensor.\n",
            ["The control arm crash sensor logs every crash of the arm"],
        ))
        store.write_page(_page(
            "brand-new-overview", "Brand New — Overview", NEW,
            "# Brand New\n\n> An unregistered project with a control arm too.\n",
            ["Unregistered project mentioning a control arm"],
        ))
        yield store


# --------------------------------------------------------------------------- #
# (a) abstention
# --------------------------------------------------------------------------- #
def test_off_domain_query_abstains_with_diagnostics(mixed_brain):
    """A query the corpus cannot answer returns no_match — not the nearest page."""
    result = retrieve(mixed_brain, "kubernetes ingress control tls termination")

    assert result.abstained is True
    assert result.pages == [], "abstention must return NOTHING, not the best of a bad lot"
    # The diagnostics are the point: the caller can see the floor and what lost.
    assert result.floor == FLOOR_SCORE
    assert result.rejected, "must report what was rejected, so no_match is auditable"
    best = result.rejected[0]
    assert best.score < result.floor
    assert 0 < best.coverage < 1.0

    payload = result.as_dict()
    assert payload["status"] == "no_match"
    assert payload["floor"] == FLOOR_SCORE
    assert payload["best_rejected"][0]["score"] == round(best.score, 3)
    assert payload["best_rejected"][0]["domain"]          # domain always reported
    assert "nearest document" in payload["reason"]

    rendered = format_answer(mixed_brain, result)
    assert rendered.startswith("no_match:")
    assert str(FLOOR_SCORE).rstrip("0").rstrip(".") in rendered
    assert best.page_id in rendered


def test_pure_garbage_abstains_with_nothing_to_reject(mixed_brain):
    result = retrieve(mixed_brain, "quantum chromodynamics tax law")
    assert result.pages == []
    assert result.abstained is False        # nothing scored at all — different state
    assert result.as_dict()["status"] == "empty"


def test_floor_is_overridable_for_inspecting_near_misses(mixed_brain):
    """The floor is a parameter, not a wall: a caller may lower it deliberately."""
    q = "kubernetes ingress control tls termination"
    assert retrieve(mixed_brain, q).abstained is True
    loose = retrieve(mixed_brain, q, floor=1.0)
    assert loose.abstained is False and loose.pages


# --------------------------------------------------------------------------- #
# (b) domain scoping
# --------------------------------------------------------------------------- #
def test_robotics_outscores_finance_without_scoping(mixed_brain):
    """The premise of the next two tests: on raw score alone, robotics WINS.

    This is the audit's measurement (FRC 4.0 > aegis-finance 2.0) reproduced.
    If this assertion ever fails the scoping tests below prove nothing.
    """
    result = retrieve(mixed_brain, "control arm crash", floor=0.0)
    by_id = {p.page_id: p.score for p in result.pages}
    assert by_id["robo-bot-overview"] > by_id["alpha-fin-overview"]


def test_hard_finance_scope_drops_robotics_entirely(mixed_brain):
    result = retrieve(mixed_brain, "control arm crash", domain="finance")
    ids = [p.page_id for p in result.pages]
    assert "robo-bot-overview" not in ids, "explicit scope must DROP other domains"
    assert result.top.page_id == "alpha-fin-overview"
    assert result.domain == "finance" and result.domain_source == "requested"


def test_inferred_finance_scope_demotes_robotics_below_finance(mixed_brain):
    """No domain passed: inferred from wording. Nothing is dropped, but the
    higher-scoring robotics page can no longer out-rank the finance page."""
    result = retrieve(mixed_brain, "control arm crash nav")
    assert result.domain == "finance" and result.domain_source == "inferred"
    ids = [p.page_id for p in result.pages]
    assert ids[0] == "alpha-fin-overview"
    assert "robo-bot-overview" in ids, "soft scope demotes, it must not drop"
    scores = {p.page_id: p.score for p in result.pages}
    assert scores["robo-bot-overview"] > scores["alpha-fin-overview"], (
        "the ordering must come from domain rank, not from score"
    )


def test_unregistered_project_is_demoted_never_dropped(mixed_brain):
    """Forgetting to register a project in domains.py must degrade ranking, not
    silently delete the project from every scoped query (the house failure mode)."""
    result = retrieve(mixed_brain, "control arm crash", domain="finance")
    ids = [p.page_id for p in result.pages]
    assert "brand-new-overview" in ids
    assert ids.index("alpha-fin-overview") < ids.index("brand-new-overview")


def test_unknown_domain_is_a_loud_error(mixed_brain):
    with pytest.raises(ValueError, match="unknown domain"):
        retrieve(mixed_brain, "control arm crash", domain="cryptozoology")


def test_ambiguous_query_is_not_scoped_at_all(mixed_brain):
    """Markers from two domains tie → no scoping (default behaviour preserved)."""
    result = retrieve(mixed_brain, "portfolio servo control arm", floor=0.0)
    assert result.domain is None and result.domain_source == "none"
    assert all(p.rank == 0 for p in result.pages)


# --------------------------------------------------------------------------- #
# (c) no over-abstention
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("query,expected", [
    ("alpha-fin", "alpha-fin-overview"),                       # alias
    ("crash probability model", "alpha-fin-overview"),         # content, in-domain
    ("portfolio sharpe drawdown nav", "alpha-fin-overview"),   # content, in-domain
    ("control arm crash sensor", "robo-bot-overview"),         # robotics, unscoped
])
def test_in_domain_queries_still_answer(mixed_brain, query, expected):
    result = retrieve(mixed_brain, query)
    assert not result.abstained, f"over-abstention on {query!r}"
    assert result.top.page_id == expected
    assert result.top.score >= FLOOR_SCORE


def test_answered_result_still_carries_citations(mixed_brain):
    top = retrieve(mixed_brain, "crash probability model").top
    assert any("README.md#L" in c.source for c in top.citations)
