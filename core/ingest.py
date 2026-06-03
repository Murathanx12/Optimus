"""Ingest — git channel (CLAUDE.md §5.1, Session 1 task 2).

Reads a git repository (local path or remote URL) and produces a Tier-2
project page set with span-level provenance:

    <slug>-overview   — title, description, capabilities (from README/ABSTRACT)
    <slug>-structure  — module map + file-type composition (from `git ls-files`)
    <slug>-history    — commit volume, range, authors, recent subjects

Design rule: the ingest source is **`git ls-files`** — tracked files only.
That respects ``.gitignore`` for free, so secrets (`.env`), virtualenvs,
`node_modules`, model blobs, caches, and "keep local only" docs never enter
the brain. Provenance spans use the form::

    git:<repo>@<sha7>:<path>#L<a>-L<b>

so every claim traces back to a specific commit and line range.

Session 1 is deterministic — no LLM call. Structural distillation only.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .deprecate import alias_pattern
from .schema import STATUS_FLAGGED, Claim, Page, Tier
from .store import Store

# Files worth turning into provenance-bearing prose. Everything else counts
# toward structure/composition but isn't read line-by-line.
_DOC_NAMES = {"readme.md", "abstract.md", "claude.md", "contributing.md"}
_MAX_RECENT_COMMITS = 15
_MAX_CAPABILITY_CLAIMS = 25


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def _is_remote(source: str) -> bool:
    return bool(re.match(r"^(https?://|git@|ssh://)", source)) or (
        source.endswith(".git") and not Path(source).exists()
    )


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# --------------------------------------------------------------------------- #
# result
# --------------------------------------------------------------------------- #
@dataclass
class IngestResult:
    project: str
    sha: str
    pages: list[str] = field(default_factory=list)      # page ids written
    claim_count: int = 0
    file_count: int = 0
    commit_count: int = 0
    skipped_untracked: bool = True                      # we read tracked files only
    flagged_claims: list[str] = field(default_factory=list)  # matched a tombstone (step 4)

    def summary(self) -> str:
        flagged = f" flagged={len(self.flagged_claims)}" if self.flagged_claims else ""
        sha = f" sha={self.sha[:7]}" if self.sha else ""
        commits = f" commits={self.commit_count}" if self.commit_count else ""
        return (
            f"project={self.project}{sha} pages={len(self.pages)} "
            f"claims={self.claim_count} files={self.file_count}{commits}{flagged}"
        )


# --------------------------------------------------------------------------- #
# README parsing (line-numbered, so claims keep provenance)
# --------------------------------------------------------------------------- #
@dataclass
class _Readme:
    title: str | None
    description: str | None
    desc_line: int | None
    sections: list[tuple[str, int]]          # (heading, line_no)
    capabilities: list[tuple[str, int]]      # (bullet_text, line_no)


def _parse_readme(text: str) -> _Readme:
    lines = text.splitlines()
    title = description = None
    desc_line = None
    sections: list[tuple[str, int]] = []
    capabilities: list[tuple[str, int]] = []
    in_caps = False

    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        if description is None and line.startswith(">"):
            description = line.lstrip("> ").strip()
            desc_line = i
            continue
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            heading = m.group(2).strip()
            sections.append((heading, i))
            # "What It Does" (and close variants) is the canonical capability list.
            in_caps = bool(re.search(r"what it does|features|capabilities", heading, re.I))
            continue
        if in_caps:
            bm = re.match(r"^[-*]\s+(.*)$", line)
            if bm:
                # Strip leading bold label markers but keep the text informative.
                capabilities.append((bm.group(1).strip(), i))

    if description is None:
        # First non-empty, non-heading paragraph line as a fallback description.
        for i, raw in enumerate(lines, start=1):
            s = raw.strip()
            if s and not s.startswith(("#", ">", "-", "*", "|", "```")):
                description, desc_line = s, i
                break

    return _Readme(title, description, desc_line, sections, capabilities)


# --------------------------------------------------------------------------- #
# structure / composition
# --------------------------------------------------------------------------- #
def _module_map(files: list[str]) -> dict[str, list[str]]:
    """Top-level component → immediate child entries (dirs get a trailing /)."""
    tree: dict[str, set[str]] = {}
    for f in files:
        parts = f.split("/")
        top = parts[0] if len(parts) > 1 else "(root)"
        child = parts[1] + "/" if len(parts) > 2 else (parts[1] if len(parts) > 1 else parts[0])
        tree.setdefault(top, set()).add(child)
    return {k: sorted(v) for k, v in sorted(tree.items())}


def _composition(files: list[str]) -> list[tuple[str, int]]:
    ext = Counter()
    for f in files:
        suffix = Path(f).suffix.lower().lstrip(".") or "(none)"
        ext[suffix] += 1
    return ext.most_common(15)


# --------------------------------------------------------------------------- #
# page builders
# --------------------------------------------------------------------------- #
def _span(repo: str, sha: str, path: str, a: int | None = None, b: int | None = None) -> str:
    base = f"git:{repo}@{sha[:7]}:{path}"
    if a is None:
        return base
    return f"{base}#L{a}-L{b if b is not None else a}"


def _project_aliases(slug: str, repo_name: str, display_name: str) -> list[str]:
    """Human strings that should resolve to the project's canonical (overview) page.

    The slug is the immutable machine key; the display name is the README H1; the
    short form is the first slug segment (e.g. ``aegis`` for ``aegis-finance``).
    Page() dedups these case-insensitively. Curated aliases (e.g. "the finance
    engine") get added later by distill/manual edit via the same aliases table.
    """
    short = slug.split("-")[0]
    return [slug, display_name, repo_name, short]


def _build_overview(
    slug: str, repo_name: str, display_name: str, sha: str,
    readme: _Readme | None, has_abstract: bool,
) -> tuple[Page, list[Claim]]:
    sources = [_span(repo_name, sha, "README.md")] if readme else []
    if has_abstract:
        sources.append(_span(repo_name, sha, "ABSTRACT.md"))

    lines = [f"# {display_name}", ""]
    if readme and readme.description:
        lines += [f"> {readme.description}", ""]
    if readme and readme.capabilities:
        lines += ["## Capabilities", ""]
        for text, _ln in readme.capabilities[:_MAX_CAPABILITY_CLAIMS]:
            lines.append(f"- {text}")
        lines.append("")
    if readme and readme.sections:
        lines += ["## README sections", ""]
        lines += [f"- {h}" for h, _ in readme.sections]
        lines.append("")

    page = Page(
        id=f"{slug}-overview",
        title=f"{display_name} — Overview",
        tier=int(Tier.PROJECTS),
        type="overview",
        project=slug,
        aliases=_project_aliases(slug, repo_name, display_name),
        tags=["project", "overview"],
        sources=sources,
        body="\n".join(lines),
    )

    claims: list[Claim] = []
    if readme:
        if readme.description and readme.desc_line:
            claims.append(Claim(
                id=f"{slug}-desc",
                page_id=page.id,
                text=readme.description,
                source=_span(repo_name, sha, "README.md", readme.desc_line),
                tier=int(Tier.PROJECTS),
            ))
        for n, (text, ln) in enumerate(readme.capabilities[:_MAX_CAPABILITY_CLAIMS]):
            claims.append(Claim(
                id=f"{slug}-cap-{n:02d}",
                page_id=page.id,
                text=text,
                source=_span(repo_name, sha, "README.md", ln),
                tier=int(Tier.PROJECTS),
            ))
    return page, claims


def _build_structure(
    slug: str, repo_name: str, display_name: str, sha: str, files: list[str]
) -> Page:
    modules = _module_map(files)
    comp = _composition(files)

    lines = [f"# {display_name} — Structure", "",
             f"Tracked files: **{len(files)}** (source: `git ls-files`, secrets/ignored excluded).", "",
             "## Module map", ""]
    for top, children in modules.items():
        shown = ", ".join(children[:12])
        more = f" … (+{len(children) - 12} more)" if len(children) > 12 else ""
        lines.append(f"- **{top}** — {shown}{more}")
    lines += ["", "## File composition", ""]
    for ext, n in comp:
        lines.append(f"- `.{ext}` × {n}")

    return Page(
        id=f"{slug}-structure",
        title=f"{display_name} — Structure",
        tier=int(Tier.PROJECTS),
        type="structure",
        project=slug,
        aliases=[f"{slug} structure", f"{display_name} structure"],
        tags=["project", "structure"],
        sources=[_span(repo_name, sha, ".")],   # the tree at this commit
        body="\n".join(lines),
    )


def _build_history(
    slug: str, repo_name: str, display_name: str, sha: str, repo: Path
) -> tuple[Page, int]:
    count = int(_git(repo, "rev-list", "--count", "HEAD").strip() or "0")
    first = _git(repo, "log", "--reverse", "--format=%ad", "--date=short").splitlines()
    last = _git(repo, "log", "-1", "--format=%ad", "--date=short").strip()
    first_date = first[0].strip() if first else "?"
    authors = _git(repo, "shortlog", "-sne", "HEAD").splitlines()
    recent = _git(
        repo, "log", f"-{_MAX_RECENT_COMMITS}", "--format=%h %ad %s", "--date=short"
    ).splitlines()

    lines = [f"# {display_name} — Commit History", "",
             f"- Total commits: **{count}**",
             f"- Active range: {first_date} → {last}", "",
             "## Top contributors", ""]
    for a in authors[:8]:
        lines.append(f"- {a.strip()}")
    lines += ["", f"## Recent commits (last {len(recent)})", ""]
    for r in recent:
        lines.append(f"- {r}")

    page = Page(
        id=f"{slug}-history",
        title=f"{display_name} — Commit History",
        tier=int(Tier.PROJECTS),
        type="history",
        project=slug,
        aliases=[f"{slug} history", f"{display_name} history"],
        tags=["project", "history"],
        sources=[_span(repo_name, sha, "<git-log>")],
        body="\n".join(lines),
    )
    return page, count


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def ingest_git(store: Store, source: str, project: str | None = None) -> IngestResult:
    """Ingest a git repo into the brain. `source` is a local path or remote URL."""
    if _is_remote(source):
        clone_dir = store.root / "raw" / "clones" / _slugify(Path(source).stem)
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        if not clone_dir.exists():
            subprocess.run(["git", "clone", "--quiet", source, str(clone_dir)], check=True)
        repo = clone_dir
    else:
        repo = Path(source).resolve()
        if not (repo / ".git").exists():
            raise ValueError(f"not a git repository: {repo}")

    repo_name = repo.name
    slug = project or _slugify(repo_name)
    sha = _git(repo, "rev-parse", "HEAD").strip()
    files = [f for f in _git(repo, "ls-files").splitlines() if f.strip()]

    # README / ABSTRACT (case-insensitive lookup among tracked files).
    lower = {f.lower(): f for f in files}
    readme = None
    if "readme.md" in lower:
        readme = _parse_readme((repo / lower["readme.md"]).read_text(encoding="utf-8", errors="replace"))
    has_abstract = "abstract.md" in lower

    # Identifier split (load-bearing for query/deprecate):
    #   slug         = immutable machine key (id, edges, claims reference this)
    #   display_name = README H1, mutable, re-derived each ingest, shown to humans
    display_name = readme.title if readme and readme.title else repo_name

    overview, claims = _build_overview(slug, repo_name, display_name, sha, readme, has_abstract)
    structure = _build_structure(slug, repo_name, display_name, sha, files)
    history, commit_count = _build_history(slug, repo_name, display_name, sha, repo)

    # Step 4 — tombstone-aware ingest: a claim mentioning a tombstoned entity is
    # held in `flagged` (not active, not silently revived) for human/LLM
    # resolution. The rest of the source ingests normally. We never auto-classify
    # removal-vs-stale intent — that's deferred to the LLM/human layer.
    flagged = _flag_tombstoned(store, claims)
    overview.claims = claims                      # claims live on the page (front-matter)

    for page in (overview, structure, history):
        store.write_page(page)

    # Typed edges: structure and history are part_of the overview.
    store.add_edge(structure.id, overview.id, "part_of")
    store.add_edge(history.id, overview.id, "part_of")

    result = IngestResult(
        project=slug,
        sha=sha,
        pages=[overview.id, structure.id, history.id],
        claim_count=len(claims),
        file_count=len(files),
        commit_count=commit_count,
        flagged_claims=flagged,
    )
    store.log_event(
        "ingest",
        target=slug,
        detail={
            "channel": "git",
            "source": str(repo),
            "sha": sha,
            "pages": result.pages,
            "claims": result.claim_count,
            "files": result.file_count,
            "commits": result.commit_count,
            "flagged": flagged,
        },
    )
    return result


def _flag_tombstoned(store: Store, claims: list[Claim]) -> list[str]:
    """Mark any claim mentioning a tombstoned alias as `flagged`; return their ids."""
    tomb = store.tombstoned_aliases()             # alias(lower) → canonical entity
    if not tomb:
        return []
    pattern = alias_pattern(list(tomb.keys()))
    flagged: list[str] = []
    for c in claims:
        if pattern.search(c.text):
            c.status = STATUS_FLAGGED
            flagged.append(c.id)
    return flagged


# --------------------------------------------------------------------------- #
# folder channel (CLAUDE.md §5.2) — Tier A (structure + tools) + Tier B (text)
# --------------------------------------------------------------------------- #
# Extension → tool/software. The cheap, deterministic "what is he using" signal:
# learned from file extensions, never from reading file contents.
_TOOL_BY_EXT = {
    "blend": "Blender", "blend1": "Blender",
    "f3d": "Fusion 360", "f3z": "Fusion 360",
    "fbx": "3D asset (FBX)", "obj": "3D asset (OBJ)", "gltf": "glTF", "glb": "glTF",
    "stl": "3D print / mesh", "3mf": "3D print", "step": "CAD (STEP)", "stp": "CAD (STEP)",
    "iges": "CAD (IGES)", "igs": "CAD (IGES)",
    "sldprt": "SolidWorks", "sldasm": "SolidWorks", "slddrw": "SolidWorks",
    "dwg": "AutoCAD", "dxf": "CAD (DXF)",
    "kicad_pcb": "KiCad", "kicad_sch": "KiCad", "sch": "EDA schematic", "brd": "PCB layout",
    "ino": "Arduino", "hex": "firmware",
    "ipynb": "Jupyter", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
    "tsx": "React/TSX", "jsx": "React",
    "psd": "Photoshop", "kra": "Krita", "ai": "Illustrator", "xcf": "GIMP",
    "ztl": "ZBrush", "zpr": "ZBrush", "spp": "Substance Painter", "sbs": "Substance Designer",
    "unity": "Unity", "uasset": "Unreal", "umap": "Unreal",
    "sldworks": "SolidWorks", "tex": "LaTeX", "docx": "Word", "pptx": "PowerPoint",
    "xlsx": "Excel", "c": "C", "cpp": "C++", "h": "C/C++ header", "rs": "Rust",
    "go": "Go", "java": "Java", "cs": "C#",
}
_TEXT_EXT = {"md", "markdown", "txt", "rst"}
_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".cache",
    "dist", "build", ".next", "out", ".idea", ".vscode", ".gradle",
    ".mypy_cache", ".pytest_cache", "site-packages",
}
_MAX_DOC_FILES = 40
_MAX_DOC_BYTES = 64_000


def _fspan(slug: str, relpath: str, line: int | None = None) -> str:
    base = f"folder:{slug}:{relpath}"
    return f"{base}#L{line}" if line else base


def _walk_folder(root: Path) -> tuple[list[str], float]:
    """Return (relative posix paths, newest mtime). Skips junk dirs + dotfiles.
    Reads only directory entries — never file contents."""
    rels: list[str] = []
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):                  # dotfiles (e.g. .env) never enter the brain
                continue
            p = Path(dirpath) / fn
            rels.append(p.relative_to(root).as_posix())
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
    return rels, newest


def _detect_tools(rels: list[str]) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for r in rels:
        ext = Path(r).suffix.lower().lstrip(".")
        if ext in _TOOL_BY_EXT:
            counts[_TOOL_BY_EXT[ext]] += 1
    return counts.most_common()


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#>-*").strip()
        if s:
            return s
    return ""


def ingest_folder(store: Store, source: str, project: str | None = None) -> IngestResult:
    """Ingest a local folder. Tier A: structure + tool detection from names/extensions
    (no contents read). Tier B: read small text/doc files only (binaries never opened)."""
    root = Path(source).resolve()
    if not root.is_dir():
        raise ValueError(f"not a folder: {root}")
    name = root.name
    slug = project or _slugify(name)

    rels, newest = _walk_folder(root)               # Tier A — names/extensions only
    tools = _detect_tools(rels)
    comp = _composition(rels)
    modules = _module_map(rels)
    newest_date = ""
    if newest:
        import datetime as _dt
        newest_date = _dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d")

    # Tier B — read doc/text files only, capped, binaries skipped entirely.
    display_name = name
    description = None
    claims: list[Claim] = []

    readme_rel = next((r for r in rels if Path(r).name.lower().startswith("readme")), None)
    if readme_rel:
        try:
            rm = _parse_readme((root / readme_rel).read_text(encoding="utf-8", errors="replace"))
            if rm.title:
                display_name = rm.title
            if rm.description:
                description = rm.description
                claims.append(Claim(id=f"{slug}-desc", page_id=f"{slug}-overview",
                                    text=rm.description, source=_fspan(slug, readme_rel, 1), tier=2))
            for n, (text, ln) in enumerate(rm.capabilities[:15]):
                claims.append(Claim(id=f"{slug}-cap-{n:02d}", page_id=f"{slug}-overview",
                                    text=text, source=_fspan(slug, readme_rel, ln), tier=2))
        except OSError:
            pass

    # Tool-usage facts become claims (this is the "he uses Blender + Fusion" signal).
    for i, (tool, n) in enumerate(tools):
        claims.append(Claim(id=f"{slug}-tool-{i:02d}", page_id=f"{slug}-overview",
                            text=f"Uses {tool} ({n} file{'s' if n != 1 else ''})",
                            source=_fspan(slug, "."), tier=2))

    # Other doc files → one claim each (path + first line), capped.
    docs = [r for r in rels
            if Path(r).suffix.lower().lstrip(".") in _TEXT_EXT and r != readme_rel]
    for r in docs[:_MAX_DOC_FILES]:
        fp = root / r
        try:
            if fp.stat().st_size > _MAX_DOC_BYTES:
                continue
            first = _first_meaningful_line(fp.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if first:
            claims.append(Claim(id=f"{slug}-doc-{len([c for c in claims if '-doc-' in c.id]):02d}",
                                page_id=f"{slug}-overview",
                                text=f"{r}: {first}", source=_fspan(slug, r, 1), tier=2))

    # --- pages ---
    ov_lines = [f"# {display_name}", "",
                f"> {description}" if description else "> Local folder ingested by Optimus (folder channel).",
                ""]
    if tools:
        ov_lines += ["## Tools detected", ""]
        ov_lines += [f"- {tool} — {n} file{'s' if n != 1 else ''}" for tool, n in tools]
        ov_lines.append("")
    ov_lines += ["## Activity", "",
                 f"- Tracked files: **{len(rels)}**",
                 f"- Most recent edit: {newest_date or 'unknown'}", ""]
    overview = Page(
        id=f"{slug}-overview", title=f"{display_name} — Overview", tier=int(Tier.PROJECTS),
        type="overview", project=slug, aliases=[slug, display_name, name, slug.split("-")[0]],
        tags=["project", "overview", "folder"], sources=[_fspan(slug, ".")],
        body="\n".join(ov_lines),
    )

    st_lines = [f"# {display_name} — Structure", "",
                f"Files: **{len(rels)}** (folder channel; binaries counted, not read; "
                "junk dirs + dotfiles skipped).", "", "## Top-level", ""]
    for top, children in modules.items():
        shown = ", ".join(children[:12])
        more = f" … (+{len(children) - 12} more)" if len(children) > 12 else ""
        st_lines.append(f"- **{top}** — {shown}{more}")
    st_lines += ["", "## File composition", ""]
    st_lines += [f"- `.{ext}` × {n}" for ext, n in comp]
    structure = Page(
        id=f"{slug}-structure", title=f"{display_name} — Structure", tier=int(Tier.PROJECTS),
        type="structure", project=slug, aliases=[f"{slug} structure"],
        tags=["project", "structure", "folder"], sources=[_fspan(slug, ".")],
        body="\n".join(st_lines),
    )

    flagged = _flag_tombstoned(store, claims)
    overview.claims = claims
    for page in (overview, structure):
        store.write_page(page)
    store.add_edge(structure.id, overview.id, "part_of")

    result = IngestResult(
        project=slug, sha="", pages=[overview.id, structure.id],
        claim_count=len(claims), file_count=len(rels), commit_count=0,
        flagged_claims=flagged,
    )
    store.log_event("ingest", target=slug, detail={
        "channel": "folder", "source": str(root), "pages": result.pages,
        "claims": result.claim_count, "files": result.file_count,
        "tools": [t for t, _ in tools], "flagged": flagged,
    })
    return result
