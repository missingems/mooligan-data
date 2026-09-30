"""explore.json: what the app's Explore tab opens with, built from the snapshots.

One small file for the six main formats (the top of the metagame, and the latest
events with their winners), so the tab doesn't download a snapshot per format
before it can show anything. See docs/data-format.md.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from .cards import slug

# In the order the tab shows them.
FORMATS = (
    ("standard", "Standard"),
    ("pioneer", "Pioneer"),
    ("modern", "Modern"),
    ("legacy", "Legacy"),
    ("pauper", "Pauper"),
    ("vintage", "Vintage"),
)
STANDINGS = 8
KEY_CARDS = 2
# Results listed in an event's `top`.
TOP_RESULTS = 3
# Newest events per format. Modern alone has about four a day (Challenges, a League, more),
# so this is about a week of it; every kind counts, Leagues included.
RECENT_EVENTS = 30
WINDOW_DAYS = 30
# Each meta window, with the two windows whose shares its trend compares: the
# archetype's share in the first against its share in the second. The 30-day
# list has no longer window to compare with, so it sets the last week against
# the month, as `share_7d` against `share_30d` does.
WINDOWS = (
    ("7d", "7d", "14d"),
    ("14d", "14d", "30d"),
    ("30d", "7d", "30d"),
)
# A move of more than this many points of share (in tenths, as shown) is a trend.
TREND_TENTHS = 10

# "1st Place" and so on: a league's "5-0" is a record, not a placing.
_PLACE = re.compile(r"^(\d+)(?:st|nd|rd|th) Place$")
# The latest event is a recent one without the winner's player.
_LATEST_KEYS = ("id", "name", "date", "kind", "source", "url", "deck_count", "result_count", "winner_archetype", "lead", "top")
# Which window's tile an archetype's colours and key cards are read from: the longest first.
TILE_WINDOWS = ("30d", "14d", "7d")


def build_explore(
    snapshots: Dict[str, dict],
    now: datetime,
    decks: Optional[Dict[str, Dict[str, dict]]] = None,
    catalog: Optional[Dict[str, dict]] = None,
) -> dict:
    """The document for every format in `snapshots` (format -> the snapshot's own document).

    `decks` (format -> deck id -> the stored `{"m": [[quantity, name], ...], "s": ...}`) and
    `catalog` (slug -> `{"name", "oracle_id", "land"}`) give a result its key cards from its own
    deck when its archetype has none; without them that result's `key_cards` stay empty.
    """
    formats = []
    for format, name in FORMATS:
        snapshot = snapshots.get(format)
        if snapshot is None:
            continue
        previews = Previews(snapshot.get("meta", {}), (decks or {}).get(format), catalog)
        events = _recent_events(snapshot.get("events", []), now, previews)
        latest = next((event for event in events if event["winner_archetype"]), events[0] if events else None)
        formats.append(
            {
                "format": format,
                "name": name,
                "latest_event": {key: latest[key] for key in _LATEST_KEYS} if latest else None,
                "standings": _standings(snapshot, now),
                "standings_by_window": _standings_by_window(snapshot.get("meta", {})),
                "recent_events": events,
            }
        )
    return {"generated_at": _iso(now), "formats": formats}


def _standings(snapshot: dict, now: datetime) -> List[dict]:
    meta = snapshot.get("meta", {})
    month = meta.get("30d", {}).get("archetypes", [])
    week = {archetype["id"]: archetype for archetype in meta.get("7d", {}).get("archetypes", [])}
    since = now - timedelta(days=WINDOW_DAYS)
    standings = []
    # sorted() is stable, so equal shares keep MTGGoldfish's order.
    for archetype in sorted(month, key=lambda archetype: archetype["percentage"], reverse=True)[:STANDINGS]:
        places = _places(snapshot.get("archetypes", {}).get(archetype["id"], {}).get("results", []), since, now)
        in_week = week.get(archetype["id"])
        standings.append(
            {
                "id": archetype["id"],
                "name": archetype["name"],
                "share_30d": round(archetype["percentage"], 1),
                "share_7d": round(in_week["percentage"], 1) if in_week else None,
                "deck_count_30d": archetype.get("deck_count"),
                "top8_30d": sum(1 for place in places if place <= 8),
                "wins_30d": sum(1 for place in places if place == 1),
                "colors": list(archetype.get("colors", [])),
                "key_cards": key_cards(archetype),
            }
        )
    return standings


def _standings_by_window(meta: dict) -> Dict[str, List[dict]]:
    """The top archetypes of each window by that window's own share, and which way each is moving."""
    shares = {
        window: {archetype["id"]: archetype["percentage"] for archetype in meta.get(window, {}).get("archetypes", [])}
        for window, _, _ in WINDOWS
    }
    by_window = {}
    for window, recent, baseline in WINDOWS:
        archetypes = meta.get(window, {}).get("archetypes", [])
        by_window[window] = [
            {
                "id": archetype["id"],
                "name": archetype["name"],
                "share": round(archetype["percentage"], 1),
                "deck_count": archetype.get("deck_count"),
                "trend": _trend(shares[recent].get(archetype["id"]), shares[baseline].get(archetype["id"])),
                "colors": list(archetype.get("colors", [])),
                "key_cards": key_cards(archetype),
            }
            for archetype in sorted(archetypes, key=lambda archetype: archetype["percentage"], reverse=True)[:STANDINGS]
        ]
    return by_window


def _trend(recent: Optional[float], baseline: Optional[float]) -> Optional[str]:
    """'up' or 'down' when the shares, as shown to one decimal, differ by more than a point; None when either is missing."""
    if recent is None or baseline is None:
        return None
    change = round(recent * 10) - round(baseline * 10)
    if change > TREND_TENTHS:
        return "up"
    if change < -TREND_TENTHS:
        return "down"
    return None


def archetype_tiles(meta: dict) -> Dict[str, dict]:
    """Each archetype in the metagame's windows by id, as its tile in the longest window that shows it.

    A tile in a shorter window stands in when the longer one has no key cards.
    """
    tiles: Dict[str, dict] = {}
    for window in TILE_WINDOWS:
        for tile in meta.get(window, {}).get("archetypes", []):
            kept = tiles.get(tile["id"])
            if kept is None or (not kept.get("key_cards") and tile.get("key_cards")):
                tiles[tile["id"]] = tile
    return tiles


def key_cards(archetype: dict, limit: int = KEY_CARDS) -> List[dict]:
    return [
        {"name": card["name"], "oracle_id": card.get("oracle_id")}
        for card in archetype.get("key_cards", [])[:limit]
    ]


class Previews:
    """The key cards a result shows: two cards, so every result has something to draw.

    They are the first two of the result's archetype's tile in the format's metagame. A result
    whose archetype is untracked, has left the metagame or has no tile gets two cards of its own
    deck instead (see `deck_key_cards`), when that deck's contents are known.
    """

    def __init__(self, meta: dict, decks: Optional[Dict[str, dict]] = None, catalog: Optional[Dict[str, dict]] = None) -> None:
        self._tiles = archetype_tiles(meta)
        self._decks = decks or {}
        self._catalog = catalog or {}

    def key_cards(self, result: dict) -> List[dict]:
        archetype_id = result.get("archetype_id")
        tile = self._tiles.get(archetype_id) if archetype_id else None
        cards = key_cards(tile) if tile else []
        if cards:
            return cards
        deck = self._decks.get(result["deck_id"])
        return deck_key_cards(deck.get("m", []), self._catalog, result.get("archetype") or "") if deck else []


def deck_key_cards(mainboard: Sequence[Sequence], catalog: Dict[str, dict], archetype: str = "", limit: int = KEY_CARDS) -> List[dict]:
    """Which cards of a deck stand for it: its mainboard's non-lands, as `[quantity, name]` pairs, picked in this order.

    1. The namesake: a card whose name shares a word of four or more letters with the archetype's
       name ("Beanstalk Control" picks a card with "Beanstalk" in it). One card, the best ranked of them.
    2. The most played: most copies first, so the four-ofs come before the singletons.
    3. Ties in copies go to the card with the higher price (the catalog's `price`, Scryfall's USD for the
       card), a card with no price ranks below any priced one, and equal prices (or none) to the higher
       `mana_value`. A last tie keeps the decklist's order.

    Copies of a name add up. A card the catalog doesn't know is left out: it can't be told from a land, and
    it has no oracle id to show. Each is `{"name", "oracle_id"}`, the name as the decklist writes it.
    """
    copies: Dict[str, int] = {}
    for quantity, name in mainboard:
        copies[name] = copies.get(name, 0) + quantity
    ranked = []
    for name, count in copies.items():
        known = catalog.get(slug(name))
        if known and not known.get("land"):
            ranked.append((count, known.get("price", -1), known.get("mana_value", 0), name, known.get("oracle_id")))
    # sorted() is stable, so a full tie keeps the decklist's order.
    ranked.sort(key=lambda card: card[:3], reverse=True)
    words = _words(archetype)
    namesake = next((card for card in ranked if words & _words(card[3].split("/")[0])), None)
    chosen = ([namesake] if namesake else []) + [card for card in ranked if card is not namesake]
    return [{"name": name, "oracle_id": oracle_id} for _, _, _, name, oracle_id in chosen[:limit]]


def _words(text: str) -> set:
    """The words of four or more letters in a name, lower-cased ("Goryo's Vengeance" has goryo and vengeance)."""
    return {word.lower() for word in re.findall(r"[^\W\d_]{4,}", text)}


def _places(results: List[dict], since: datetime, now: datetime) -> List[int]:
    """The placings among an archetype's results in the window, leaving out league records and dates yet to come."""
    places = []
    for result in results:
        match = _PLACE.match(result["finish"])
        if match and since <= _parse(result["date"]) and _parse(result["date"]).date() <= now.date():
            places.append(int(match.group(1)))
    return places


def _recent_events(events: List[dict], now: datetime, previews: Previews) -> List[dict]:
    # MTGGoldfish lists at least one result dated months ahead (an event still to be played).
    past = [event for event in events if _parse(event["date"]).date() <= now.date()]
    past.sort(key=lambda event: (event["date"], int(event["event_id"]) if event["event_id"].isdigit() else 0), reverse=True)
    recent = []
    for event in past[:RECENT_EVENTS]:
        winner = next((result for result in event["results"] if result["finish"] == "1st Place"), None)
        top = _top(event["results"], previews)
        recent.append(
            {
                "id": event["event_id"],
                "name": name_without_date(event["event_name"], event["date"][:10]),
                "date": event["date"][:10],
                "kind": event.get("kind", "other"),
                "source": event.get("source"),
                "url": event["url"],
                "deck_count": len(event["results"]),
                "result_count": len(event["results"]),
                "winner_archetype": winner["archetype"] if winner else None,
                "winner_player": winner["player"] if winner else None,
                "lead": top[0] if top else None,
                "top": top,
            }
        )
    return recent


def _top(results: List[dict], previews: Previews) -> List[dict]:
    """The first three results in finish order: placings by place, then the rest as listed (a League's records).

    The first is the event's lead: its winner, or, with no 1st place, the first result listed.
    """
    ordered = sorted(results, key=_place)[:TOP_RESULTS]
    return [
        {
            "finish": result["finish"],
            "archetype": result["archetype"],
            "archetype_id": result.get("archetype_id"),
            "player": result["player"],
            "deck_id": result["deck_id"],
            "key_cards": previews.key_cards(result),
        }
        for result in ordered
    ]


def _place(result: dict) -> float:
    match = _PLACE.match(result["finish"])
    return int(match.group(1)) if match else float("inf")


def name_without_date(name: str, date: str) -> str:
    """MTGGoldfish puts the event's date in its name ("Modern League 2026-09-29 (1)"); the entry has it on its own."""
    return re.sub(r"\s{2,}", " ", name.replace(date, " ")).strip() or name


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
