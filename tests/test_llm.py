"""Tests for the LLM seam — confirms the model boundary is mockable and that the
default refuses to run (so the deterministic core can't silently call out)."""

from __future__ import annotations

import pytest

from core.llm import Completer, NotConfiguredCompleter, StaticCompleter


def test_not_configured_completer_raises():
    with pytest.raises(NotImplementedError, match="not configured"):
        NotConfiguredCompleter().complete("anything")


def test_static_completer_returns_canned_and_records_calls():
    llm = StaticCompleter({"hi": "hello"}, default="?")
    assert llm.complete("hi") == "hello"
    assert llm.complete("unknown", system="s") == "?"
    assert llm.calls == [("hi", None), ("unknown", "s")]


def test_doubles_satisfy_the_protocol():
    assert isinstance(StaticCompleter(), Completer)
    assert isinstance(NotConfiguredCompleter(), Completer)
