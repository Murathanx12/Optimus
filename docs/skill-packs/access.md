# Skill access

Call `task_skills()` for the domain names. Select one pack, then request one returned entry ID. For example, call `task_skills("cad", "guide:workflow")`. Follow `next_page` only when the first page lacks the needed entry. Entry IDs include the source label so a duplicate name cannot silently select a different implementation.

Optimus serves the maintained Markdown directly from each configured directory. The MCP is read-only. Associate a project's canonical skill directory with one or more packs in the private `brain/skill-access.json`. The format is a JSON object keyed by pack, with a source label and an absolute directory of skill folders inside each pack. Configure the active checkout from the project's handoff. A missing source is reported by label.

```json
{"cad":{"project":"/absolute/path/to/project/.claude/skills"}}
```

For mixed directories, use a source object with `directory` and `skills` keys. For example, `{"directory":"/absolute/path/to/skills","skills":["literature-review"]}` includes just that procedure. If a configured folder disappears or a named skill moves, the catalog returns its label under `missing_sources` or `missing_entries`. A named read includes the resolved path and SHA-256 digest for the exact bytes served.

For release checkouts that rotate, set a source's `release_receipt`, `checkout_parent` and `checkout_prefix`. Give the receipt and parent absolute local paths. On each request Optimus reads the receipt's `repo` and `generated_utc` and serves `.claude/skills` in the active checkout. The checkout must be a matching direct child of the configured parent. An unreadable receipt or a timestamp outside the last hour marks that source unavailable and gives the reason in `source_errors`. Other sources and guides in the pack stay accessible.

For continuity, save the dated state of a task in `brain/projects/task-<pack>/handoff.md` through the owner's existing editor. Record the source revision, last observable result, pending decision and next verification. A subsequent session can request this entry by name. Keep private handoffs out of the public repository.
