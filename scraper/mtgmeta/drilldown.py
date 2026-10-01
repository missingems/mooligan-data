"""archetypes/{id}.json and events/{id}.json: what the app opens from an Explore row.

explore.json shows a format's top archetypes and latest events. These files are
one level down: an archetype's recent decks, and an event's whole standings,
each row linking on to `decks/{deck_id}.json`. Built from the snapshot a run
just wrote, so they are never older than it. See docs/data-format.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

from .explore import WINDOWS, Previews, archetype_tiles, deck_key_cards, key_cards, name_without_date, prestige

ARCHETYPE_DECKS = 60
ARCHETYPE_KEY_CARDS = 3


def build_archetype_pages(
    snapshot: dict,
    now: datetime,
    deck_ids: Set[str],
    decks: Optional[Dict[str, dict]] = None,
    catalog: Optional[Dict[str, dict]] = None,
) -> Dict[str, dict]:
    """A page per archetype in the format's metagame (any window), by archetype id.

    `deck_ids` are the decklists published, which is what each deck's `published` says. A tile
    that shows no key cards takes them from the archetype's featured deck instead, when `decks`
    (the format's stored deck contents) has it and `catalog` (the card catalog) knows its cards, and
    one that shows no colours takes the colours of that deck.
    """
    meta = snapshot.get("meta", {})
    previews = Previews(meta, decks, catalog, snapshot.get("archetypes", {}))
    shares = {
        window: {tile["id"]: tile["percentage"] for tile in meta.get(window, {}).get("archetypes", [])}
        for window, _, _ in WINDOWS
    }
    today = _today(now)
    pages = {}
    for archetype_id, tile in archetype_tiles(meta).items():
        archetype = snapshot.get("archetypes", {}).get(archetype_id, {})
        results = archetype.get("results", [])
        cards = key_cards(tile, ARCHETYPE_KEY_CARDS)
        featured = (decks or {}).get(archetype.get("deck_id"))
        if not cards and featured:
            cards = deck_key_cards(featured.get("m", []), catalog or {}, tile["name"], ARCHETYPE_KEY_CARDS)
        # Stable, so results of one day keep the order the snapshot has them in.
        past = sorted((result for result in results if result["date"][:10] <= today), key=lambda result: result["date"], reverse=True)
        pages[archetype_id] = {
            "id": archetype_id,
            "name": tile["name"],
            "format": snapshot["format"],
            "colors": previews.tile_colors(tile),
            "key_cards": cards,
            "shares": {
                window: round(shares[window][archetype_id], 1) if archetype_id in shares[window] else None
                for window, _, _ in WINDOWS
            },
            "decks": [
                {
                    "deck_id": result["deck_id"],
                    "date": result["date"][:10],
                    "event_id": result.get("event_id"),
                    "event_name": name_without_date(result["event_name"], result["date"][:10]),
                    "finish": result["finish"],
                    "player": result["player"],
                    "published": result["deck_id"] in deck_ids,
                }
                for result in past[:ARCHETYPE_DECKS]
            ],
        }
    return pages


def build_event_pages(
    snapshot: dict,
    now: datetime,
    deck_ids: Set[str],
    decks: Optional[Dict[str, dict]] = None,
    catalog: Optional[Dict[str, dict]] = None,
) -> Dict[str, dict]:
    """A page per event in the snapshot dated today or earlier, by event id.

    `decks` is the format's stored deck contents and `catalog` the card catalog, as in
    `build_explore`: a result whose archetype has no key cards takes its own deck's, and its
    `colors` are the event page's, else its deck's, else its archetype's.
    """
    previews = Previews(snapshot.get("meta", {}), decks, catalog, snapshot.get("archetypes", {}))
    today = _today(now)
    pages = {}
    for event in snapshot.get("events", []):
        if event["date"][:10] > today:
            continue
        pages[event["event_id"]] = {
            "id": event["event_id"],
            "name": name_without_date(event["event_name"], event["date"][:10]),
            "date": event["date"][:10],
            "kind": event.get("kind", "other"),
            "prestige": prestige(event),
            "source": event.get("source"),
            "url": event["url"],
            "format": snapshot["format"],
            "results": [
                {
                    "finish": result["finish"],
                    "player": result["player"],
                    "archetype": result["archetype"],
                    "archetype_id": result.get("archetype_id"),
                    "deck_id": result["deck_id"],
                    "published": result["deck_id"] in deck_ids,
                    "colors": previews.colors(result),
                    "key_cards": previews.key_cards(result),
                }
                for result in event["results"]
            ],
        }
    return pages


def _today(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")
