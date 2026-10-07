---
name: orbit-blackline-visuals
description: The owner's visual language for ANY project. Style C "orbit" draws a system as a loop of stages on a dotted ring, with a wave that dwells at each stage; use it for front pages and heroes. Style A "blackline" is a pure-black HUD of cards and hairlines with blue current in the wires; use it for explanation and architecture pages. The neural map applies C to a knowledge graph. Everything is animated SVG/HTML generated from data, pure black with white, blue for flow and gains, orange for learning; never PNG, never a white canvas. Use when asked for a visual, diagram, hero, landing or showcase page, brain map, README image, social card, or "make it look better".
---

# Orbit + blackline visuals (cross-project)

The owner chose this language on 2026-10-07. Four styles were shown side by side, each with the same
content, rendered as the viewer would see them. This file is self-contained: the tokens, motion and
rules below are enough to start in a new repo. Two working implementations exist (§7).

## 1. The verdicts, and what they rule out

| style | owner's verdict | use it for |
|---|---|---|
| **C: orbit** | stood out the most: "a spiral", not "the blocky structure everybody makes" | front page, README hero, landing page, social card. The page says *this is the system, and this part is running* |
| **A: blackline** | liked for "how the data is going through" | explanation pages, architecture, pipelines, flowcharts. The page says *this is how data moves* |
| **neural map** (C applied to a graph) | the brain page: "the neurons how they are connected and interact with each other" | knowledge graphs, memory maps, dependency maps |
| B: Swiss white | "too bright, too white" | never |
| D: glass terminal | "good but doesn't work with this project" | only if the owner asks |

Also rejected, so do not use:
- a navy or blue background. The owner asked for black and white with blue and orange highlights, "not blue background";
- raster renders committed to the repo (the first PNG pass was called awful);
- red or green numbers;
- a framing of "no improvement". Lead with the result and print what makes it honest beside it (§5.6).

"Visuals" means diagrams, graphs and motion design that make the system easier to read. It does
not mean pictures.

## 2. Tokens

### Colour (dark only; there is no light theme, by decision)

| token | value | meaning |
|---|---|---|
| `bg` | `#000000` | the canvas: pure black, never navy |
| `ink` | `#ffffff` | titles, wordmark, numbers that are facts |
| `ink-2` | `rgba(255,255,255,.62–.72)` | body text, descriptions |
| `ink-3` | `rgba(255,255,255,.40–.55)` | kickers, meta, ticks, footers |
| `hairline` | `rgba(255,255,255,.06–.22)` | rings, card frames, grid, wires |
| `blue` | `#4a8dff` | forward flow: the active stage, a live line, module names |
| `blue-hi` | `#6fb0ff` | gains and the swelling wave. The brightest thing on the page is a result |
| `orange` | `#ff8a1f` (highlight `#ffb36b`) | learning and asking: feedback paths, a LEARNING stage, a query replay |
| benchmark | `#ffffff`, dash `5 4` | the benchmark over the same window |
| control | white at 40% | a matched control (random twin, placebo) |

Use one accent per meaning. Red and green are never used. Print a negative number in white with a
true minus sign (`−`), never coloured as an alarm.

### Type (no webfont: an SVG inside GitHub's `<img>` cannot load one)

- Sans: `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif`.
  - Wordmark: 50–64 px, weight 200, tracking 16–22 px.
  - Stage titles: 14–15 px, weight 600, UPPERCASE, tracking 1.6 px.
  - Body: 13–17 px.
  - Big numbers: 34 px, weight 300.
- Mono: `ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace`.
  Used for kickers, labels, chips, ticks and module names: 10–12 px, UPPERCASE kickers, tracking 1.5–3.5 px.
- Budget widths for DejaVu Sans, the widest common fallback. Nothing is smaller than 10 px at full size.

### Geometry

- **Canvas:** 1200 px wide. GitHub scales it to roughly 0.7x in a README column.
- **Orbit:**
  - The stages sit evenly on a ring (9 stages, 40° apart, radius 232).
  - The stage that closes the loop (LEARNING) is at the crown (−90°), and the rest run clockwise.
  - Labels sit outside the ring: right-hand labels are anchored start, left-hand labels anchored end, the bottom pair below their bubble, the crown label above.
  - The inner learning orbits run at R−46 and R−76.
- **Blackline:**
  - A 3x3 serpentine grid (row 2 runs right to left), so every arrow is short and none crosses.
  - Cards are 350x216, with 12 px corner brackets and 1.5 px strokes.
  - A dot grid sits behind everything: 24 px pitch, 7% white.
- **Neural map:** positions are DECLARED, never simulated.
  - Rings by page type, from the centre out: self, structure, decisions/history, overview.
  - One equal sector per project, with the public projects at the top.
  - Neuron radius is about `4 + 1.35·√claims`.
  - Claims are beads at fixed slots on dendrites; parent links are curved axons.
  - The drawable radius is fitted to the frame so nothing clips.

## 3. Motion: every animation states one fact

| what moves | the fact | spec |
|---|---|---|
| dot wave (C) | the loop runs, stage by stage | the ring is ~120 dots. A wave swells each dot x2.7 and turns it `blue-hi`, then decays. 2.0 s per stage = 0.8 s travel (easeInOutCubic) + 1.2 s dwell, so 9 stages take 18 s. Each dot's delay is the inverse of the wave's position function, so speed varies with no JS |
| bubble + title + readout (C) | which stage is working now | on arrival the bubble scales 1 → 1.5 in 0.43 s, holds through the dwell and releases over 0.6 s. The title fills blue (orange for LEARNING), an underline grows `scaleX(0→1)`, and a centre readout names the stage |
| comets on the inner orbits (C) | what learning hands to the next cycle | SMIL `animateMotion`, `keyPoints="0;1;1"` over the cycle, launched when the wave reaches LEARNING |
| current in the wires (A) | data flows forward | dash `3 9`, offset −12 per second, linear. Linear easing is reserved for continuous flow |
| card highlight (A) | the stage being explained | one card's frame is lit blue at a time, for 8% of a 9 s cycle (orange for LEARNING) |
| pulses on edges (neural map) | facts feed pages, pages feed overviews | blue pulses run along REAL edges, one project at a time; the reached neuron swells and fills blue |
| query replay (neural map) | what a real question retrieves | orange: a real logged query enters from the top edge and lights the returned pages in rank order, with their scores |
| charts | the number arriving | bars grow once (1.4 s, spline `0.2 0.8 0.2 1`); lines are revealed by a clip (2.6 s) so dashes survive; the latest point pulses (r 4 → 16, 2 s) |

`@media (prefers-reduced-motion: reduce)` turns every CSS animation off. The static frame must be
complete on its own: dots at rest, labels at full strength, the chart drawn, the first readout shown.
HTML pages also get a Pause control. If you cannot say what an animation means in one sentence, delete it.

## 4. Components

1. **Stage table** (the data behind C and A): number, title, two description lines of at most 40
   characters, and the modules that run the stage. A test fails when a printed path stops existing or a
   printed function stops being defined, so the picture cannot drift from the code.
2. **Orbit hero** (C), **blackline pipeline** (A), **blackline flowchart** (A: any Mermaid flowchart,
   redrawn node for node and word for word).
3. **Results panel** (C):
   - the headline number (big, `blue-hi`);
   - its evidence label (e.g. `OBSERVED(n)`);
   - the benchmark over the same window;
   - the matched control;
   - the selection rule, as code, with its denominator printed.
4. **Social card** (C, static) and an **HTML twin** of the hero. The twin inlines the SVG with every
   id prefixed, uses count-up numbers, and loads nothing external.
5. **Neural map** (C on a graph), plus a detail panel, legend and controls kept OUTSIDE the map.

## 5. Procedure

1. **Data first.** Every element traces to a field: a table drives the picture, numbers come from a
   pinned snapshot or receipt id, and nothing is decorative. Use rings and declared grids, never a
   force simulation (one jitters forever and clips at the edges).
2. **Generate, don't draw.**
   - A stdlib Python generator writes the SVG and the HTML twin deterministically: no clock, no
     randomness, LF endings, rounded coordinates.
   - A test reproduces the committed bytes, and `--check` exits non-zero when an output is stale.
3. **Colour by meaning** (§2). Ask "what does this colour mean?" for every fill.
4. **Motion with meaning** (§3).
5. **GitHub-safe SVG** for anything a README shows:
   - none of: script, `foreignObject`, `use`, an external font or image;
   - only `#fragment` hrefs;
   - CSS keyframes and SMIL only.

   An HTML page may run inline JS but loads nothing external (no CDN, no webfont).
6. **Results first, honestly.** Lead with the result. Beside it, print the evidence label, the
   benchmark, the control, and the selection rule with its denominator. Do not lead with a disclaimer
   and do not hide the denominator.
7. **Verify by looking.**
   - Use headless Chromium through Playwright, with the SVG inside an `<img>` as GitHub shows it.
   - Capture three moments of the cycle plus one frame with the font forced to DejaVu Sans.
   - For HTML, check desktop and mobile widths.
   - In a Claude cloud container, launch the preinstalled Chromium with `executable_path` (under
     `PLAYWRIGHT_BROWSERS_PATH`); never `playwright install`.
8. **Gallery before a new style.** Show 3–4 options side by side, then build the chosen one.
9. **No PNG in git.** Where a raster is required (a GitHub social preview, slides), export it locally
   and upload it; never commit it.

## 6. Before showing anyone

- [ ] Every number equals its source (a test compares them).
- [ ] Every printed path or function exists (a test checks).
- [ ] Re-rendering produces identical bytes; `--check` is clean.
- [ ] The reduced-motion frame is complete.
- [ ] The DejaVu frame does not overflow.
- [ ] The page has no red, no green and no navy, and loads nothing external.

## 7. Working implementations (copy from these)

- `Murathanx12/Aegis-Finance`:
  - `scripts/render_public_assets.py`: orbit hero, blackline pipeline and gauntlet, results panel,
    social card, HTML front page.
  - `backend/tests/test_public_assets.py`: the byte-for-byte, receipt-equality, path-existence and
    wave-clock tests.
  - The full design record, with every owner remark mapped to what was built:
    `docs/design/AEGIS_VISUAL_LANGUAGE_2026-10-07.md`.
  - The repo-specific skill: `.claude/skills/aegis-motion-visuals/`.
- This repo:
  - `showcase/build.py`: the neural map (`MAP_RINGS`, `map_layout`, `render_html`, and `--from-json`
    to re-render from a snapshot).
  - `tests/test_showcase.py`.

## 8. Tools: what built this, and when another is better

Used:
- a stdlib generator;
- CSS keyframes and SMIL;
- headless Chromium through Playwright for screenshots;
- an HTML gallery embedding each style as a `data:` URI, so the comparison matched what viewers see.

| tool | the better choice when |
|---|---|
| Figma MCP (`generate_diagram`, `use_figma`) | a designer wants to adjust the layout by hand before it is coded; export SVG back into the generator's tokens |
| p5.js / p5.brush | a generative, always-moving backdrop for a portfolio piece; never for a number |
| GSAP / Framer Motion | the page lives in a React app (scroll-linked reveals, hover states); not usable in a README |
| D3 (`d3-shape`, `d3-scale`) | live data on a website: real axes, transitions between snapshots |
| Lottie / Rive | a designer-authored animation that must play identically in an app and on mobile |
| Remotion | turning the orbit into a short video for social posts |
| Canva / Gamma | slides and one-pagers that reuse these tokens |
