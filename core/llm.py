"""LLM seam — the single, mockable boundary for every model call.

Quarantine rule: the deterministic core (schema, store, ingest, and query's
*retrieval*) must NEVER call this. The model enters only at:
  - `distill` — transcript → durable memory (decisions vs. chatter, dispositions),
  - query-synthesis — composing a novel-answer page from retrieved pages.
Both are later sessions. Defining the interface now keeps those features behind
a seam so tests use recorded fixtures, never live API calls, and the core stays
snapshot-testable.

Nothing here makes a network call. A real Anthropic-backed `Completer` lands in
the distill session; until then `NotConfiguredCompleter` is the default and
fails loud if anything reaches for the model prematurely.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Completer(Protocol):
    """Minimal completion interface. distill/query-synthesis depend on this, not
    on any concrete SDK — so the model provider is swappable and mockable."""

    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


class NotConfiguredCompleter:
    """Default seam value. Raises if the deterministic core touches the LLM."""

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        raise NotImplementedError(
            "LLM seam not configured — the deterministic core must not call the model. "
            "Inject a real Completer at distill/query-synthesis time."
        )


class StaticCompleter:
    """Deterministic test double: canned responses by exact-prompt lookup, else a
    default. Lets distill/query-synthesis be tested with fixtures, no live calls."""

    def __init__(self, responses: dict[str, str] | None = None, default: str = "") -> None:
        self._responses = dict(responses or {})
        self._default = default
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append((prompt, system))
        return self._responses.get(prompt, self._default)


class AnthropicCompleter:
    """Real model-backed completer — the production path for distill. Lazily imports
    the SDK so the deterministic core never hard-depends on it. Key comes from the
    arg or $ANTHROPIC_API_KEY. Costs money: only constructed when a key is configured
    and the caller explicitly opts into expensive mode."""

    def __init__(self, model: str = "claude-opus-4-8", api_key: str | None = None,
                 max_tokens: int = 4096) -> None:
        import os

        import anthropic  # lazy: optional dependency
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
