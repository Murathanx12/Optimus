# Re-ingest + retrieval scope

Two things rot on their own: the **corpus** (it only knows what it was last fed)
and the **floor** (calibrated against a corpus of a given size and shape). This
is the note for keeping both honest. It is a *note*, not a cron job — re-ingest
is a deliberate act, run at a known commit, so the brain can always say which
commit it knows about.

## When to re-run

**After each research round, freeze, or panel adjudication** — i.e. whenever
`aegis-finance` accumulates a batch of `research:` commits or new files land in
`docs/research/`. Also after any Aegis release or big refactor.

The failure this prevents was measured on 2026-07-29: the corpus was last
ingested at `cb01d8b` (2026-06-17), so rounds 7-13, the whole Strategy Factory,
and the 2026-07-28 freeze at 158 candidates were **invisible** to `brain_query`.
Asked about the freeze it answered *"No brain pages matched"*; asked about the
belief engine it returned the dead V5/V7 ancestor codebases.

## The command

From the Optimus repo root, using its own venv:

```bash
cd C:/Users/mrthn/optimus

# 1. the live program, at HEAD (git channel: overview + structure + history)
.venv/Scripts/python.exe optimus.py ingest --git "C:/Users/mrthn/aegis-finance"

# 2. the research module (TRIALS, ledger, methodology)
.venv/Scripts/python.exe optimus.py ingest --git "C:/Users/mrthn/Aegis module"

# 3. the research docs, as their own project (folder channel: one claim per doc)
.venv/Scripts/python.exe optimus.py ingest --folder \
    "C:/Users/mrthn/aegis-finance/docs/research" --project aegis-research
```

Ingest is idempotent — it rewrites the same page ids from source, so re-running
is safe. Back the brain up first if you want a rollback point
(`tools/backup_brain.py`, or just copy `brain/`).

Last run: **2026-07-29**, `aegis-finance@da6b22d`, `Aegis module@1847497` →
25 pages. Verify with a query for material that is new in this round:

```bash
.venv/Scripts/python.exe optimus.py query "freeze 158"
# -> aegis-finance-history / aegis-module-history, score 32
```

### What each channel actually captures

| Channel | Sees | Does NOT see |
|---|---|---|
| `--git` overview | README title, description, "What it does" bullets → claims | anything outside the README |
| `--git` structure | `git ls-files` module map + file composition | file contents |
| `--git` history | commit count, range, authors, **last 15 commit subjects** | commit bodies, older commits |
| `--folder` | file tree, tool detection, first meaningful line of ≤40 text files ≤64 KB | full document text |

So the brain is a **summary index, not a full-text store**. A round's headline
reaches it through the commit subject and the research doc's title line; the
argument inside the doc does not. Retrieval is scoped accordingly, and a
ten-concept research question will correctly `no_match` rather than pretend.

> Note: the folder channel caps at 40 documents (`_MAX_DOC_FILES`).
> `docs/research` held 41 files on 2026-07-29 — one was dropped. If that
> directory grows a lot, either raise the cap or split the ingest, otherwise
> coverage silently stops tracking the directory.

## Abstention (the floor)

`retrieve()` returns **nothing** unless a page scores at or above
`FLOOR_SCORE = 20.0`, and reports `no_match` with the floor and the best
rejected candidates. It never returns the best of a bad lot. The calibration
table (measured in-domain vs off-domain scores, and the 12.0 → 21.9 separating
band it sits in) lives in the comment above `FLOOR_SCORE` in `core/query.py`.

Re-probe the floor if the corpus grows substantially or the term weights change:
run a handful of known-answerable and known-unanswerable queries, check the
bands still separate, and update the comment with the new numbers.

Callers may pass `floor=` (CLI `--floor`) to inspect near-misses. `no_match`
means *not in the brain* — the correct fallback is the live Aegis sources
(`aegis_canon`, `aegis_registry`, `aegis_verified_state`, `aegis_postmortems`),
not a lower floor.

## Domain scoping

Domains are declared in `core/domains.py` as a one-line-per-project registry
(`PROJECT_DOMAIN`), derived from a page's `project` slug. Nothing is stored in
the SQLite index — it is opened `mode=ro` by the MCP server and cannot run a
migration.

**Registering a new project is a one-line edit in `core/domains.py`.** An
unregistered project resolves to `unscoped`: demoted, never dropped.

| How `domain` is set | Behaviour |
|---|---|
| Passed explicitly (`brain_query(domain="finance")`, `--domain finance`) | **Hard scope.** Pages in other registered domains are removed from the candidate set. Related domains (`finance-ancestor` for `finance`), `core` identity/disposition pages, and `unscoped` pages are kept but demoted. |
| Omitted | **Soft scope.** The domain is inferred from distinctive query terms (`DOMAIN_MARKERS`). If confident, out-of-domain pages are demoted but never dropped; if unsure or tied, no scoping at all. |

Domain tier is the **first** sort key, so no out-of-scope or ancestor page can
out-rank an in-scope one whatever it scores. Measured on the live brain:
`"monte carlo prediction engine"` scores `market-prediction-engine-overview`
(a dead V5-era ancestor) at 52.0 and `aegis-finance-overview` at 31.5 — and
returns the live program first.

Markers are deliberately narrow: a word that plausibly belongs to two domains
("crash", "control", "signal", "model") is **not** a marker. Adding an ambiguous
one silently mis-scopes queries.
