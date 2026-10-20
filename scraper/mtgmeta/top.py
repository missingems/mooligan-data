"""edh/top.json: EDHREC's ranked top 100 commanders for the past week and the past month, with each one's share.

A commander's `share` is its decks as a percent of all the decks of its window's top 100, not of every Commander
deck. Its Scryfall ids and colour identity come from the card catalog, by name; a partner pair ("A // B") is no one
card, so it has no ids, and its colour identity is both halves' together. EDHREC's data, used with their
permission. See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .cards import slug as card_slug
from .colors import COLORS

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "edh/top.json"


def build_top(windows: Dict[str, List[dict]], now: datetime, catalog: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    """The file for the windows read (see `Edhrec.top_commanders`); None when none was."""
    if not windows:
        return None
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windows": {window: _window(rows, catalog or {}) for window, rows in windows.items()},
    }


def top_slugs(windows: Dict[str, List[dict]]) -> List[str]:
    """Every listed commander's slug, the first window's first and each once."""
    return list(dict.fromkeys(row["slug"] for rows in windows.values() for row in rows))


def write_top(directory: Path, windows: Dict[str, List[dict]], now: datetime, catalog: Optional[Dict[str, dict]] = None) -> List[str]:
    """Writes edh/top.json and returns its path; writes nothing, so the published file stays, when no window was read."""
    document = build_top(windows, now, catalog)
    if document is None:
        return []
    path = directory / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    log.info("EDHREC top commanders: %s", ", ".join(f"{window} {len(rows)}" for window, rows in windows.items()))
    return [PATH]


def _window(rows: Sequence[dict], catalog: Dict[str, dict]) -> dict:
    decks = sum(row["decks"] for row in rows)
    return {
        "decks": decks,
        "commanders": [
            {
                "rank": row["rank"],
                "slug": row["slug"],
                "name": row["name"],
                "decks": row["decks"],
                "share": round(row["decks"] * 100 / decks, 1) if decks else 0.0,
                **_card(row["name"], catalog),
                "trend": row["trend"],
            }
            for row in rows
        ],
    }


def _card(name: str, catalog: Dict[str, dict]) -> dict:
    """The commander's colour identity and ids, null for what the catalog does not know."""
    entry = catalog.get(card_slug(name))
    if "//" in name and (not entry or entry.get("name") != name):
        halves = [catalog.get(card_slug(half)) for half in name.split("//")]
        known = all(half and "color_identity" in half for half in halves)
        colors = {letter for half in halves for letter in half["color_identity"]} if known else None
        return {"color_identity": sorted(colors, key=COLORS.index) if known else None, "oracle_id": None, "scryfall_id": None}
    entry = entry or {}
    return {
        "color_identity": entry.get("color_identity"),
        "oracle_id": entry.get("oracle_id"),
        "scryfall_id": entry.get("scryfall_id"),
    }
