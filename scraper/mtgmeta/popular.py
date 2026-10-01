"""popular-cards/{format}.json: the cards a format's recent decks play most, per window and per kind of card.

Built from the stored decklists and the dates the snapshot gives them, so it is never older than the
snapshot it was built with. Every deck dated inside a window counts once, unweighted, and so does a deck that
only an archetype's results mention (big paper events are published there only). See docs/data-format.md.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from .cards import slug

SCHEMA = 1

# What a card is, in the order that decides it when its type line has several ("Artifact Creature" is a creature,
# "Artifact Land" a land).
KINDS = ("creature", "planeswalker", "battle", "land", "instant", "sorcery", "artifact", "enchantment")
# The lists of a window, in the order they are published; `all` and `sideboard` come from the boards.
LISTS = ("all", "creature", "planeswalker", "instant", "sorcery", "artifact", "enchantment", "battle", "land", "sideboard")
# Cards in `all`, and in each other list.
ALL_LIMIT = 50
LIST_LIMIT = 25
# A card must be in at least this many decks, and in at least this percent of the window's.
MIN_DECKS = 2
MIN_PERCENT = 1
# Each window with the two periods its trend sets against each other: the card's share of the decks in the last
# `recent` days against its share in the days from `baseline` back to `recent` back. The 30-day window has no longer
# one to compare with, so it sets the last week against the 23 days before it.
WINDOWS = (
    ("7d", 7, 7, 14),
    ("14d", 14, 14, 28),
    ("30d", 30, 7, 30),
)
# A card's share must move by more than this many points, and by more than this many standard errors (a
# two-proportion z-score, so a small period can't call a trend off a few decks), to be a trend.
TREND_POINTS = 5
TREND_Z = 3

_slug = lru_cache(maxsize=None)(slug)


def _types(type_line: str) -> set:
    """The words of the front face's type line before the "—", lower-cased: {"legendary", "artifact", "creature"}."""
    front = type_line.split("//")[0].split("—")[0]
    return set(re.findall(r"[a-z]+", front.lower()))


def card_kind(type_line: str) -> Optional[str]:
    """Which list a card belongs to, from its type line: the first of `KINDS` among its types, None for none of them.

    Only the front face counts, as it does for the deck, so a double-faced spell with a land on the back is a spell
    and a split card is its first half. Subtypes don't count ("Creature — Elemental Landwalker" is no land), and
    "Kindred" and "Tribal" only add a type that is looked at ("Kindred Instant — Lesson" is an instant).
    """
    types = _types(type_line)
    return next((kind for kind in KINDS if kind in types), None)


def is_basic(type_line: str) -> bool:
    """Whether the front face is a basic: the five basic lands, Wastes and every Snow-Covered one have the Basic supertype."""
    return "basic" in _types(type_line)


def deck_dates(document: dict) -> Dict[str, datetime]:
    """When each deck the snapshot dates was played: its event's date, else its archetype result's.

    A featured deck (an archetype's `deck_id`) has no date unless it is also a result, so it isn't here.
    """
    dates: Dict[str, datetime] = {}
    for event in document.get("events", []):
        played = _parse(event["date"])
        for result in event.get("results", []):
            dates.setdefault(result["deck_id"], played)
    for archetype in document.get("archetypes", {}).values():
        for result in archetype.get("results", []):
            dates.setdefault(result["deck_id"], _parse(result["date"]))
    return dates


def build_popular_cards(document: dict, deck_cards: Dict[str, dict], catalog: Dict[str, dict], now: datetime) -> dict:
    """The file for one format: `document` is its snapshot, `deck_cards` its stored decklists (deck id -> `{"m": [[quantity, name], ...], "s": ...}`).

    `catalog` (slug -> `{"name", "oracle_id", "type_line", "layout", ...}`, see `scryfall.card_catalog`) names each
    card and says what it is. A card it doesn't know is left out, and so is a basic, and a card whose type line is
    none of the `KINDS`.
    """
    dates = {deck_id: played for deck_id, played in deck_dates(document).items() if deck_id in deck_cards}
    counts = {deck_id: (_copies(deck_cards[deck_id].get("m", [])), _copies(deck_cards[deck_id].get("s", []))) for deck_id in dates}
    windows = {}
    for name, days, recent, baseline in WINDOWS:
        in_window = _deck_ids(dates, now, days)
        # A window that is its own recent period needs no second list of decks.
        recent_ids = in_window if recent == days else _deck_ids(dates, now, recent)
        baseline_ids = _deck_ids(dates, now, baseline, until=recent)
        boards = []
        for board in (0, 1):
            tally = _tally(in_window, counts, board)
            recent_tally = tally if recent_ids is in_window else _tally(recent_ids, counts, board)
            boards.append(
                _rows(tally, len(in_window), catalog, (len(recent_ids), recent_tally), (len(baseline_ids), _tally(baseline_ids, counts, board)))
            )
        main, side = boards
        lists = [{"kind": "all", "cards": main[:ALL_LIMIT]}]
        lists += [{"kind": kind, "cards": [row for row in main if row["type"] == kind][:LIST_LIMIT]} for kind in LISTS[1:-1]]
        lists.append({"kind": "sideboard", "cards": side[:LIST_LIMIT]})
        windows[name] = {"deck_count": len(in_window), "lists": [one for one in lists if one["cards"]]}
    return {"schema": SCHEMA, "format": document["format"], "generated_at": _iso(now), "windows": windows}


def trend(recent: int, recent_total: int, baseline: int, baseline_total: int) -> Optional[str]:
    """"up" or "down" when a card's share of the decks moved between two periods, else None.

    `recent` of `recent_total` decks play it now, `baseline` of `baseline_total` did before. It moved when the
    share changed by more than `TREND_POINTS` points and a two-proportion z-score is above `TREND_Z`, which
    keeps a card seen in a handful of decks from trending on chance. No trend without decks in both periods.
    """
    if not recent_total or not baseline_total:
        return None
    pooled = (recent + baseline) / (recent_total + baseline_total)
    if pooled <= 0 or pooled >= 1:
        return None
    # The move in shares, scaled by both totals so the points can be compared in whole numbers: exactly 5 points is no trend.
    moved = recent * baseline_total - baseline * recent_total
    if abs(moved) * 100 <= TREND_POINTS * recent_total * baseline_total:
        return None
    error = math.sqrt(pooled * (1 - pooled) * (1 / recent_total + 1 / baseline_total))
    if abs(moved / (recent_total * baseline_total)) / error > TREND_Z:
        return "up" if moved > 0 else "down"
    return None


def _rows(
    tally: Dict[str, List[int]],
    total: int,
    catalog: Dict[str, dict],
    recent: Tuple[int, Dict[str, List[int]]],
    baseline: Tuple[int, Dict[str, List[int]]],
) -> List[dict]:
    """The cards of one board that clear the floor, most decks first: then most copies, then name.

    `tally` is the window's and `total` its decks; `recent` and `baseline` are each period's deck count and
    tally, which the trends compare.
    """
    rows = []
    for card, (decks, copies) in tally.items():
        if decks < MIN_DECKS or 100 * decks / total < MIN_PERCENT:
            continue
        known = catalog.get(card)
        if known is None:
            continue
        type_line = known.get("type_line", "")
        kind = card_kind(type_line)
        if kind is None or is_basic(type_line):
            continue
        name = known["name"]
        rows.append(
            {
                # A split card is both its halves, "Fire // Ice"; any other double-faced or adventure card is its front face.
                "name": name if known.get("layout") == "split" else name.split(" // ")[0],
                "oracle_id": known.get("oracle_id"),
                "type": kind,
                "decks": decks,
                "share": round(100 * decks / total, 1),
                "copies": round(copies / decks, 1),
                "trend": trend(recent[1].get(card, [0])[0], recent[0], baseline[1].get(card, [0])[0], baseline[0]),
            }
        )
    # The copies as shown, so cards shown alike come in name order.
    rows.sort(key=lambda row: (-row["decks"], -row["copies"], row["name"]))
    return rows


def _copies(board: list) -> Dict[str, int]:
    """Copies of each card on a board by slug, a card the list names twice added up."""
    copies: Dict[str, int] = {}
    for quantity, name in board:
        key = _slug(name)
        copies[key] = copies.get(key, 0) + quantity
    return copies


def _tally(deck_ids: List[str], counts: Dict[str, tuple], board: int) -> Dict[str, List[int]]:
    """Each card on a board (0 mainboard, 1 sideboard) to `[decks that play it, copies in them]`."""
    tally: Dict[str, List[int]] = {}
    for deck_id in deck_ids:
        for card, quantity in counts[deck_id][board].items():
            entry = tally.setdefault(card, [0, 0])
            entry[0] += 1
            entry[1] += quantity
    return tally


def _deck_ids(dates: Dict[str, datetime], now: datetime, days: int, until: int = 0) -> List[str]:
    """The decks dated from `days` days before `now` up to `until` days before it (or up to today, with no `until`).

    As the Top 8 counts in explore.json take their days: `now - days` itself is in, and with no `until` so is every
    date up to the end of today, but not one dated ahead.
    """
    since = now - timedelta(days=days)
    if until:
        end = now - timedelta(days=until)
        return [deck_id for deck_id, played in dates.items() if since <= played < end]
    return [deck_id for deck_id, played in dates.items() if since <= played and played.date() <= now.date()]


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
