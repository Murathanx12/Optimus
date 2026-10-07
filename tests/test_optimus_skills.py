"""Optimus's own skill root: cross-project skills served by `aegis_skills`.

2026-10-07: the owner asked for the visual language chosen that day to be kept
"in Optimus" for future projects. Every existing skill root was another
checkout's (aegis, terminal) or one machine's (~/.claude/skills), so a skill
that belongs to no single project had nowhere to live. These tests pin the new
root, its precedence (generic skills lose to a project's own), and the skills
committed to it. The file checks run without the MCP SDK; the serving checks
skip where the SDK is absent, like tests/test_mcp_server_helpers.py.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"
sys.path.insert(0, str(ROOT))

#: A backticked path into THIS repo; paths into other repos are not checked here.
_LOCAL_PATH = re.compile(r"`((?:showcase|tests|mcp|core|tools|ui)/[\w./-]+)`")


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must open with a --- frontmatter block"
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            out[key.strip()] = value.strip()
    return out


def _skill_dirs() -> list[Path]:
    return sorted(d for d in SKILLS.iterdir() if d.is_dir() and d.name != "__pycache__")


def test_every_optimus_skill_names_itself_and_says_when_to_use_it() -> None:
    dirs = _skill_dirs()
    assert dirs, f"no skills under {SKILLS}"
    for d in dirs:
        f = d / "SKILL.md"
        assert f.exists(), f"{d.name}: no SKILL.md"
        fm = _frontmatter(f.read_text(encoding="utf-8"))
        assert fm.get("name") == d.name, f"{d.name}: frontmatter name is {fm.get('name')!r}"
        assert len(fm.get("description", "")) >= 80, f"{d.name}: description too thin to route on"


def test_every_path_a_skill_names_in_this_repo_exists() -> None:
    for d in _skill_dirs():
        for rel in _LOCAL_PATH.findall((d / "SKILL.md").read_text(encoding="utf-8")):
            assert (ROOT / rel).exists(), f"{d.name} names {rel}, which does not exist"


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("mcp.server.fastmcp")
    spec = importlib.util.spec_from_file_location(
        "optimus_mcp_server_skills_under_test", ROOT / "mcp" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_optimus_root_is_this_repo_and_comes_last(server) -> None:
    labels = [label for label, _ in server.SKILL_ROOTS]
    assert labels[-1] == "optimus", labels
    assert dict(server.SKILL_ROOTS)["optimus"].resolve() == SKILLS.resolve()


def test_an_optimus_skill_is_served_by_root_and_by_bare_name(server, monkeypatch) -> None:
    # Isolated from whatever aegis/terminal/user roots exist on this machine.
    monkeypatch.setattr(server, "SKILL_ROOTS",
                        (("aegis", ROOT / "no-such-root"), ("optimus", SKILLS)))
    full = server.aegis_skills("optimus:orbit-blackline-visuals")
    assert full.startswith("# orbit-blackline-visuals  [root: optimus]")
    assert server.aegis_skills("orbit-blackline-visuals") == full
    listing = server.aegis_skills("")
    assert "## optimus (" in listing
    assert "**orbit-blackline-visuals**" in listing
    assert "## aegis — ROOT NOT PRESENT" in listing


def test_a_project_skill_of_the_same_name_wins_and_the_clash_is_named(
        server, monkeypatch, tmp_path) -> None:
    project = tmp_path / "skills"
    (project / "orbit-blackline-visuals").mkdir(parents=True)
    (project / "orbit-blackline-visuals" / "SKILL.md").write_text(
        "---\nname: orbit-blackline-visuals\ndescription: project override\n---\n",
        encoding="utf-8")
    monkeypatch.setattr(server, "SKILL_ROOTS", (("aegis", project), ("optimus", SKILLS)))
    assert "[root: aegis]" in server.aegis_skills("orbit-blackline-visuals")
    assert "[root: optimus]" in server.aegis_skills("optimus:orbit-blackline-visuals")
    assert "NAME CLASHES" in server.aegis_skills("")
