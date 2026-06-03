# examples/

`examples/brain/` is a **synthetic** brain produced by `build_example.py`. It
exists so the public engine repo can demonstrate the page layout and
front-matter schema without exposing any real memory.

The real `brain/`, `raw/`, and `reports/` at the repo root are gitignored — the
engine is open-source, the brain content is private. They never share git
history. See `.gitignore` (the privacy boundary).

Regenerate the example after a schema change:

```
python examples/build_example.py
```
