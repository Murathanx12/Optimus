# Optimus Brain Viewer (read-only)

A localhost-only web UI that **visualizes** the Optimus brain — the web of memory,
colored by audit state. It is a *view*: it reads the existing brain and never
mutates it.

## Launch

```powershell
python -m ui.server
```

Defaults to `--root <repo root>`, port `8765`, and opens your browser at
`http://127.0.0.1:8765/`. Options:

```powershell
python -m ui.server --root . --port 8765 --no-browser
```

Stop with `Ctrl+C`.

## What it shows

1. **Graph** — nodes = brain pages, edges = the typed edges in the brain
   (`part_of`, `supersedes`, `contradicts`, `references`). **Shape encodes tier**
   (① Identity = star, ② Projects = circle, ③ Dispositions = hexagon,
   ④ Ephemeral = triangle). **Fill encodes audit state.**
2. **Audit overlay** — each node colored by its three-state audit result, the
   page aggregating its claims:
   - **green** VERIFIED — source reachable and still matches.
   - **red** DRIFTED — source reachable but the quote no longer matches → the
     brain believes something *wrong*. Loud. Filter with **“Only DRIFTED”**.
   - **grey** UNVERIFIABLE-HERE — source not reachable from this machine. Not
     wrong, just uncheckable; the last-known-good quote + `as of` date are shown.
   - dark — skipped / no claims.
3. **Node detail** — click a node to see its claims, each with kind
   (fact/raw/decision), text, **Why** (rationale) + verbatim **quote** for
   decisions, source span, audit state, and `as of` for unverifiable ones.
4. **Tombstones** — the ⚰ button lists deprecated entities (reason + date +
   aliases/pages). Deprecated *pages* render struck-through and dimmed in the graph.
5. **Search / filter** — alias-aware search (typing `aegis` finds the Aegis
   pages), plus tier, project, and audit-state filters.

Drag to pan · scroll to zoom · drag a node to move · click for detail.

## Read-only guarantees (enforced, not just intended)

- The brain is opened via `Store(root, read_only=True)`: an OS-level `mode=ro`
  SQLite handle. Every write method (`write_page`, `add_edge`, `write_tombstone`,
  `reindex`, …) raises `RuntimeError`; `log_event` no-ops so `audit()` can run.
- No write path exists in `ui/`. The HTTP server rejects POST/PUT/DELETE/PATCH.
- **No network calls.** Binds `127.0.0.1` only. The frontend is hand-rolled
  vanilla JS/SVG — zero external libraries, zero CDNs, zero telemetry. It works
  fully offline.

Verify the guarantees against your real brain (proves nothing is written, and
demonstrates drift→red on a throwaway copy):

```powershell
python -m ui.check_readonly
```

## Architecture

- `ui/server.py` — stdlib `http.server`, localhost-only, serves JSON + 3 static files.
- `ui/model.py` — pure read-only payload builders over `core.store.Store` +
  `core.audit` (tested in `tests/test_ui_model.py`).
- `ui/index.html`, `ui/app.js`, `ui/style.css` — the single-page frontend.

A future edit feature (v2) must route through `core.store.Store`, never direct
markdown/SQLite writes — and is explicitly **not** part of this surface.
