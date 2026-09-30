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

# "1st Place" and so on: a league's "5-0" is a record, not a placing.
_PLACE = re.compile(r"^(\d+)(?:st|nd|rd|th) Place$")
# Names from MTGGoldfish end in the event's date, which the entry carries on its own.
_TRAILING_DATE = re.compile(r"\s+\d{4}-\d{2}-\d{2}$")
# The latest event is a recent one without the winner's player.
_LATEST_KEYS = ("name", "date", "kind", "source", "url", "deck_count", "winner_archetype")


def build_explore(snapshots: Dict[str, dict], now: datetime) -> dict:
    """The document for every format in `snapshots` (format -> the snapshot's own document)."""
    formats = []
    for format, name in FORMATS:
        snapshot = snapshots.get(format)
        if snapshot is None:
            continue
        events = _recent_events(snapshot.get("events", []), now)
        latest = next((event for event in events if event["winner_archetype"]), events[0] if events else None)
        formats.append(
            {
                "format": format,
                "name": name,
                "latest_event": {key: latest[key] for key in _LATEST_KEYS} if latest else None,
                "standings": _standings(snapshot, now),
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
                "key_cards": [
                    {"name": card["name"], "oracle_id": card.get("oracle_id")}
                    for card in archetype.get("key_cards", [])[:KEY_CARDS]
                ],
            }
        )
    return standings


def _places(results: List[dict], since: datetime, now: datetime) -> List[int]:
    """The placings among an archetype's results in the window, leaving out league records and dates yet to come."""
    places = []
    for result in results:
        match = _PLACE.match(result["finish"])
        if match and since <= _parse(result["date"]) and _parse(result["date"]).date() <= now.date():
            places.append(int(match.group(1)))
    return places


def _recent_events(events: List[dict], now: datetime) -> List[dict]:
    # MTGGoldfish lists at least one result dated months ahead (an event still to be played).
    past = [event for event in events if _parse(event["date"]).date() <= now.date()]
    past.sort(key=lambda event: (event["date"], int(event["event_id"]) if event["event_id"].isdigit() else 0), reverse=True)
    recent = []
    for event in past[:RECENT_EVENTS]:
        winner = next((result for result in event["results"] if result["finish"] == "1st Place"), None)
        recent.append(
            {
                "name": _TRAILING_DATE.sub("", event["event_name"]),
                "date": event["date"][:10],
                "kind": event.get("kind", "other"),
                "source": event.get("source"),
                "url": event["url"],
                "deck_count": len(event["results"]),
                "winner_archetype": winner["archetype"] if winner else None,
                "winner_player": winner["player"] if winner else None,
            }
        )
    return recent


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
