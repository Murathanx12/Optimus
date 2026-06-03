# OPTIMUS — Build Brief for Claude Code

> Owner: Murathan Abdullaev (Murat).
> Status: greenfield. This file is the entry point. Read it fully before writing code.
> Predecessor specs (if present in repo): `OPTIMUS.md` (operating contract) and `OPTIMUS_PHASE1_SCOPE.md` (10-phase roadmap). If they exist, they are canonical and this brief defers to them. If they don't, this brief is self-contained enough to start.

---

## 0. Read this first — what you're building and what you are not

Optimus is a **personal context layer + tool router** that wraps cloud Claude with persistent, plaintext, portable memory. It makes every Claude session — chat, Claude Code, desktop — start already knowing who Murat is, what he's working on, what he's tried, and what he's about to repeat.

Optimus is **not** a language model. Cloud Claude is the brain's reasoning engine. Optimus is the layer between Murat and his tools that supplies context and routes requests.

The product test: when Murat opens any Claude surface, he never re-explains context, restates preferences, or repeats a past decision. The brain already loaded it.

The architectural test: every byte of memory is plaintext markdown + a derived SQLite index. If Anthropic disappears, the brain still reads in any markdown editor. If Optimus is abandoned, the corpus survives. **The storage is the export.**

---

## 1. The mission, expanded (what Murat asked for, current)

Three concrete capabilities define done:

1. **Track every conversation.** Like Claude/GPT memory, but owned and plaintext. Ingest Claude chat exports, Claude Code session transcripts, and any pasted conversation, distill them into durable memory (decisions, preferences, project state, dispositions), and discard the noise.
2. **Know every project.** Ingest across all of the owner's work — from a **git remote** or a **local folder** — and build per-project memory plus a cross-project view. The concrete project/affiliation list is private; it lives in `brain/identity/identity-seed.md` (Tier 1), not in this public brief.
3. **Know Murat.** Hold a stable model of how he communicates, how he decides, and what he's built — so the brain's outputs sound like the answer he'd give himself six months from now.

Optimus is not trying to be smart. It's trying to be **specific**.

---

## 2. What changed in the platform since the original design (use these)

The original design predates Opus 4.8 and the current Claude Code. Three platform changes materially affect the architecture — fold them in:

- **Mid-conversation system entries + no prompt-cache break.** The Messages API now accepts system entries inside the `messages` array, and updating instructions mid-task no longer busts the cache. This makes **live memory injection cheap.** The proactive observer and the live-contradiction surfacing can fire mid-session without re-priming the whole context. Design the brain-injection path around this rather than around full-prompt re-priming.
- **MCP is the surface-agnostic spine.** Expose Optimus as an MCP server. Claude Code, Desktop, and chat all read/write the *same* store through it. Never duplicate memory per surface.
- **Dynamic Workflows (parallel subagents) exist now.** Before building a bespoke orchestration layer for ingest, check whether the platform's workflow/subagent orchestration covers the fan-out (e.g. one subagent per project during bulk ingest). Don't reinvent it. Keep Optimus focused on the memory + disposition layer, which nothing else provides.

---

## 3. Who the brain serves (the identity seed)

The Tier-1 identity seed and the Tier-3 disposition seed are **private**. They are
the exact content the privacy boundary exists to protect, so they do **not** live
in this public engineering brief — they live in the brain and load at runtime:

- `brain/identity/identity-seed.md` — Tier 1: builder profile, active projects, environment. Durable; edits require Murat's explicit approval (see §6.2).
- `brain/dispositions/communication-seed.md` — Tier 3: how he communicates and decides (direct/low-fluff, systems-thinker, critic-by-default, …). Auto-updates, but observed > stated.

Both are gitignored (`/brain/` — see §4.2 and `.gitignore`). This brief is the
engineering contract for the open-source engine; the owner's personal model is
supplied from the brain, never committed here. When working in-repo, read those
two pages first if present — they are the operative identity/disposition context.

---

## 4. Architecture

### 4.1 Storage
- **Markdown is source-of-truth. SQLite is a derived index.** If SQLite corrupts, rebuild it from markdown. Never the reverse.
- Per project: a `brain/` directory of markdown pages + `index.db`. A top-level `optimus/` holds the cross-project layer and global identity/disposition tiers.

### 4.2 Repo layout (target)
```
optimus/
├── CLAUDE.md                  ← this file
├── OPTIMUS.md                 ← operating contract (canonical, if present)
├── core/                      ← the engine
│   ├── ingest.py  query.py  distill.py  lint.py  audit.py  deprecate.py
│   ├── router.py              ← request classifier → tool/route
│   └── store.py               ← markdown + SQLite read/write
├── mcp/                       ← Optimus exposed as an MCP server
├── daemon/                    ← watcher that tails git commits, session logs, file edits
├── brain/
│   ├── identity/              ← Tier 1 (manual-approval edits)
│   ├── dispositions/          ← Tier 3 (how he decides/communicates)
│   ├── projects/<name>/       ← Tier 2 (per-project, volatile)
│   ├── conversations/         ← distilled conversation memory
│   └── index.db
├── raw/                       ← intake: dropped exports, transcripts, notes, before distillation
└── reports/                   ← lint/audit/"what changed" daily diffs
```

### 4.3 Memory tiers (different decay rates — this is load-bearing)
| Tier | Contents | Decay | Edit rule |
|---|---|---|---|
| 1 Identity | who he is, permanent facts | none | **manual approval only** |
| 2 Projects | project state, decisions, code patterns | volatile | auto-update from ingest/distill |
| 3 Dispositions | how he decides, communicates, what he rejects | slow | auto-update, but **observed > stated** |
| 4 Ephemeral | task-scoped, transient | disposable | auto-expire |

Rule: **observed behavior outranks stated preference.** If he says "I prefer X" but rejects X five times in review, the rejection wins and the disposition page updates.

### 4.4 The six operations
| Operation | Trigger | Writes |
|---|---|---|
| `ingest` | new file in `raw/`, git/folder source, or `optimus ingest <path>` | new/updated brain pages, event log, SQLite |
| `query` | `optimus query "..."` or MCP request | relevant pages; a synthesis page if the answer is novel |
| `distill` | end of a Claude Code session, or on a conversation transcript | decisions, patterns, project-state + disposition updates |
| `lint` | weekly / `optimus lint` | report only, no auto-fix |
| `audit` | monthly / `optimus audit` | report only, no auto-fix |
| `deprecate` | `optimus deprecate "<entity>"` or MCP request | tombstone + every referencing page marked deprecated |

### 4.5 `deprecate` — the operation that makes this more than a wiki (the "buzzer fix")
The motivating bug: a hardware component (a buzzer) was removed from a project, but references to it persisted across multiple docs and pages and kept resurfacing. `deprecate` fixes that class of problem:
1. Resolve aliases → canonical entity + all aliases.
2. Find every referencing page (edges, prose mentions of any alias, tagged claims).
3. Stage a diff per page marking the claim deprecated (strike-through + why/when note).
4. Write a tombstone (timestamp + rationale) and **hard-block silent re-ingestion** of the dead fact.

### 4.6 Router + daemon
- **Router:** a small/cheap classifier (1B-class local model or a fast cheap call) decides route — Python eval for calculation, ingest pipeline for a PDF, project-state load + Claude Code for "continue project X." Cloud Claude should not be deciding "is this a calc or a search" — too slow, too expensive.
- **Daemon:** tails git commits, Claude Code session logs, and file edits; updates memory without being asked. Pi-capable later, laptop for now.

### 4.7 Provenance + trust
- Every claim carries a source-span citation in front-matter (`sources: [raw/...#L42-L51]`).
- A daily **"what changed"** diff in `reports/` — what was added, modified, deprecated. This is how trust is maintained; without it, errors surface months later with no origin.
- **Failure-mode log:** every time the brain is wrong (he corrects it, rejects a flag, deletes a memory), log why. After ~100 entries that's a dataset for improving Optimus without retraining.

---

## 5. Ingest sources (Murat's two new requirements, concrete)

The intake (`raw/`) accepts four channels. All flow through `ingest` → `distill`:

1. **Git repos.** `optimus ingest --git <url|local-path>` — clone/read, parse README + code structure + commit history into a project page set. Code patterns and architecture decisions become Tier-2 memory.
2. **Local folders.** `optimus ingest --folder <path>` — same pipeline for non-git project folders (3D art assets, notes, course material).
3. **Conversation exports.** `optimus ingest --conversations <export.json|dir>` — parse Claude/ChatGPT conversation exports; distill durable memory, drop noise. This is the "track every conversation" requirement.
4. **Session transcripts.** Auto, via the daemon, at the end of each Claude Code session → `distill`.

Each ingested item gets provenance back to its source so any claim is traceable.

---

## 6. Build discipline — guardrails you must hold

These existed in the original contract for good reason. Do not relax them without Murat's explicit say-so:

1. **Staged ingest, not all-at-once.** Prove the shell on **one** project end-to-end (Aegis Finance — highest-quality corpus) before bulk-ingesting the rest. Phase N+1 doesn't start until Phase N passes its audit. Murat's instinct is "ingest everything now"; the staged path is lower-risk. If he overrides, write the big-bang version, but flag the risk first.
2. **Identity tier is manual-approval.** The brain may *propose* identity edits; it may not commit them autonomously. This is the rail against drift.
3. **Intervention cap (no-Clippy guarantee).** The proactive observer is capped at ~2 unprompted interventions per session. Surface contradictions live, but don't nag.
4. **No auto-fixes from lint/audit.** They report. Murat decides.
5. **Schema-first.** Get the front-matter schema and tier boundaries right before scaling ingest. Wrong tier boundaries are the most expensive early mistake.

---

## 7. Phase 1 scope + Session 1 plan

**Phase 1 = the per-project memory shell, single project, laptop-only, ~$0 infra.** Visualizer, cross-project linking, voice, and server/remote architecture are Phase 2+ — out of scope now.

Phase 1 acceptance: ingest Aegis Finance from git → brain pages with provenance → `query` returns correct project context → `distill` on a session transcript updates project state → `deprecate` cleanly removes a test entity across all references → MCP server lets Claude Code load that context on session start.

**Session 1 (do only these — 2–3 tasks, then stop and report):**
1. Scaffold the repo per §4.2. Set up Python env, `store.py` (markdown + SQLite read/write), and the front-matter schema + SQLite tables (`pages`, `edges`, `aliases`, `claims`, `tombstones`, `events`).
2. Implement `ingest` for the **git** channel only. Point it at the Aegis Finance repo. Produce brain pages for the project with source-span provenance.
3. Write tests for the schema and the git-ingest path, and a short `reports/SESSION1.md` "what changed" summary. Stop. Do not start `query`, the daemon, or MCP yet.

Report back what the schema looks like in practice and whether the tier boundaries hold against real Aegis content before continuing.

---

## 8. Tech stack
- Python 3.11+. SQLite (stdlib). Markdown with YAML front-matter.
- Anthropic API for distillation/synthesis; a small local model (or cheap fast call) for the router classifier.
- MCP server via the official MCP Python SDK.
- No Postgres, no cloud DB, no proprietary store in Phase 1. Laptop-only.
- Windows/PowerShell — `;` for sequential commands.

---

## 9. Sources from the ideation phase (draw on these, don't re-derive)
- **Karpathy LLM Wiki pattern** — the plaintext-page storage primitive. Optimus's brain is this, plus typed edges, tiers, and `deprecate`.
- **Agent-memory frameworks** — Mem0, Zep, Letta, Cognee, OMEGA. Study their retrieval and decay handling; none combine plaintext-portable + MCP-native + disposition layer + deprecate, which is Optimus's differentiated thesis.
- **Microsoft JARVIS (2023)** — LLM-as-controller + expert executors. The router concept. MCP is the piece that paper lacked.
- **Reference implementations** — NicholasSpisak/second-brain, Sage-Wiki, Thinking-MCP, ELF — for prior art on LLM-maintained knowledge graphs.

What no one else builds, and Optimus must: plaintext-portable memory, MCP-native surface-agnosticism, a disposition layer (how he decides, not just what he knows), span-level provenance, and `deprecate` that propagates fact removal across all references.

---

## 10. Out of scope for now (defer, don't build)
Graph visualizer · cross-project linking UI · voice input · server/remote architecture · the full identity/personality layer · any always-on hosted deployment. Phase 2+.

---

## 11. The non-goal that matters most
A general assistant gives generic answers wrapped in Murat's name. Optimus gives the answer *he* would have given himself, later, with everything he's learned by then. Build for specificity, not intelligence. Hold that.
