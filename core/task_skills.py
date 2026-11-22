"""Task-scoped, read-only discovery for the Optimus MCP server."""
import hashlib
import json
import os
import re
from pathlib import Path

PACKS = {
    "finance": "Portfolio research, experiment records and verification",
    "coding": "Build, debug, test and maintain projects and skills",
    "cad": "Schematics, PCB layout, mechanics and design review",
    "presentation": "Slides, visual identity and design review",
    "research": "Evidence gathering, source checks and synthesis",
    "game-dev": "Game design, Studio development and playtesting",
}
PAGE_SIZE = 12
VALID_LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _sources(root, pack, defaults):
    """Only the operator config can add filesystem roots."""
    config = root / "brain" / "skill-access.json"
    extra = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    selected = dict(defaults.get(pack, {}))
    for label, path in extra.get(pack, {}).items():
        if not VALID_LABEL.fullmatch(label) or label == "guide":
            raise ValueError(f"invalid source label {label!r}")
        names = None
        if isinstance(path, dict):
            names = path.get("skills")
            if not isinstance(names, list) or not all(isinstance(n, str) and VALID_LABEL.fullmatch(n) for n in names):
                raise ValueError(f"{label} needs a list of skill folder names")
            path = path["directory"]
        expanded = Path(os.path.expandvars(path)).expanduser()
        if not expanded.is_absolute():
            raise ValueError(f"{label} needs an absolute skill directory")
        selected[label] = (expanded, names)
    return selected


def task_catalog(root, defaults, pack="", name="", page=1):
    if not pack:
        return {"packs": PACKS}
    if pack not in PACKS:
        return {"error": "Unknown pack", "packs": list(PACKS)}
    if page < 1:
        return {"error": "Page starts at 1"}
    try:
        roots = _sources(root, pack, defaults)
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        return {"error": f"Invalid skill-access configuration: {error}"}
    guides = root / "docs" / "skill-packs"
    index = {"guide:access": guides / "access.md", "guide:workflow": guides / (pack + ".md")}
    if pack == "coding":
        index["guide:editor"] = guides / "editor.md"
    handoff = root / "brain" / "projects" / ("task-" + pack) / "handoff.md"
    expected = root.resolve() / "brain" / "projects" / ("task-" + pack) / "handoff.md"
    if handoff.is_file() and handoff.resolve() == expected:
        index["guide:handoff"] = handoff
    missing = []
    missing_entries = []
    for label, source in sorted(roots.items()):
        path, allowed = source if isinstance(source, tuple) else (source, None)
        if not path.is_dir():
            missing.append(label)
            continue
        found = set()
        for manifest in path.glob("*/SKILL.md"):
            if allowed is not None and manifest.parent.name not in allowed:
                continue
            if manifest.is_file() and manifest.resolve().is_relative_to(path.resolve()):
                found.add(manifest.parent.name)
                index[label + ":" + manifest.parent.name] = manifest
        if allowed:
            missing_entries.extend(label + ":" + name for name in sorted(set(allowed) - found))
    if name:
        if name not in index:
            return {"pack": pack, "error": "Unknown entry", "name": name}
        path = index[name]
        try:
            data = path.read_bytes()
            return {"pack": pack, "name": name, "path": str(path.resolve()),
                    "sha256": hashlib.sha256(data).hexdigest(), "body": data.decode("utf-8-sig")}
        except (OSError, UnicodeError) as error:
            return {"pack": pack, "error": f"Cannot read {name}: {type(error).__name__}"}
    names = sorted(index)
    start = (page - 1) * PAGE_SIZE
    return {"pack": pack, "entries": names[start:start + PAGE_SIZE], "total": len(names),
            "next_page": page + 1 if start + PAGE_SIZE < len(names) else None,
            "missing_sources": missing, "missing_entries": missing_entries}


def register(server, root, defaults):
    @server.tool()
    def task_skills(pack: str = "", name: str = "", page: int = 1) -> dict:
        """List task packs, list one pack, or fetch one exact entry. Start without arguments.
        Entries have source:name IDs. guide:workflow gives the pack's working procedure.
        guide:handoff appears when the operator has saved a task-specific handoff."""
        return task_catalog(root, defaults, pack, name, page)
