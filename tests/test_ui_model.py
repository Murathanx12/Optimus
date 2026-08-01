"""ui.model — the read-only payload builders the viewer serves.

Verifies graph assembly, audit aggregation (incl. the loud-drift rule), page
detail with bound audit states, alias-resolving search, and that a deliberately
drifted claim surfaces as a red ('drifted') node end-to-end — all over a brain
opened read_only=True, without ever mutating the real brain.
"""

from __future__ import annotations

import pytest

from core.audit import (
    STATE_DRIFTED,
    STATE_SKIPPED,
    STATE_UNVERIFIABLE,
    STATE_VERIFIED,
    audit,
)
from core.schema import Page, Tier
from core.store import Store
from ui import model


def test_aggregate_state_priority():
    assert model.aggregate_state([]) == model.NODE_NONE
    # drift dominates everything
    assert model.aggregate_state([STATE_VERIFIED, STATE_DRIFTED, STATE_UNVERIFIABLE]) == STATE_DRIFTED
    # verified beats merely-uncheckable when nothing drifted
    assert model.aggregate_state([STATE_VERIFIED, STATE_UNVERIFIABLE, STATE_SKIPPED]) == STATE_VERIFIED
    # uncheckable beats skipped
    assert model.aggregate_state([STATE_UNVERIFIABLE, STATE_SKIPPED]) == STATE_UNVERIFIABLE
    assert model.aggregate_state([STATE_SKIPPED]) == STATE_SKIPPED


def _folder_brain(root) -> Store:
    """A brain whose claims cite a real local folder, so audit can VERIFY them."""
    src = root / "src"
    src.mkdir(parents=True)
    (src / "README.md").write_text(
        "alpha line one\nbeta line two\ngamma line three\n", encoding="utf-8"
    )
    store = Store(root)
    page = Page(
        id="p-overview", title="P Overview", tier=Tier.PROJECTS, type="overview",
        project="p", aliases=["the proj"], source_root=str(src),
        sources=["folder:p:README.md#L1-L1"],
    )
    page.claims = [
        # verified: the cited line really contains the text
        page_claim("p-c-0", "p-overview", "README.md: alpha line one",
                   "folder:p:README.md#L1-L1"),
        # drifted: cited line exists but does NOT contain this text
        page_claim("p-c-1", "p-overview", "README.md: nonexistent claim text",
                   "folder:p:README.md#L2-L2"),
        # skipped: no re-readable span
        page_claim("p-c-2", "p-overview", "freeform note", "note:scratch"),
    ]
    store.write_page(page)
    store.close()
    return Store(root, read_only=True)


def page_claim(cid, pid, text, source):
    from core.schema import Claim
    return Claim(id=cid, page_id=pid, text=text, source=source, tier=2, kind="fact")


def test_build_graph_and_drift_is_red(optimus_root):
    ro = _folder_brain(optimus_root)
    report = audit(ro)
    graph = model.build_graph(ro, report)

    assert graph["summary"]["pages"] == 1
    node = graph["nodes"][0]
    # one verified, one drifted, one skipped → page aggregates to the loud DRIFTED state
    assert node["audit_state"] == STATE_DRIFTED
    assert node["audit_counts"][STATE_VERIFIED] == 1
    assert node["audit_counts"][STATE_DRIFTED] == 1
    assert node["audit_counts"][STATE_SKIPPED] == 1
    assert graph["summary"]["drifted"] == 1
    ro.close()


def test_page_detail_binds_audit_states(optimus_root):
    ro = _folder_brain(optimus_root)
    report = audit(ro)
    detail = model.page_detail(ro, report, "p-overview")
    assert detail is not None
    states = {c["id"]: c["audit"]["state"] for c in detail["claims"]}
    assert states["p-c-0"] == STATE_VERIFIED
    assert states["p-c-1"] == STATE_DRIFTED
    assert states["p-c-2"] == STATE_SKIPPED
    assert detail["source_root"] is not None
    ro.close()


def test_page_detail_missing(optimus_root):
    ro = _folder_brain(optimus_root)
    report = audit(ro)
    assert model.page_detail(ro, report, "no-such-page") is None
    ro.close()


def test_search_resolves_alias(optimus_root):
    ro = _folder_brain(optimus_root)
    results = model.search(ro, "the proj")
    assert any(r["page_id"] == "p-overview" for r in results)
    # substring/title match also works
    assert any(r["page_id"] == "p-overview" for r in model.search(ro, "overview"))
    assert model.search(ro, "") == []
    ro.close()


def test_unverifiable_aggregates_grey(optimus_root):
    """A claim whose source_root is absent → unverifiable-here (grey), not drift."""
    store = Store(optimus_root)
    page = Page(
        id="u-overview", title="U", tier=Tier.PROJECTS, type="overview", project="u",
        source_root=str(optimus_root / "does-not-exist"),
        sources=["folder:u:README.md#L1-L1"],
    )
    page.claims = [page_claim("u-c-0", "u-overview", "README.md: anything",
                              "folder:u:README.md#L1-L1")]
    store.write_page(page)
    store.close()
    ro = Store(optimus_root, read_only=True)
    graph = model.build_graph(ro, audit(ro))
    assert graph["nodes"][0]["audit_state"] == STATE_UNVERIFIABLE
    ro.close()
