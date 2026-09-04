"""Every ingest source must be registered in PROJECT_DOMAIN.

Found 2026-09-04 (Fable 5.1 review): `aegis-docs` (432 pages), `aat-docs`
(102), `aegis-module-docs` (65) and `aegis-health` (1) — 600 of 1,015 pages —
were ingested by tools/refresh_aegis.py but absent from core/domains.py.
An unregistered project is UNSCOPED, which `rank_for` sorts BELOW every
in-domain page, so on a `domain="finance"` query the largest body of finance
knowledge in the brain could never out-rank a smaller in-domain page.

This test reads the source list and the domain map so the next new source
fails loudly here instead of silently demoting itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import domains  # noqa: E402
from tools import refresh_aegis  # noqa: E402


def _slug_from_source(channel: str, source: str, override: str | None) -> str:
    if override:
        return override
    # git channel: slug derives from the folder name (core.ingest convention)
    return Path(source).name.lower().replace(" ", "-")


def test_every_refresh_source_is_domain_registered():
    missing = []
    for channel, source, override in refresh_aegis.SOURCES:
        slug = _slug_from_source(channel, source, override)
        if domains.domain_for(slug) == domains.UNSCOPED:
            missing.append(slug)
    assert not missing, (
        f"unregistered project slugs (add to core/domains.py PROJECT_DOMAIN): {missing}"
    )


def test_the_four_orphans_of_2026_09_04_are_finance():
    for slug in ("aegis-docs", "aat-docs", "aegis-module-docs", "aegis-health"):
        assert domains.domain_for(slug) == domains.FINANCE, slug
