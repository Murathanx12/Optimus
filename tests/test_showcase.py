"""showcase/build.py — the public brain page, rendered from brain.json alone.

``python showcase/build.py --from-json`` re-renders index.html from the
committed snapshot without the brain DB, so none of these tests needs one.
They pin what the page promises:

- the render is a pure function: two renders are byte-identical;
- the page loads nothing from anywhere (no CDN, no webfont, no remote script);
- the committed index.html IS the render of the committed brain.json, so a
  stale page fails here instead of in front of a visitor;
- the map is the declared taxonomy (rings by type, sectors by project), never
  a layout pass, and private pages stay anonymous on the page;
- every module path the page prints exists.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "showcase" / "optimus-brain"
BRAIN_JSON = SNAPSHOT / "brain.json"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "showcase_build", ROOT / "showcase" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(BRAIN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page(build) -> str:
    return build.render_from_json(BRAIN_JSON)


def _embedded_data(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="brain-data">(.*?)</script>',
                  page, re.S)
    assert m, "the page carries its data in one inline JSON block"
    return json.loads(m.group(1))


def test_render_from_json_is_deterministic(build, page):
    assert build.render_from_json(BRAIN_JSON) == page


def test_committed_index_is_the_render_of_the_committed_snapshot(page):
    # line endings normalised: git may check index.html out with CRLF on Windows
    committed = (SNAPSHOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == page, (
        "showcase/optimus-brain/index.html is stale: run "
        "`python showcase/build.py --from-json` and commit the result")


def test_page_loads_nothing_external(page):
    assert not re.search(r"<script\b[^>]*\bsrc\s*=", page, re.I)
    assert not re.search(r"<link\b", page, re.I)          # no stylesheet, font, preconnect
    assert not re.search(r"<(?:iframe|img|video|audio|object|embed|source)\b", page, re.I)
    assert not re.search(r"@import|@font-face", page, re.I)
    assert not re.search(r"""url\(\s*["']?\s*(?:https?:)?//""", page, re.I)
    assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|\bimport\s*\(|new\s+WebSocket", page)
    # no attribute points off the page at all (the curl example is text, not a link)
    external = re.findall(
        r"""\b(?:src|href|xlink:href|action|poster|srcset)\s*=\s*["']?\s*((?:https?:)?//[^"'\s>]*)""",
        page, re.I)
    assert external == []
    assert len(re.findall(r"<script\b", page)) == 2      # the data block + the inline script


def test_page_keeps_every_section(page, snapshot):
    for section in ("The brain, mapped", "How it digests information",
                    "Corpus at a glance", "Retrieval, demonstrated",
                    "Public knowledge pages", "For AI agents"):
        assert section in page
    for p in snapshot["public_pages"]:
        assert f'id="page-{p["id"]}"' in page
        assert f'href="pages/{p["id"]}.md"' in page
    for op in snapshot["stats"]["events_by_op"]:
        assert f'<span class="op">{op} ' in page
    for d in snapshot["retrieval_demos"]:
        assert d["query"] in page
    assert "/brain.json" in page and "/llms.txt" in page


def test_reduced_motion_is_honoured(page):
    assert "@media (prefers-reduced-motion: reduce)" in page
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in page


def test_layout_is_the_declared_taxonomy(build, snapshot):
    graph = snapshot["graph"]
    layout = build.map_layout(graph)
    assert build.map_layout(graph) == layout                  # a pure function
    pages = [n for n in graph["nodes"] if n.get("kind", "page") == "page"]
    assert set(layout["pages"]) == {p["id"] for p in pages}   # every page, nothing invented

    ring_of = {t: i for i, ring in enumerate(build.MAP_RINGS) for t in ring["types"]}
    fallback = next(i for i, ring in enumerate(build.MAP_RINGS)
                    if ring["key"] == build.MAP_FALLBACK_RING)
    step = 360.0 / len(layout["sectors"])
    for p in pages:
        spot = layout["pages"][p["id"]]
        assert spot["ring"] == ring_of.get(p["type"], fallback)
        assert spot["r"] == build.MAP_RINGS[spot["ring"]]["r"] < 1
        if spot["sector"] is not None:                       # bearing = the project's sector
            sector = layout["sectors"][spot["sector"]]
            assert sector["key"] == (p["project"] or "")
            gap = abs((spot["a"] - sector["a"] + 180) % 360 - 180)
            assert gap <= build.MAP_SECTOR_SPREAD * step / 2 + 1e-9
    spots = {(s["r"], round(s["a"] % 360, 3)) for s in layout["pages"].values()}
    assert len(spots) == len(pages)                           # no two pages share a spot

    keys = [s["key"] for s in layout["sectors"]]
    public = [k for k in build.PUBLIC_PROJECTS if k in keys]
    assert keys[:len(public)] == public                       # public lobes first, at the top
    assert all(s["public"] == (s["key"] in build.PUBLIC_PROJECTS) for s in layout["sectors"])


def test_private_pages_stay_anonymous_on_the_page(page, snapshot):
    data = _embedded_data(page)
    assert data["graph"] == snapshot["graph"]     # the page exports nothing brain.json does not
    for n in data["graph"]["nodes"]:
        if n["public"]:
            continue
        assert n.get("title") is None and n.get("text") is None
        if n.get("kind", "page") == "page":
            assert re.fullmatch(r"private-\d+", n["id"])
            assert n["project"] is None or re.fullmatch(r"private project \d+", n["project"])
    for s in data["layout"]["sectors"]:
        if not s["public"]:
            assert re.fullmatch(r"PRIVATE PROJECT \d+|NO PROJECT", s["label"])
    for d in data["demos"]:
        for r in d["results"]:
            assert r["public"] or r["page_id"] is None


def test_a_private_retrieval_hit_never_prints_its_id(build, snapshot):
    demos = [{"query": "who is behind this", "results": [
        {"page_id": "personal-diary-overview", "title": "Diary — Overview",
         "type": "overview", "project": "personal-diary", "score": 51.0,
         "public": False}]}]
    html_text = build.render_html(snapshot["stats"], snapshot["public_pages"], demos,
                                  snapshot["graph"], snapshot["brain_commit"],
                                  snapshot["built_at"])
    for leak in ("personal-diary-overview", "Diary — Overview", "personal-diary"):
        assert leak not in html_text
    assert "private page" in html_text


def test_every_module_the_page_names_exists(build):
    for _title, _text, module, _is_query in build.PIPELINE:
        assert (ROOT / module).is_file(), module
    server = (ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
    assert re.search(r"^def brain_query\(", server, re.M)   # the tool the Serve card names


def test_from_json_writes_only_index_and_never_opens_the_brain(build, tmp_path, monkeypatch):
    src = tmp_path / "snapshot.json"
    src.write_text(BRAIN_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(build, "OUT", out)

    def refuse(*_a, **_k):
        raise AssertionError("--from-json must not open the brain DB")

    monkeypatch.setattr(build, "Store", refuse)
    build.main(["--from-json", str(src)])
    assert sorted(p.name for p in out.iterdir()) == ["index.html"]
    assert (out / "index.html").read_text(encoding="utf-8") == build.render_from_json(src)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_inline_script_parses(page, tmp_path):
    # a syntax error would leave a blank map behind an otherwise healthy page
    script = re.findall(r"<script>(.*?)</script>", page, re.S)[-1]
    js = tmp_path / "map.js"
    js.write_text(script, encoding="utf-8")
    res = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True,
                         timeout=60)
    assert res.returncode == 0, res.stderr
