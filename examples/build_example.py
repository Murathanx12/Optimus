"""Generate examples/brain/ from a throwaway synthetic repo.

The engine is open-source; real brain content is private (gitignored). This
script produces a committable *synthetic* brain so anyone reading the repo can
see the page layout and front-matter schema without any of Murat's real memory.

Regenerate:
    python examples/build_example.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ingest import ingest_git  # noqa: E402
from core.store import Store  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent

_README = """# Example Project

> A synthetic project showing what an ingested Optimus brain page set looks like.

## What It Does

- **Demo module** — illustrates a capability claim with line-level provenance.
- **Sample pipeline** — second capability, also cited back to this README.

## Architecture

Synthetic prose; the real value is the page/front-matter shape, not the content.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "example-project"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "example@optimus.local")
        _git(repo, "config", "user.name", "Optimus Example")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "README.md").write_text(_README, encoding="utf-8")
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "initial: example scaffold")

        with Store(EXAMPLES) as store:  # writes examples/brain/...
            result = ingest_git(store, str(repo), project="example-project")
        print("generated examples/brain/:", result.summary())


if __name__ == "__main__":
    main()
