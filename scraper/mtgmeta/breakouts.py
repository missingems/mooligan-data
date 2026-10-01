"""breakouts/{format}.json: the cards new to a format's metagame, the ones to notice this week.

A card breaks out when the last 7 days' decks play it and the 23 days before barely did: a new release finding a
home, or an old card a new deck picked up. Built from the stored decklists and the snapshot's dates, as
popular-cards/{format}.json is, with what those decks did and which archetypes play the card. See
docs/data-format.md.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .explore import prestige
from .popular import _copies, _deck_ids, _iso, card_kind, deck_dates, is_basic

SCHEMA = 1

# The decks of the last RECENT_DAYS days, set against those from BASELINE_DAYS back to RECENT_DAYS back.
RECENT_DAYS = 7
BASELINE_DAYS = 30
# A card breaks out when at least MIN_DECKS recent decks, and MIN_SHARE percent of them, play it, and its share
# of the recent decks is at least GROWTH times its share of the earlier ones.
MIN_DECKS = 4
MIN_SHARE = 1.0
GROWTH = 3
# With fewer earlier decks than this, everything would look new, so nothing breaks out.
MIN_BASELINE_DECKS = 20
LIMIT = 25
# Archetypes named on each card.
ARCHETYPES = 3

_PLACE = re.compile(r"^(\d+)(?:st|nd|rd|th) Place$")


def build_breakouts(document: dict, deck_cards: Dict[str, dict], catalog: Dict[str, dict], now: datetime) -> dict:
    """The file for one format: `document` is its snapshot, `deck_cards` its stored decklists, `catalog` Scryfall's cards by slug."""
    dates = {deck_id: played for deck_id, played in deck_dates(document).items() if deck_id in deck_cards}
    recent = _deck_ids(dates, now, RECENT_DAYS)
    baseline = _deck_ids(dates, now, BASELINE_DAYS, until=RECENT_DAYS)
    file = {
        "schema": SCHEMA,
        "format": document["format"],
        "generated_at": _iso(now),
        "deck_count": len(recent),
        "baseline_deck_count": len(baseline),
        "cards": [],
    }
    if len(baseline) < MIN_BASELINE_DECKS or not recent:
        return file
    played = {deck_id: _played(deck_cards[deck_id]) for deck_id in recent + baseline}
    results = _results(document)
    recent_decks = _decks_by_card(recent, played)
    baseline_decks = _decks_by_card(baseline, played)
    rows = []
    for card, decks in recent_decks.items():
        known = catalog.get(card)
        if known is None or is_basic(known.get("type_line", "")):
            continue
        share = 100 * len(decks) / len(recent)
        earlier = baseline_decks.get(card, [])
        previous_share = 100 * len(earlier) / len(baseline)
        if len(decks) < MIN_DECKS or share < MIN_SHARE or share < GROWTH * previous_share:
            continue
        rows.append(_row(card, known, decks, earlier, share, previous_share, played, results, dates))
    rows.sort(key=lambda row: (-row["decks"], -row["top8"], row["name"]))
    file["cards"] = rows[:LIMIT]
    return file


def _played(deck: dict) -> Dict[str, bool]:
    """Each card a deck plays, by slug, to whether it is in the mainboard."""
    played = {card: False for card in _copies(deck.get("s", []))}
    played.update({card: True for card in _copies(deck.get("m", []))})
    return played


def _decks_by_card(deck_ids: List[str], played: Dict[str, Dict[str, bool]]) -> Dict[str, List[str]]:
    decks: Dict[str, List[str]] = {}
    for deck_id in deck_ids:
        for card in played[deck_id]:
            decks.setdefault(card, []).append(deck_id)
    return decks


def _results(document: dict) -> Dict[str, Tuple[Optional[str], str, Optional[int], int]]:
    """Each deck's (archetype id, archetype name, place or None for a League record, its event's prestige)."""
    events = {event["event_id"]: event for event in document.get("events", [])}
    names = {archetype_id: archetype.get("name", archetype_id) for archetype_id, archetype in document.get("archetypes", {}).items()}
    results: Dict[str, Tuple[Optional[str], str, Optional[int], int]] = {}
    for event in events.values():
        weight = prestige(event)
        for result in event.get("results", []):
            archetype_id = result.get("archetype_id")
            name = names.get(archetype_id) or result.get("archetype") or ""
            results.setdefault(result["deck_id"], (archetype_id, name, _place(result), weight))
    for archetype_id, archetype in document.get("archetypes", {}).items():
        for result in archetype.get("results", []):
            event = events.get(result.get("event_id"))
            results.setdefault(result["deck_id"], (archetype_id, names[archetype_id], _place(result), prestige(event) if event else 1))
    return results


def _place(result: dict) -> Optional[int]:
    match = _PLACE.match(result.get("finish") or "")
    return int(match.group(1)) if match else None


def _row(card, known, decks, earlier, share, previous_share, played, results, dates) -> dict:
    places = [results[deck_id][2] for deck_id in decks if deck_id in results and results[deck_id][2] is not None]
    archetypes: Dict[str, List] = {}
    for deck_id in decks:
        archetype_id, name, _, _ = results.get(deck_id, (None, "", None, 1))
        if archetype_id:
            archetypes.setdefault(archetype_id, [name, 0])[1] += 1
    name = known["name"]
    row = {
        # Named as in popular-cards: a split card is both its halves, any other double-faced card its front face.
        "name": name if known.get("layout") == "split" else name.split(" // ")[0],
        "oracle_id": known.get("oracle_id"),
        "type": card_kind(known.get("type_line", "")) or "other",
        "decks": len(decks),
        "share": round(share, 1),
        "previous_share": round(previous_share, 1),
        "new": not earlier,
        "first_seen": min(dates[deck_id] for deck_id in decks + earlier).strftime("%Y-%m-%d"),
        "mainboard": sum(1 for deck_id in decks if played[deck_id][card]),
        "top8": sum(1 for place in places if place <= 8),
        "wins": sum(1 for place in places if place == 1),
        "best_prestige": max((results[deck_id][3] for deck_id in decks if deck_id in results), default=None),
        "archetypes": [
            {"id": archetype_id, "name": name, "decks": count}
            for archetype_id, (name, count) in sorted(archetypes.items(), key=lambda item: (-item[1][1], item[0]))[:ARCHETYPES]
        ],
    }
    if known.get("price") is not None:
        row["price"] = known["price"]
    return row
