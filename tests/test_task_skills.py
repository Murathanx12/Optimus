import hashlib
import json
from pathlib import Path

from core.task_skills import PAGE_SIZE, task_catalog


def test_discovery_avoids_manifest_reads(tmp_path, monkeypatch):
    checkout = tmp_path / "skills"
    for n in range(PAGE_SIZE + 2):
        folder = checkout / f"check-{n:02d}"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("private body", encoding="utf-8")
    roots = {"cad": {"board": checkout}}
    def unexpected_read(*args, **kwargs):
        raise AssertionError("catalog opened a skill body")
    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    first = task_catalog(tmp_path, roots, "cad")
    second = task_catalog(tmp_path, roots, "cad", page=2)
    assert len(first["entries"]) == PAGE_SIZE
    assert first["next_page"] == 2 and second["next_page"] is None
    assert set(first["entries"]).isdisjoint(second["entries"])
    assert task_catalog(tmp_path, roots, "research", "board:check-00").get("error")


def test_private_pack_filter_and_provenance(tmp_path):
    root = tmp_path / "skills"
    for name in ("cad", "game"):
        skill = root / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(name.encode())
    brain = tmp_path / "brain"
    brain.mkdir()
    config = {"cad": {"project": {"directory": str(root), "skills": ["cad", "gone"]}}}
    (brain / "skill-access.json").write_text(json.dumps(config), encoding="utf-8")
    listing = task_catalog(tmp_path, {}, "cad")
    assert "project:game" not in listing["entries"]
    assert listing["missing_entries"] == ["project:gone"]
    record = task_catalog(tmp_path, {}, "cad", "project:cad")
    assert record["body"] == "cad" and Path(record["path"]) == root / "cad" / "SKILL.md"
    assert record["sha256"] == hashlib.sha256(b"cad").hexdigest()
    assert task_catalog(tmp_path, {}, "cad", "../game").get("error")


def test_guides_and_handoff(tmp_path):
    assert "coding" in task_catalog(tmp_path, {})["packs"]
    assert "guide:editor" in task_catalog(tmp_path, {}, "coding")["entries"]
    assert "guide:editor" not in task_catalog(tmp_path, {}, "game-dev")["entries"]
    handoff = tmp_path / "brain/projects/task-game-dev/handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text("verified place", encoding="utf-8")
    assert task_catalog(tmp_path, {}, "game-dev", "guide:handoff")["body"] == "verified place"
    assert "guide:handoff" not in task_catalog(tmp_path, {}, "cad")["entries"]
    assert "missing" in task_catalog(tmp_path, {"cad": {"missing": tmp_path / "absent"}}, "cad")["missing_sources"]
