"""Tests for the front-matter schema + SQLite store (Session 1 task 3)."""

from __future__ import annotations

import sqlite3

from core.schema import STATUS_ACTIVE, Claim, Page, Tier
from core.store import Store


def test_page_roundtrips_through_markdown():
    page = Page(
        id="demo-overview",
        title="Demo — Overview",
        tier=int(Tier.PROJECTS),
        type="overview",
        project="demo",
        aliases=["Demo", "demo"],
        tags=["project", "overview"],
        sources=["git:demo@abc1234:README.md#L1-L40"],
        body="# Demo\n\n> one-liner\n\n- a\n- b",
    )
    text = page.to_markdown()
    assert text.startswith("---\n")
    back = Page.from_markdown(text)
    assert back.id == page.id
    assert back.tier == page.tier
    assert back.sources == page.sources
    assert back.body.strip() == page.body.strip()
    assert back.status == STATUS_ACTIVE


def test_aliases_are_deduped_case_insensitively():
    page = Page(id="x", title="X", tier=2, type="overview",
                aliases=["aegis-finance", "aegis-finance", "Aegis Finance"])
    assert page.aliases == ["aegis-finance", "Aegis Finance"]


def test_front_matter_key_order_is_stable():
    page = Page(id="x", title="X", tier=1, type="identity")
    fm_lines = [ln.split(":")[0] for ln in page.to_markdown().splitlines() if ":" in ln]
    # id must come before title before tier — deterministic order for clean diffs.
    assert fm_lines.index("id") < fm_lines.index("title") < fm_lines.index("tier")


def test_all_six_tables_exist(optimus_root):
    with Store(optimus_root) as store:
        names = {
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    for required in ("pages", "edges", "aliases", "claims", "tombstones", "events"):
        assert required in names, f"missing table: {required}"


def test_write_page_indexes_and_reads_back(optimus_root):
    with Store(optimus_root) as store:
        page = Page(
            id="demo-overview", title="Demo", tier=int(Tier.PROJECTS),
            type="overview", project="demo", body="hello",
        )
        path = store.write_page(page)
        assert path.exists()
        assert store.page_count(project="demo") == 1
        got = store.read_page("demo-overview")
        assert got is not None and got.body.strip() == "hello"


def test_aliases_resolve_case_insensitively(optimus_root):
    with Store(optimus_root) as store:
        store.write_page(Page(
            id="aegis-overview", title="Aegis Finance", tier=int(Tier.PROJECTS),
            type="overview", project="aegis-finance",
            aliases=["Aegis", "aegis-finance"], body="x",
        ))
        assert store.resolve_alias("AEGIS") == ["aegis-overview"]
        assert store.resolve_alias("aegis finance") == ["aegis-overview"]


def test_claims_carry_provenance(optimus_root):
    with Store(optimus_root) as store:
        store.write_page(Page(
            id="p", title="P", tier=2, type="overview", project="demo", body="x",
            claims=[Claim(id="c1", page_id="p", text="does the thing",
                          source="git:demo@abc1234:README.md#L12-L12", tier=2)],
        ))
        claims = store.claims_for("p")
        assert len(claims) == 1
        assert claims[0].source.startswith("git:demo@")


def test_claims_roundtrip_through_markdown_with_status():
    """Claims + their status persist in front-matter (the portability fix)."""
    page = Page(
        id="p", title="P", tier=2, type="overview", project="demo", body="x",
        claims=[
            Claim(id="c1", page_id="p", text="active fact",
                  source="git:demo@abc1234:README.md#L1-L1", tier=2),
            Claim(id="c2", page_id="p", text="dead fact",
                  source="git:demo@abc1234:README.md#L2-L2", tier=2, status="deprecated"),
        ],
    )
    back = Page.from_markdown(page.to_markdown())
    assert [(c.id, c.text, c.source, c.status) for c in back.claims] == [
        ("c1", "active fact", "git:demo@abc1234:README.md#L1-L1", "active"),
        ("c2", "dead fact", "git:demo@abc1234:README.md#L2-L2", "deprecated"),
    ]
    assert all(c.page_id == "p" and c.tier == 2 for c in back.claims)  # derived from page


def test_reindex_rebuilds_from_markdown(optimus_root):
    """SQLite is derived: wiping index rows and reindexing from .md restores them."""
    with Store(optimus_root) as store:
        store.write_page(Page(id="p1", title="One", tier=2, type="overview", project="demo", body="a"))
        store.write_page(Page(id="p2", title="Two", tier=2, type="structure", project="demo", body="b"))
        store._conn.execute("DELETE FROM pages")
        store._conn.commit()
        assert store.page_count() == 0
        n = store.reindex()
        assert n == 2
        assert store.page_count() == 2


def test_event_log_records_ops(optimus_root):
    with Store(optimus_root) as store:
        store.log_event("ingest", target="demo", detail={"files": 3})
        events = store.events("ingest")
        assert len(events) == 1
        assert events[0]["target"] == "demo"
