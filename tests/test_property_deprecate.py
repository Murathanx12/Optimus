"""Property test (deprecate step 5): a tombstoned entity is never silently revived.

Generates arbitrary sequences of ingest / deprecate / reindex and asserts the
ground-truth invariant:

    for every tombstone that exists in the store, NO active claim mentions it.

The entity may legitimately appear as a `flagged` claim (held for resolution) or a
`deprecated` claim — just never `active`. The invariant is read off the store's own
tombstone table, not off bookkeeping in the test, so it can't be gamed.

Honest note on invariant strength:
- The `ingest` op drives the REAL folder channel (`ingest_folder` over a generated
  folder), so the property exercises a real ingest pipeline end-to-end — its
  tombstone guard, claim front-matter persistence, and page writes — not a stub.
- It includes `reindex()` as an op, proving the guarantee survives a full
  rebuild-from-markdown mid-sequence.
- Mutation-checked: bypassing the step-4 guard makes the invariant fail (see the
  example tests), so it has teeth.
- BOTH channels share the exact `_flag_tombstoned` guard. The property drives the
  folder channel for speed (no subprocess); the GIT channel's identical behaviour
  is covered by example tests (test_reingest_flags_tombstoned_entity_never_revives,
  test_folder_channel_respects_tombstones). Cloning a git repo per generated
  example would be too slow to run under hypothesis.
- KNOWN LIMIT: asserts across reindex() (which preserves the tombstone table), not
  a full index.db deletion — tombstones aren't yet re-parsed from tombstones.md on
  total index loss (see ARCHITECTURE "Gaps").
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from core.deprecate import alias_pattern, deprecate
from core.ingest import ingest_folder
from core.schema import STATUS_ACTIVE
from core.store import Store

ENTITIES = ["buzzer", "encoder", "servo"]

_op = st.one_of(
    st.tuples(st.just("ingest"),
              st.lists(st.sampled_from(ENTITIES), min_size=1, max_size=3, unique=True)),
    st.tuples(st.just("deprecate"), st.sampled_from(ENTITIES)),
    st.tuples(st.just("reindex")),
)


def _ingest_source(store: Store, entities: list[str], counter: list[int], sources_dir: Path) -> None:
    """Real folder-channel ingest of a generated source mentioning `entities`."""
    counter[0] += 1
    folder = sources_dir / f"src-{counter[0]:03d}"
    folder.mkdir()
    # README capability bullets → one claim per entity (so entities land in claims).
    caps = "\n".join(f"- The {e} subsystem is wired in." for e in entities)
    (folder / "README.md").write_text(
        f"# src {counter[0]}\n\n> generated\n\n## What It Does\n\n{caps}\n", encoding="utf-8")
    ingest_folder(store, str(folder), project=f"src-{counter[0]:03d}")


@settings(max_examples=40, deadline=None)
@given(st.lists(_op, min_size=1, max_size=10))
def test_tombstoned_entity_is_never_silently_revived(op_seq):
    workdir = Path(tempfile.mkdtemp())
    sources = workdir / "_sources"
    sources.mkdir()
    try:
        store = Store(workdir / "brainroot")
        counter = [0]
        for op in op_seq:
            if op[0] == "ingest":
                _ingest_source(store, op[1], counter, sources)
            elif op[0] == "deprecate":
                deprecate(store, op[1], reason="removed in test",
                          date="2026-06-03", confirm=None)
            else:  # reindex — rebuild the index from markdown mid-sequence
                store.reindex()

        active = store.all_claims(status=STATUS_ACTIVE)
        for tomb in store.list_tombstones():
            pat = alias_pattern(tomb["aliases"])
            offenders = [c.text for c in active if pat.search(c.text)]
            assert not offenders, (
                f"entity '{tomb['entity']}' was silently revived to active: {offenders}"
            )
        store.close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
