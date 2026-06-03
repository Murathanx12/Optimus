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
def optimus_root(tmp_path: Path) -> Path:
    """An isolated Optimus root (brain/ + index.db created on demand)."""
    root = tmp_path / "optimus-root"
    root.mkdir()
    return root
