"""Pull the Aegis daily market-context digest into the brain's raw inbox.

Fetches GET /api/brain/digest from the live deploy and saves it as
raw/market-digests/YYYY-MM-DD.md (idempotent — same-day re-runs overwrite
with the freshest reading). The folder is then ingestible with the normal
folder-ingest pipeline, so "what the engine saw each day" becomes queryable
brain memory:

    python tools/pull_market_digest.py            # fetch today's digest
    python optimus.py ingest raw/market-digests   # (attended) index them

Descriptive context only — the digest never contains buy/sell language.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

BASE = "https://aegis-finance-production.up.railway.app"
OUT_DIR = Path(__file__).resolve().parent.parent / "raw" / "market-digests"


def main() -> int:
    resp = requests.get(f"{BASE}/api/brain/digest", timeout=120)
    resp.raise_for_status()
    data = resp.json()
    date, markdown = data.get("date"), data.get("markdown")
    if not date or not markdown:
        print(f"unexpected payload: {str(data)[:200]}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{date}.md"
    path.write_text(markdown, encoding="utf-8")
    print(f"saved {path} ({len(markdown)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
