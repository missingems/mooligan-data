"""today.json: what matters today in one response, for a Today carousel (not published yet).

Built only from files already published: one interesting card from `breakouts/{format}.json` (a new card seeing
play, else a released card suddenly seeing play) and the day's biggest mover and loser from `movers/all.json`. It
waits on the decision on where /today is served, so nothing calls it yet. See docs/data-format.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .movers import FORMATS

SCHEMA = 1

# The breakout row's fields the interesting card keeps; `price` is missing from a row when the card has none.
CARD_FIELDS = ("name", "oracle_id", "type", "decks", "share", "previous_share", "first_seen", "top8", "wins", "price")
# The mover's fields, as movers/all.json publishes them, without `history`.
MOVER_FIELDS = ("name", "slug", "oracle_id", "scryfall_id", "set", "price", "previous", "change", "percent")
# A format's place when a card's rows tie on decks: the published order, and formats not in it after, alphabetically.
FORMAT_ORDER = {format: place for place, format in enumerate(FORMATS)}


def build_today(breakouts: Dict[str, dict], movers_all: Optional[dict], now: datetime) -> dict:
    """The file: `breakouts` is each format's breakouts document by format id, `movers_all` is movers/all.json (None if missing)."""
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interesting_card": {"card": _interesting_card(breakouts)},
        "movers": _movers(movers_all),
        # No source of card previews exists yet.
        "preview": {"card": None},
    }


def _interesting_card(breakouts: Dict[str, dict]) -> Optional[dict]:
    """One card: a new card seeing play, and only when there is none a released card that suddenly sees play."""
    found: Dict[bool, List[Tuple[str, dict]]] = {True: [], False: []}
    for key, document in breakouts.items():
        format = document.get("format") or key
        for row in document.get("cards") or []:
            found[bool(row.get("new"))].append((format, row))
    for new, kind in ((True, "new_card"), (False, "released_card")):
        if found[new]:
            format, row = _pick(found[new])
            return {"kind": kind, "format": format, **{field: row[field] for field in CARD_FIELDS if field in row}}
    return None


def _pick(entries: List[Tuple[str, dict]]) -> Tuple[str, dict]:
    """The card that matches in the most formats (a real release is new in several at once), shown as its busiest format's row."""
    cards: Dict[str, List[Tuple[str, dict]]] = {}
    for format, row in entries:
        cards.setdefault(row.get("oracle_id") or row.get("name", ""), []).append((format, row))
    identity = min(cards, key=lambda card: _rank(card, cards[card]))
    return min(cards[identity], key=_home)


def _rank(identity: str, rows: List[Tuple[str, dict]]) -> tuple:
    """Most formats, then most decks and top 8s over them, then name."""
    return (
        -len({format for format, _ in rows}),
        -sum(row.get("decks", 0) for _, row in rows),
        -sum(row.get("top8", 0) for _, row in rows),
        rows[0][1].get("name", ""),
        identity,
    )


def _home(entry: Tuple[str, dict]) -> tuple:
    """Most decks, then the format's place in the published order (formats not in it after, alphabetically)."""
    format, row = entry
    return (-row.get("decks", 0), FORMAT_ORDER.get(format, len(FORMAT_ORDER)), format if format not in FORMAT_ORDER else "")


def _movers(movers_all: Optional[dict]) -> dict:
    """The last day's biggest gainer and biggest loser of movers/all.json, as published; never the week or the month."""
    day = ((movers_all or {}).get("windows") or {}).get("1d") or {}
    return {
        "price_day": (movers_all or {}).get("price_day"),
        "mover": _first(day.get("gainers")),
        "loser": _first(day.get("losers")),
    }


def _first(rows: Optional[list]) -> Optional[dict]:
    return {field: rows[0][field] for field in MOVER_FIELDS if field in rows[0]} if rows else None


def read_published(directory: Path) -> Tuple[Dict[str, dict], Optional[dict]]:
    """The breakouts documents by format id and movers/all.json from a work directory; a file not there is left out."""
    breakouts = {path.stem: json.loads(path.read_text()) for path in sorted((directory / "breakouts").glob("*.json"))}
    path = directory / "movers" / "all.json"
    return breakouts, json.loads(path.read_text()) if path.exists() else None


def write_today(directory: Path, now: datetime) -> List[str]:
    """Builds today.json from the published files in `directory`, writes it there and returns its path."""
    breakouts, movers_all = read_published(directory)
    (directory / "today.json").write_text(json.dumps(build_today(breakouts, movers_all, now), ensure_ascii=False, separators=(",", ":")))
    return ["today.json"]
