"""Store: the single read/write path for brain pages + the derived SQLite index.

Markdown files under ``brain/`` are source of truth. Every page write also
upserts a row into ``index.db``. The index can be fully rebuilt from markdown
via :meth:`Store.reindex`.

Tier → directory mapping (CLAUDE.md §4.2):
    Tier 1 IDENTITY     -> brain/identity/
    Tier 2 PROJECTS     -> brain/projects/<project>/
    Tier 3 DISPOSITIONS -> brain/dispositions/
    Tier 4 EPHEMERAL    -> brain/ephemeral/   (created on demand)
Conversation memory lives under brain/conversations/ regardless of tier.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import yaml

from .schema import (
    DDL,
    STATUS_ACTIVE,
    Claim,
    Page,
    Tier,
    utcnow_iso,
)


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.brain = self.root / "brain"
        self.db_path = self.brain / "index.db"
        self.brain.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(DDL)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------- #
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- path resolution ---------------------------------------------------- #
    def page_dir(self, page: Page) -> Path:
        if page.tier == Tier.IDENTITY:
            return self.brain / "identity"
        if page.tier == Tier.PROJECTS:
            sub = page.project or "_unknown"
            return self.brain / "projects" / sub
        if page.tier == Tier.DISPOSITIONS:
            return self.brain / "dispositions"
        return self.brain / "ephemeral"

    def page_path(self, page: Page) -> Path:
        return self.page_dir(page) / f"{page.id}.md"

    def rel_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # -- page write/read ---------------------------------------------------- #
    def write_page(self, page: Page) -> Path:
        """Write a page to markdown and upsert its index row (source-of-truth first)."""
        path = self.page_path(page)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page.to_markdown(), encoding="utf-8")
        self._index_page(page, path)
        self._conn.commit()
        return path

    def read_page(self, page_id: str) -> Page | None:
        row = self._conn.execute(
            "SELECT path FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        if row is None:
            return None
        return Page.from_markdown((self.root / row["path"]).read_text(encoding="utf-8"))

    def _index_page(self, page: Page, path: Path) -> None:
        self._conn.execute(
            """
            INSERT INTO pages (id, title, tier, type, project, path, status,
                               content_hash, created, updated)
            VALUES (:id, :title, :tier, :type, :project, :path, :status,
                    :content_hash, :created, :updated)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, tier=excluded.tier, type=excluded.type,
                project=excluded.project, path=excluded.path, status=excluded.status,
                content_hash=excluded.content_hash, updated=excluded.updated
            """,
            {
                "id": page.id,
                "title": page.title,
                "tier": int(page.tier),
                "type": page.type,
                "project": page.project,
                "path": self.rel_path(path),
                "status": page.status,
                "content_hash": page.body_hash,
                "created": page.created,
                "updated": page.updated,
            },
        )
        # Aliases: refresh the set for this page. The page id is always a (canonical) alias.
        self._conn.execute("DELETE FROM aliases WHERE page_id = ?", (page.id,))
        seen: set[str] = set()
        for i, alias in enumerate([page.title, *page.aliases]):
            key = alias.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            self._conn.execute(
                "INSERT OR IGNORE INTO aliases (alias, page_id, canonical) VALUES (?, ?, ?)",
                (alias, page.id, 1 if i == 0 else 0),
            )
        # Claims: refresh from the page's front-matter (markdown is source of truth).
        # This runs in both write_page and reindex, so the index — including claim
        # deprecation status — is always rebuildable from the .md alone.
        self._conn.execute("DELETE FROM claims WHERE page_id = ?", (page.id,))
        for c in page.claims:
            self._conn.execute(
                "INSERT INTO claims (id, page_id, text, source, tier, status, created, "
                "kind, rationale, quote) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (c.id, page.id, c.text, c.source, int(c.tier), c.status, c.created,
                 c.kind, c.rationale, c.quote),
            )

    # -- claims (read-only; writes go through pages, never the index directly) #
    def _claims_from_rows(self, rows) -> list[Claim]:
        keys = set(rows[0].keys()) if rows else set()
        return [
            Claim(
                id=r["id"], page_id=r["page_id"], text=r["text"], source=r["source"],
                tier=r["tier"], status=r["status"], created=r["created"],
                kind=r["kind"] if "kind" in keys else "fact",
                rationale=r["rationale"] if "rationale" in keys else None,
                quote=r["quote"] if "quote" in keys else None,
            )
            for r in rows
        ]

    def claims_for(self, page_id: str, status: str | None = None) -> list[Claim]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM claims WHERE page_id = ? ORDER BY id", (page_id,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM claims WHERE page_id = ? AND status = ? ORDER BY id",
                (page_id, status),
            ).fetchall()
        return self._claims_from_rows(rows)

    def all_claims(self, status: str | None = None) -> list[Claim]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM claims ORDER BY id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM claims WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        return self._claims_from_rows(rows)

    # -- edges -------------------------------------------------------------- #
    def add_edge(self, src_page_id: str, dst_page_id: str, rel: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO edges (src_page_id, dst_page_id, rel, created) "
            "VALUES (?, ?, ?, ?)",
            (src_page_id, dst_page_id, rel, utcnow_iso()),
        )
        self._conn.commit()

    # -- events ------------------------------------------------------------- #
    def log_event(self, op: str, target: str | None = None, detail: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO events (ts, op, target, detail) VALUES (?, ?, ?, ?)",
            (utcnow_iso(), op, target, json.dumps(detail or {})),
        )
        self._conn.commit()

    # -- tombstones (dead facts; block silent re-ingestion, CLAUDE.md §4.5) -- #
    def path_of(self, page_id: str) -> Path | None:
        row = self._conn.execute(
            "SELECT path FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        return (self.root / row["path"]) if row else None

    def write_tombstone(
        self, entity: str, aliases: list[str], reason: str,
        pages: list[str], created: str, source: str | None = None,
    ) -> None:
        slug = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-")
        self._conn.execute(
            """
            INSERT INTO tombstones (id, entity, canonical_alias, aliases, pages,
                                    reason, source, created)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                entity=excluded.entity, canonical_alias=excluded.canonical_alias,
                aliases=excluded.aliases, pages=excluded.pages, reason=excluded.reason,
                source=excluded.source, created=excluded.created
            """,
            (slug, entity, entity, json.dumps(sorted(set(aliases))),
             json.dumps(pages), reason, source, created),
        )
        self._conn.commit()
        self._rewrite_tombstones_md()

    def remove_tombstone(self, entity: str) -> None:
        slug = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-")
        self._conn.execute("DELETE FROM tombstones WHERE id = ?", (slug,))
        self._conn.commit()
        self._rewrite_tombstones_md()

    def list_tombstones(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tombstones ORDER BY id"
        ).fetchall()
        return [
            {
                "id": r["id"], "entity": r["entity"], "reason": r["reason"],
                "aliases": json.loads(r["aliases"]), "pages": json.loads(r["pages"]),
                "created": r["created"],
            }
            for r in rows
        ]

    def tombstoned_aliases(self) -> dict[str, str]:
        """alias (lowercased) → canonical entity, across all tombstones."""
        out: dict[str, str] = {}
        for t in self.list_tombstones():
            for a in t["aliases"]:
                out[a.lower()] = t["entity"]
        return out

    def _rewrite_tombstones_md(self) -> None:
        """Write brain/tombstones.md as the SOURCE OF TRUTH: machine-readable
        front-matter (re-parsed by reindex) + a human-readable body. Symmetric to
        how pages carry claims — so tombstones survive a full index rebuild."""
        toms = self.list_tombstones()
        fm = {"tombstones": [
            {"id": t["id"], "entity": t["entity"], "aliases": t["aliases"],
             "pages": t["pages"], "reason": t["reason"], "created": t["created"]}
            for t in toms
        ]}
        body = [
            "# Tombstones", "",
            "Dead facts. Each blocks silent re-ingestion of the entity "
            "(CLAUDE.md §4.5 `deprecate`). Front-matter above is source of truth.", "",
        ]
        for t in toms:
            body += [
                f"## {t['entity']}", "",
                f"- deprecated: {t['created']}",
                f"- reason: {t['reason']}",
                f"- aliases: {', '.join(t['aliases'])}",
                f"- pages: {', '.join(t['pages']) or '(none)'}",
                "",
            ]
        text = ("---\n"
                + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
                + "---\n\n" + "\n".join(body) + "\n")
        (self.brain / "tombstones.md").write_text(text, encoding="utf-8")

    def _parse_tombstones_md(self) -> list[dict]:
        """Read tombstone records from tombstones.md front-matter (source of truth)."""
        path = self.brain / "tombstones.md"
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return []
        parts = text.split("---", 2)
        if len(parts) < 3:
            return []
        fm = yaml.safe_load(parts[1]) or {}
        return list(fm.get("tombstones") or [])

    # -- queries used by tests / reporting ---------------------------------- #
    def page_count(self, project: str | None = None) -> int:
        if project is None:
            return self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        return self._conn.execute(
            "SELECT COUNT(*) FROM pages WHERE project = ?", (project,)
        ).fetchone()[0]

    def pages_for_project(self, project: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM pages WHERE project = ? ORDER BY type, id", (project,)
        ).fetchall()

    def all_pages(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT id, title, tier, type, project, path, status FROM pages "
            "WHERE status = 'active' ORDER BY id"
        ).fetchall()

    def all_aliases(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT alias, page_id, canonical FROM aliases"
        ).fetchall()

    def resolve_alias(self, alias: str) -> list[str]:
        """Alias (case-insensitive) → list of page ids."""
        rows = self._conn.execute(
            "SELECT page_id FROM aliases WHERE LOWER(alias) = LOWER(?)", (alias,)
        ).fetchall()
        return [r["page_id"] for r in rows]

    def events(self, op: str | None = None) -> list[sqlite3.Row]:
        if op is None:
            return self._conn.execute("SELECT * FROM events ORDER BY id").fetchall()
        return self._conn.execute(
            "SELECT * FROM events WHERE op = ? ORDER BY id", (op,)
        ).fetchall()

    # -- rebuild ------------------------------------------------------------ #
    def reindex(self) -> int:
        """Rebuild the page/alias index from markdown on disk. Returns page count.

        This is the proof that SQLite is derived: drop the index data and
        re-read every ``.md`` page under brain/.
        """
        self._conn.execute("DELETE FROM aliases")
        self._conn.execute("DELETE FROM pages")
        count = 0
        for md in sorted(self.brain.rglob("*.md")):
            if md.name == "tombstones.md":          # rebuilt from its front-matter below
                continue
            page = Page.from_markdown(md.read_text(encoding="utf-8"))
            self._index_page(page, md)
            count += 1
        # Tombstones are derived too: rebuild the table from tombstones.md so dead
        # facts (and their re-ingestion block) survive a full index deletion.
        self._conn.execute("DELETE FROM tombstones")
        for t in self._parse_tombstones_md():
            self._conn.execute(
                """
                INSERT OR REPLACE INTO tombstones
                    (id, entity, canonical_alias, aliases, pages, reason, source, created)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t["id"], t["entity"], t.get("entity"),
                 json.dumps(list(t.get("aliases") or [])),
                 json.dumps(list(t.get("pages") or [])),
                 t.get("reason", ""), None, t.get("created", "")),
            )
        self._conn.commit()
        return count
