"""explore.json: what the app's Explore tab opens with, built from the snapshots.

One small file for the six main formats (the top of the metagame, and the latest
events with their winners), so the tab doesn't download a snapshot per format
before it can show anything. See docs/data-format.md.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

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
RECENT_EVENTS = 20
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
_LATEST_KEYS = ("id", "name", "date", "kind", "source", "url", "deck_count", "result_count", "winner_archetype", "lead")
# Which window's tile an archetype's colours and key cards are read from: the longest first.
TILE_WINDOWS = ("30d", "14d", "7d")


def build_explore(snapshots: Dict[str, dict], now: datetime) -> dict:
    """The document for every format in `snapshots` (format -> the snapshot's own document)."""
    formats = []
    for format, name in FORMATS:
        snapshot = snapshots.get(format)
        if snapshot is None:
            continue
        events = _recent_events(snapshot.get("events", []), now, archetype_tiles(snapshot.get("meta", {})))
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


def result_key_cards(archetype_id: Optional[str], tiles: Dict[str, dict]) -> List[dict]:
    """The first two key cards of a result's archetype, empty when the archetype isn't tracked or its tile shows none."""
    tile = tiles.get(archetype_id) if archetype_id else None
    return key_cards(tile) if tile else []


def _places(results: List[dict], since: datetime, now: datetime) -> List[int]:
    """The placings among an archetype's results in the window, leaving out league records and dates yet to come."""
    places = []
    for result in results:
        match = _PLACE.match(result["finish"])
        if match and since <= _parse(result["date"]) and _parse(result["date"]).date() <= now.date():
            places.append(int(match.group(1)))
    return places


def _recent_events(events: List[dict], now: datetime, tiles: Dict[str, dict]) -> List[dict]:
    # MTGGoldfish lists at least one result dated months ahead (an event still to be played).
    past = [event for event in events if _parse(event["date"]).date() <= now.date()]
    past.sort(key=lambda event: (event["date"], int(event["event_id"]) if event["event_id"].isdigit() else 0), reverse=True)
    recent = []
    for event in past[:RECENT_EVENTS]:
        winner = next((result for result in event["results"] if result["finish"] == "1st Place"), None)
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
                "lead": _lead(event["results"], winner, tiles),
            }
        )
    return recent


def _lead(results: List[dict], winner: Optional[dict], tiles: Dict[str, dict]) -> Optional[dict]:
    """The result an event row shows: the winner, or the first listed result for an event with none (a League)."""
    lead = winner or (results[0] if results else None)
    if lead is None:
        return None
    return {
        "finish": lead["finish"],
        "archetype": lead["archetype"],
        "archetype_id": lead.get("archetype_id"),
        "player": lead["player"],
        "deck_id": lead["deck_id"],
        "key_cards": result_key_cards(lead.get("archetype_id"), tiles),
    }


def name_without_date(name: str, date: str) -> str:
    """MTGGoldfish puts the event's date in its name ("Modern League 2026-09-29 (1)"); the entry has it on its own."""
    return re.sub(r"\s{2,}", " ", name.replace(date, " ")).strip() or name


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
