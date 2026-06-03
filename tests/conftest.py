"""Shared fixtures: a self-contained synthetic git repo for ingest tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_README = """# Test Project

> A tiny synthetic repo for exercising git ingest.

## What It Does

- **Widget engine** — does the widget thing with provenance.
- **Sprocket cache** — caches sprockets for speed.
- Plain bullet without bold label.

## Architecture

Some prose about the architecture goes here.
"""

_ABSTRACT = "# Abstract\n\nThis is the synthetic project abstract.\n"
_SECRET = "API_KEY=super-secret-do-not-ingest\n"
_GITIGNORE = ".env\n__pycache__/\n"


def _run(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Create a small git repo with a README, an ABSTRACT, source dirs, and a
    gitignored .env secret. Returns the repo path."""
    repo = tmp_path / "test-project"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test Runner")
    _run(repo, "config", "commit.gpgsign", "false")

    (repo / "README.md").write_text(_README, encoding="utf-8")
    (repo / "ABSTRACT.md").write_text(_ABSTRACT, encoding="utf-8")
    (repo / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    (repo / ".env").write_text(_SECRET, encoding="utf-8")  # must NOT be ingested

    (repo / "backend").mkdir()
    (repo / "backend" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (repo / "backend" / "db.py").write_text("DB = 'sqlite'\n", encoding="utf-8")
    (repo / "engine").mkdir()
    (repo / "engine" / "train.py").write_text("MODEL = 'lgbm'\n", encoding="utf-8")

    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "initial: scaffold project")

    # A second commit so history has volume + range.
    (repo / "backend" / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "feat: bump return value")

    return repo


_BUZZER_README = """# Artooth

> The mecanum robotic butler.

## What It Does

- **Buzzer** — alerts the operator on crash detection.
- **Wheel encoder** — reports odometry to the controller.
"""


@pytest.fixture
def buzzer_repo(tmp_path: Path) -> Path:
    """A git repo whose README capability list mentions the buzzer — for the
    tombstone-aware-ingest (step 4) tests."""
    repo = tmp_path / "artooth"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test Runner")
    _run(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text(_BUZZER_README, encoding="utf-8")
    (repo / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "initial: artooth")
    return repo


@pytest.fixture
def synthetic_folder(tmp_path: Path) -> Path:
    """A non-git folder with binaries + text + junk, for folder-ingest tests."""
    root = tmp_path / "my-art"
    root.mkdir()
    (root / "README.md").write_text("# My Art\n\n> A folder of 3D experiments.\n", encoding="utf-8")
    (root / "notes.txt").write_text("Trying hard-surface modeling this week.\n", encoding="utf-8")
    (root / "robot.blend").write_bytes(b"BLENDER\x00\x01binary-not-text")   # must NOT be read
    (root / "part.f3d").write_bytes(b"\x00fusion-binary")
    (root / "build.py").write_text("print('hi')\n", encoding="utf-8")
    scene = root / "scene01"
    scene.mkdir()
    (scene / "hero.blend").write_bytes(b"\x00\x01blend")
    (scene / "tex.png").write_bytes(b"\x89PNG\x00")
    junk = root / "node_modules"          # must be ignored
    junk.mkdir()
    (junk / "lib.js").write_text("x", encoding="utf-8")
    (root / ".env").write_text("SECRET=do-not-ingest", encoding="utf-8")     # dotfile, skipped
    return root


@pytest.fixture
def optimus_root(tmp_path: Path) -> Path:
    """An isolated Optimus root (brain/ + index.db created on demand)."""
    root = tmp_path / "optimus-root"
    root.mkdir()
    return root
