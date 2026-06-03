"""Property test (deprecate step 5): a tombstoned entity is never silently revived.

Generates arbitrary sequences of ingest / deprecate / reindex over a small entity
set and asserts the ground-truth invariant:

    for every tombstone that exists in the store, NO active claim mentions it.

The entity may legitimately appear as a `flagged` claim (held for resolution) or a
`deprecated` claim — just never `active`. The invariant is read off the store's own
tombstone table, not off bookkeeping in the test, so it can't be gamed.

Honest note on invariant strength:
- STRONG on what matters most: it uses the REAL deprecate() and the REAL
  _flag_tombstoned() (the step-4 guard), and it includes reindex() as an op, so it
  proves the guarantee survives a rebuild-from-markdown mid-sequence.
- SIMPLIFIED in one place: "ingest" is simulated by writing a page whose claims
  mention the entities (via the real flagging path), not by cloning a git repo per
  step — that would be too slow under hypothesis. The full git/folder ingest
  flagging is covered by the example tests (test_reingest_flags_*).
- KNOWN LIMIT: this exercises reindex() (which preserves the tombstone table), not
  a full index-file deletion. Tombstones are not yet re-parsed from tombstones.md
  on total index loss (see ARCHITECTURE "Gaps") — so this invariant is asserted
  across reindex, not across nuking index.db.
"""

from __future__ import annotations

import shutil
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from core.deprecate import alias_pattern, deprecate
from core.ingest import _flag_tombstoned
from core.schema import STATUS_ACTIVE, Claim, Page
from core.store import Store

ENTITIES = ["buzzer", "encoder", "servo"]

# An op is one of: ingest a set of entities, deprecate one, or reindex.
_op = st.one_of(
    st.tuples(st.just("ingest"),
              st.lists(st.sampled_from(ENTITIES), min_size=1, max_size=3, unique=True)),
    st.tuples(st.just("deprecate"), st.sampled_from(ENTITIES)),
    st.tuples(st.just("reindex")),
)


def _simulate_ingest(store: Store, entities: list[str], counter: list[int]) -> None:
    """Write a 'source' page whose claims mention `entities`, through the real
    tombstone-flagging path (step 4)."""
    counter[0] += 1
    sid = f"src-{counter[0]:03d}"
    claims = [
        Claim(id=f"{sid}-{e}", page_id=sid, text=f"The {e} is part of the build.",
              source=f"folder:{sid}:notes.md#L1", tier=2)
        for e in entities
    ]
    _flag_tombstoned(store, claims)                       # real step-4 guard
    body = "\n".join(f"- The {e} is part of the build." for e in entities)
    store.write_page(Page(id=sid, title=f"Source {counter[0]}", tier=2, type="note",
                          project="probe", body=f"# {sid}\n\n{body}\n", claims=claims))


@settings(max_examples=60, deadline=None)
@given(st.lists(_op, min_size=1, max_size=12))
def test_tombstoned_entity_is_never_silently_revived(op_seq):
    workdir = tempfile.mkdtemp()
    try:
        store = Store(workdir)
        counter = [0]
        for op in op_seq:
            if op[0] == "ingest":
                _simulate_ingest(store, op[1], counter)
            elif op[0] == "deprecate":
                deprecate(store, op[1], reason="removed in test",
                          date="2026-06-03", confirm=None)
            else:  # reindex — rebuild the index from markdown mid-sequence
                store.reindex()

        # Ground-truth invariant: nothing active may mention a tombstoned entity.
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
