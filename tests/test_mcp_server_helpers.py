"""Unit tests for the pure helpers behind two MCP tools and the health page.

2026-09-04 (Fable 5.1 review) — three silent defects, each pinned here:
  1. `aegis_verified_state` returned 47-53 KB and exceeded the client's
     tool-output cap, so the session-start protocol's first call was
     unreadable. Now `section="summary"` by default.
  2. `session_briefing` served a 30-hour-old health page with no age check.
     Now a STALE banner is prepended past 12 h; a missing stamp is UNKNOWN.
  3. `health_snapshot._memory_current_state` searched for a heading
     (`## Current state`) that never existed in MEMORY.md and returned a
     prose string that read like a finding. Now it finds `## START HERE`,
     matches a trailing block, and refuses loudly when nothing matches.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("mcp.server.fastmcp")
    return _load(ROOT / "mcp" / "server.py", "optimus_mcp_server_under_test")


@pytest.fixture(scope="module")
def health():
    return _load(ROOT / "tools" / "health_snapshot.py", "optimus_health_snapshot_under_test")


# ---- 1. verified_state sections -------------------------------------------

_PAYLOAD = {
    "status": "ok", "degraded_reasons": [], "deploy": {"commit": "abc"},
    "scheduler": {"jobs": 3}, "nav": {"all_fresh": True}, "track_record": {},
    "llm": {}, "data_sources": {},
    "recent_warnings": ["w"] * 50, "fred_health": {"DGS10": "ok"},
    "forecast_populations": {"x": 1}, "extra_key": 7,
}


def test_summary_default_drops_heavy_keys_and_names_them(server):
    out = server._select_verified_state(_PAYLOAD, "summary")
    assert "recent_warnings" not in out
    assert "fred_health" not in out
    assert "forecast_populations" not in out
    assert out["status"] == "ok" and out["nav"] == {"all_fresh": True}
    assert out["_section"] == "summary"
    assert set(out["_omitted_keys"]) == {"recent_warnings", "fred_health",
                                         "forecast_populations", "extra_key"}


def test_named_sections_fetch_exactly_their_keys(server):
    assert server._select_verified_state(_PAYLOAD, "warnings")["recent_warnings"] == ["w"] * 50
    assert server._select_verified_state(_PAYLOAD, "fred")["fred_health"] == {"DGS10": "ok"}
    assert server._select_verified_state(_PAYLOAD, "all") is _PAYLOAD


def test_unknown_section_is_an_error_not_a_guess(server):
    out = server._select_verified_state(_PAYLOAD, "bogus")
    assert "error" in out and "all" in out["sections"]


def test_default_section_is_summary(server):
    import inspect
    sig = inspect.signature(server.aegis_verified_state)
    assert sig.parameters["section"].default == "summary"


# ---- 2. staleness banner ---------------------------------------------------

def test_fresh_page_gets_no_banner(server):
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    body = "# Aegis program health — generated 2026-09-04 06:15 UTC\n"
    assert server._staleness_banner(body, now) == ""


def test_stale_page_gets_loud_banner(server):
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    body = "# Aegis program health — generated 2026-09-03 06:15 UTC\n"
    banner = server._staleness_banner(body, now)
    assert "STALE" in banner and "29.8 h" in banner and "refresh_aegis" in banner


def test_missing_stamp_is_unknown_never_fresh(server):
    banner = server._staleness_banner("no stamp here")
    assert "age unknown" in banner


# ---- 3. health page memory block -------------------------------------------

_MEMORY_MD = """# Memory Index

## START HERE
- **S37**: the invisible ceiling.
- **S36**: the gate, the clock, the null.

## SESSIONS 17-18
- older stuff
"""


def test_start_here_block_is_found(health):
    block = health._memory_current_state(_MEMORY_MD)
    assert block.startswith("## START HERE")
    assert "S37" in block and "SESSIONS 17-18" not in block


def test_trailing_block_matches(health):
    text = "# Memory Index\n\n## START HERE\n- only section, last in file\n"
    assert "only section" in health._memory_current_state(text)


def test_no_block_refuses_loudly(health):
    out = health._memory_current_state("# Memory Index\n\n## Something else\n")
    assert out.startswith("(NO STATE BLOCK FOUND")
    assert "defect" in out
