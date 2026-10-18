# Optimus: restore the neural map

The source of this direction is `.claude/skills/orbit-blackline-visuals/SKILL.md`, the owner's selected design record of 7 October 2026, and the declared polar neural geometry in `showcase/build.py`.

- Canvas `#000000`; ink `#ffffff`; secondary ink `#b5b5b5`; forward flow `#4a8dff` / `#6fb0ff`; retrieval and learning `#ff8a1f`. No navy, white canvas, green or red.
- Type: the original light, spaced system-sans wordmark with monospace coordinates and controls. No external font dependency.
- Layout: the neural map leads. Four declared sectors describe capture, memory, retrieval and learning; a side instrument gives the selected module's purpose, source and connections.
- Motion: pulses travel along curated architecture edges. Orange traces an explicitly illustrative retrieval route, not a real recorded query. Declared neuron positions never jitter. Visitors may drag them locally; reset restores the declared layout. Pause and reduced motion show the complete network.
- Public boundary: this graph documents public source modules. It contains no personal knowledge pages, private corpus identifiers, chat text or account/browser state. The legacy brain export is neither read nor deployed.

`build.py` generates `index.html`, `architecture.json` and `neural-map.svg` deterministically. `--check` rejects stale output. The SVG works in GitHub image embeds. HTML adds selection, search, keyboard navigation, zoom, direct neuron drag, expanded drag-to-pan and a stepped retrieval walkthrough. Curved wires terminate outside neuron membranes and avoid unrelated somas; black text halos preserve labels. Dragging updates connected wires without triggering selection. The public map never automatically zooms to a selected neuron.

The walkthrough explains four source-backed stages and provides manual Next step navigation, including under reduced motion. It never calls a private memory or model endpoint. Local review concepts live in ignored `validation/concepts.html`; focus framing is an unshipped alternative.
