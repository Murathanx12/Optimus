# Optimus — Architecture

Status: **alpha, Phase 1.** Laptop-only, ~$0, deterministic core (no LLM wired in
any path). Updated at session boundaries.

Optimus is a personal context layer over cloud Claude: plaintext markdown is the
source of truth, SQLite is a *derived, rebuildable* index. The product goal is
specificity, not intelligence — start every Claude surface already knowing the
context instead of re-explaining it.

## The load-bearing principle

**Markdown = truth. SQLite = derived index.** Every write hits markdown first,
then upserts the index. Throw the index away and `Store.reindex()` rebuilds it
from the `.md` files — *including claims and their deprecation status*, which is
the one piece of state that exists in no source and must therefore live in
markdown. This is what lets the corpus survive Optimus being abandoned.

## Data flow

```
git repo ──ingest_git──▶ brain/projects/<slug>/*.md ──upsert──▶ brain/index.db
                              ▲ (source of truth)         (pages, aliases, claims,
                              │                             edges, tombstones, events)
query "what is aegis" ──retrieve()(no LLM)──────────────────────▶ ranked, cited pages
deprecate "buzzer" ──strike body + flag claims + tombstone──▶ (all persisted to .md)
```

## Memory tiers (different decay / edit rules)

| Tier | Contents | Edit rule |
|---|---|---|
| 1 Identity | who the owner is | manual approval only |
| 2 Projects | project state, decisions, patterns | auto, volatile |
| 3 Dispositions | how they decide / communicate | auto, **observed > stated** |
| 4 Ephemeral | task-scoped | auto-expire |

## Data model

**Page** — YAML front-matter + markdown body. Fixed key order for clean diffs:
`id, title, tier, type, project, aliases, tags, sources, status, created,
updated, claims`. `id` is the immutable machine key; `title` is the display
string (e.g. README H1). `aliases` resolve human strings → page. Round-trips
losslessly through markdown.

**Claim** — atomic, provenance-carrying statement, stored in its page's
front-matter: `{id, text, source, status}` (tier/page_id/created derived from the
page on load). Status (`active` / `deprecated` / `flagged`) is what makes
deprecate's output survive a reindex.

**Provenance grammar:** `git:<repo>@<sha7>:<path>#L<a>-L<b>` — every claim traces
to a commit + line range. Generalizes to other channels (`raw:notes/x.md#L3`).

**Six derived SQLite tables:** `pages`, `aliases`, `edges`, `claims`,
`tombstones`, `events`. All rebuildable from markdown except `edges` (see Gaps).

## Operations

### ingest (git channel) — deterministic, no LLM
- Source = `git ls-files` (tracked files only) → `.gitignore` excludes secrets,
  virtualenvs, caches for free.
- Emits 3 Tier-2 pages per project: `<slug>-overview` (title, description,
  capabilities, sections), `<slug>-structure` (module map + file composition),
  `<slug>-history` (commits, range, contributors). Capability bullets become
  line-cited claims on the overview. Edges: structure/history `part_of` overview.
- **Tombstone-aware (step 4):** a claim mentioning a tombstoned entity is held in
  `flagged` (not active, never silently revived); the rest ingests normally.

### query — deterministic, LLM-free, snapshot-tested
Aliases set the **project scope**; intent keywords pick the **page within** it.
Scoring (tie-broken by page id): `+50` type matches intent, `+30` overview when
no intent but project scoped, `+20` in scoped project, `+15` directly named,
`+5`/term in title, `+2`/term in an **active** claim (deprecated/flagged claims
have weight 0). Unknown queries return nothing. Synthesis (LLM) is deferred
behind the `core.llm` seam; retrieval never calls the model.

### deprecate — fact removal with propagation (the differentiator)
Resolve entity through the alias graph → find every referencing body line + claim
→ stage strike-through diffs → on confirm (y/N/review) atomically: strike the
markdown lines (+ why/when note), set matching claims `deprecated`, deprecate any
page that *is* the entity, write a tombstone (markdown + index). Claim status is
edited on the page and persisted via `write_page`, so it lands in markdown and
survives reindex. Rolls back every page (restoring claims with it) if any write
fails. Whole-word alias matching only — no stemming; `--alias` is the explicit,
auditable recall lever (a false strike corrupts a true fact; a miss is
recoverable).

## The LLM seam (`core/llm.py`)
`Completer` protocol + `NotConfiguredCompleter` (default, raises) +
`StaticCompleter` (test double). The deterministic core must never call it; the
real model enters only at `distill` and query-synthesis, behind this seam, tested
with fixtures. A test hard-asserts retrieval is LLM-free.

## Privacy boundary
The engine is open-source; the brain content is private. `/brain`, `/raw`,
`/reports` are gitignored (root-anchored, so `examples/brain/` — synthetic —
still ships). The owner's identity/disposition seeds live in gitignored
`brain/identity/` and `brain/dispositions/`, not in this repo. `tools/backup_brain.py`
snapshots the brain off-machine. Forkers get the same boundary.

## Gaps / not yet built
- **Edges aren't persisted to markdown** → `reindex()` drops them (same class as
  the now-fixed claims gap, lower priority; no current feature depends on edges).
- **Property test (deprecate step 5)** — `ingest→ingest→deprecate→ingest` never
  silently revives — pending (its own session, against the now-stable model).
- **Not built:** `distill` (first LLM op), MCP server, daemon, router, lint, audit.
- **Unproven:** Tier 2-vs-3 boundary (only Tier 2 exercised so far).

## CLI
```
python optimus.py ingest --git <path|url> [--project <slug>]
python optimus.py query "what is Aegis" [-k 3]
python optimus.py deprecate "buzzer" --reason "removed" [--alias piezo] [--dry-run] [--yes]
python tools/backup_brain.py --dest "<off-machine path>"
```
