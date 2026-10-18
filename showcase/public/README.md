# Optimus public showcase

Static architectural showcase for [Optimus](https://github.com/Murathanx12/Optimus). This directory is the versioned deployment source.

No backend, inference calls, tracking or private corpus. Build with the standard-library generator, then serve this directory with any static host. Vercel project identity stays in the ignored `.vercel/` directory.

The neural graph is a curated architecture of public source modules. It does not read the brain database or legacy export. Every neuron points to an existing source file; every edge carries a plain-language relationship. Aggregate collection receipts describe a checked 18 October 2026 run, not a public export of private source material.

`neural-map.svg` is a self-contained animated GitHub image. `neural-map.html` is a standalone interactive embed with inline data, CSS and JavaScript; it works inside an opaque-origin `sandbox="allow-scripts"` iframe. Neither fetches a private endpoint.

```powershell
.venv/Scripts/python.exe showcase/public/build.py
.venv/Scripts/python.exe showcase/public/build.py --check
.venv/Scripts/python.exe showcase/public/check.py
node showcase/public/verify.cjs
```

The browser verifier expects this directory served at `http://127.0.0.1:8895` (or set `SHOWCASE_URL`). It checks module selection, search including no-match, keyboard operation, zoom/pan/reset, route tracing, pause and reduced motion; it captures desktop, mobile, an opaque-origin sandbox embed, three GitHub-style SVG frames and a DejaVu font frame. Screenshots stay in ignored `validation/`.

Before publishing, verify link destinations and keep previous generated brain exports outside this deployment. The generated CSP permits external script only from this site, plus the exact hash of the standalone embed script; inline styles support the GitHub-safe SVG.
