"""Optimus memory schema: front-matter model + derived SQLite index.

Markdown is the source of truth. SQLite is a *derived* index — if it corrupts,
it can be rebuilt from the markdown pages. Never the reverse.

This module defines:
  - the memory tiers (load-bearing: different decay/edit rules per tier),
  - the `Page` front-matter model and its markdown (de)serialization,
  - the `Claim` model (atomic, provenance-carrying statements),
  - the DDL for the six tables: pages, edges, aliases, claims, tombstones, events.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

import yaml


# --------------------------------------------------------------------------- #
# Tiers — different decay rates and edit rules (CLAUDE.md §4.3)
# --------------------------------------------------------------------------- #
class Tier(IntEnum):
    IDENTITY = 1      # who he is, permanent facts        — manual-approval edits only
    PROJECTS = 2      # project state, decisions, patterns — auto-update, volatile
    DISPOSITIONS = 3  # how he decides/communicates        — auto-update, observed > stated
    EPHEMERAL = 4     # task-scoped, transient             — auto-expire


# Page status values.
STATUS_ACTIVE = "active"
STATUS_DEPRECATED = "deprecated"

# Front-matter key order, fixed so serialization is deterministic and diffs stay clean.
_FRONTMATTER_ORDER = (
    "id",
    "title",
    "tier",
    "type",
    "project",
    "aliases",
    "tags",
    "sources",
    "status",
    "created",
    "updated",
)


def utcnow_iso() -> str:
    """Current UTC time as a stable ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(text: str) -> str:
    """Stable SHA-256 of page body — used to detect real changes on re-ingest."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Page:
    """A single brain page: YAML front-matter + markdown body.

    `sources` holds provenance spans. For the git channel the format is
    ``git:<repo>@<sha>:<path>#L<a>-L<b>`` so every claim is traceable to a
    commit and line range.
    """

    id: str
    title: str
    tier: int
    type: str
    body: str = ""
    project: str | None = None
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    status: str = STATUS_ACTIVE
    created: str = field(default_factory=utcnow_iso)
    updated: str = field(default_factory=utcnow_iso)

    def __post_init__(self) -> None:
        # Dedup aliases case-insensitively, order-preserving (keep first casing).
        seen: set[str] = set()
        deduped: list[str] = []
        for a in self.aliases:
            key = a.strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(a)
        self.aliases = deduped

    # -- serialization ------------------------------------------------------ #
    def front_matter(self) -> dict[str, Any]:
        raw = {
            "id": self.id,
            "title": self.title,
            "tier": int(self.tier),
            "type": self.type,
            "project": self.project,
            "aliases": list(self.aliases),
            "tags": list(self.tags),
            "sources": list(self.sources),
            "status": self.status,
            "created": self.created,
            "updated": self.updated,
        }
        return {k: raw[k] for k in _FRONTMATTER_ORDER}

    def to_markdown(self) -> str:
        fm = yaml.safe_dump(
            self.front_matter(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        body = self.body.rstrip("\n")
        return f"---\n{fm}---\n\n{body}\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Page":
        fm, body = _split_front_matter(text)
        return cls(
            id=fm["id"],
            title=fm["title"],
            tier=int(fm["tier"]),
            type=fm["type"],
            body=body,
            project=fm.get("project"),
            aliases=list(fm.get("aliases") or []),
            tags=list(fm.get("tags") or []),
            sources=list(fm.get("sources") or []),
            status=fm.get("status", STATUS_ACTIVE),
            created=fm.get("created", utcnow_iso()),
            updated=fm.get("updated", utcnow_iso()),
        )

    @property
    def body_hash(self) -> str:
        return content_hash(self.body)


@dataclass
class Claim:
    """An atomic, provenance-carrying statement extracted into a page.

    `source` is a single provenance span (same grammar as Page.sources).
    """

    id: str
    page_id: str
    text: str
    source: str
    tier: int
    status: str = STATUS_ACTIVE
    created: str = field(default_factory=utcnow_iso)


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a ``---``-delimited YAML front-matter block + body."""
    if not text.startswith("---"):
        raise ValueError("page has no front-matter block")
    parts = text.split("---", 2)
    # parts[0] is empty (text starts with ---), parts[1] is YAML, parts[2] is body.
    if len(parts) < 3:
        raise ValueError("malformed front-matter block")
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return fm, body


# --------------------------------------------------------------------------- #
# SQLite DDL — the six derived tables (CLAUDE.md §7 Session 1, task 1)
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 2

DDL = """
CREATE TABLE IF NOT EXISTS pages (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    tier         INTEGER NOT NULL,
    type         TEXT NOT NULL,
    project      TEXT,
    path         TEXT NOT NULL,          -- markdown path relative to repo root
    status       TEXT NOT NULL DEFAULT 'active',
    content_hash TEXT NOT NULL,
    created      TEXT NOT NULL,
    updated      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aliases (
    alias     TEXT NOT NULL,
    page_id   TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    canonical INTEGER NOT NULL DEFAULT 0,   -- 1 = primary name for the entity
    PRIMARY KEY (alias, page_id)
);

CREATE TABLE IF NOT EXISTS edges (
    src_page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    dst_page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    rel         TEXT NOT NULL,             -- typed relationship, e.g. part_of, has_module
    created     TEXT NOT NULL,
    PRIMARY KEY (src_page_id, dst_page_id, rel)
);

CREATE TABLE IF NOT EXISTS claims (
    id      TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    text    TEXT NOT NULL,
    source  TEXT NOT NULL,                 -- provenance span
    tier    INTEGER NOT NULL,
    status  TEXT NOT NULL DEFAULT 'active',
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tombstones (
    id              TEXT PRIMARY KEY,      -- slug of the canonical entity
    entity          TEXT NOT NULL,         -- canonical entity name
    canonical_alias TEXT,
    aliases         TEXT NOT NULL DEFAULT '[]',  -- JSON list of all aliases (re-ingest block)
    pages           TEXT NOT NULL DEFAULT '[]',  -- JSON list of pages touched at deprecation
    reason          TEXT NOT NULL,
    source          TEXT,
    created         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    op     TEXT NOT NULL,                  -- ingest | distill | query | deprecate | lint | audit
    target TEXT,                           -- what the op acted on
    detail TEXT                            -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_pages_project ON pages(project);
CREATE INDEX IF NOT EXISTS idx_pages_tier    ON pages(tier);
CREATE INDEX IF NOT EXISTS idx_claims_page   ON claims(page_id);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_edges_src     ON edges(src_page_id);
CREATE INDEX IF NOT EXISTS idx_tombstones_entity ON tombstones(entity);
CREATE INDEX IF NOT EXISTS idx_events_op      ON events(op);
"""
