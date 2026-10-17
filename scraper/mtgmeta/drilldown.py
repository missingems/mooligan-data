"""archetypes/{id}.json and events/{id}.json: what the app opens from an Explore row.

explore.json shows a format's top archetypes and latest events. These files are
one level down: an archetype's recent decks, and an event's whole standings,
each row linking on to `decks/{deck_id}.json`. Built from the snapshot a run
just wrote, so they are never older than it. See docs/data-format.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set

from .cards import slug
from .explore import WINDOWS, Previews, archetype_tiles, deck_key_cards, key_cards, name_without_date, prestige
from .popular import _deck_ids, card_kind, deck_dates

ARCHETYPE_DECKS = 60
ARCHETYPE_KEY_CARDS = 3
# The days of decks an archetype's card tally counts, and the cards in its hand.
CARD_DAYS = 7
HAND = 5


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
    one that shows no colours takes the colours of that deck. `cards` and `hand` are tallied from the
    stored lists of the archetype's decks of the last `CARD_DAYS` days (see `card_tally`), and each deck
    carries its event's header. An archetype the snapshot's `merges` merged into another gets a page too:
    its leader's, with `merged_into` naming the leader.
    """
    meta = snapshot.get("meta", {})
    previews = Previews(meta, decks, catalog, snapshot.get("archetypes", {}))
    shares = {
        window: {tile["id"]: tile["percentage"] for tile in meta.get(window, {}).get("archetypes", [])}
        for window, _, _ in WINDOWS
    }
    today = _today(now)
    headers = {event["event_id"]: _event_header(event) for event in snapshot.get("events", [])}
    recent = _recent_decks(snapshot, now)
    pages = {}
    for archetype_id, tile in archetype_tiles(meta).items():
        archetype = snapshot.get("archetypes", {}).get(archetype_id, {})
        results = archetype.get("results", [])
        cards = key_cards(tile, ARCHETYPE_KEY_CARDS, previews.catalog)
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
                    "event": headers.get(result.get("event_id")),
                }
                for result in past[:ARCHETYPE_DECKS]
            ],
        }
        week = recent.get(archetype_id, [])
        lists = [(decks or {})[deck_id] for deck_id in week if deck_id in (decks or {})]
        pages[archetype_id]["cards"] = {
            "window": f"{CARD_DAYS}d",
            "deck_count": len(week),
            "list_count": len(lists),
            **card_tally(lists, catalog or {}),
        }
        pages[archetype_id]["hand"] = hand(lists, catalog or {})
    for member, leader in snapshot.get("merges", {}).items():
        if leader in pages:
            pages[member] = {**pages[leader], "merged_into": leader}
    return pages


def card_tally(lists: Sequence[dict], catalog: Dict[str, dict]) -> Dict[str, List[dict]]:
    """The cards of some decklists (each `{"m": [[quantity, name], ...], "s": ...}`), per board: `{"main": [...], "side": [...]}`.

    Each is `{"name", "oracle_id", "type", "decks", "share", "copies"}`, named and typed as in popular-cards: `type`
    is the front face's kind of card (`card_kind`, "other" for none), `decks` the lists that play it, `share` their
    percent of the lists to one decimal and `copies` the average copies in them, to one decimal. Most decks first,
    then most copies as shown, then name. Lands and basics are in; a card the catalog doesn't know is left out.
    """
    boards = {}
    for board, key in (("main", "m"), ("side", "s")):
        rows = []
        for card, (count, copies) in _tally(lists, key).items():
            known = catalog.get(card)
            if known is None:
                continue
            rows.append(
                {
                    **_card(known),
                    "type": card_kind(known.get("type_line", "")) or "other",
                    "decks": count,
                    "share": round(100 * count / len(lists), 1),
                    "copies": round(copies / count, 1),
                }
            )
        rows.sort(key=lambda row: (-row["decks"], -row["copies"], row["name"]))
        boards[board] = rows
    return boards


def hand(lists: Sequence[dict], catalog: Dict[str, dict], limit: int = HAND) -> List[dict]:
    """The `limit` mainboard non-lands that most stand for some decklists, as `{"name", "oracle_id"}`.

    A card's weight is its share of the lists times its average copies in those that play it (its copies over all
    the lists, divided by the lists), unrounded; a tie goes to the name. A card the catalog doesn't know is left out.
    """
    ranked = []
    for card, (_, copies) in _tally(lists, "m").items():
        known = catalog.get(card)
        if known is not None and not known.get("land"):
            ranked.append((copies, _card(known)))
    ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
    return [card for _, card in ranked[:limit]]


def _card(known: dict) -> dict:
    """A catalog card's name and oracle id: a split card is both halves, "Fire // Ice", any other its front face."""
    name = known["name"] if known.get("layout") == "split" else known["name"].split(" // ")[0]
    return {"name": name, "oracle_id": known.get("oracle_id")}


def _tally(lists: Sequence[dict], board: str) -> Dict[str, List[int]]:
    """Each card on a board (`"m"` or `"s"`) of the lists by slug: `[lists that play it, copies in them]`."""
    tally: Dict[str, List[int]] = {}
    for deck in lists:
        copies: Dict[str, int] = {}
        for quantity, name in deck.get(board, []):
            card = slug(name)
            copies[card] = copies.get(card, 0) + quantity
        for card, quantity in copies.items():
            entry = tally.setdefault(card, [0, 0])
            entry[0] += 1
            entry[1] += quantity
    return tally


def _recent_decks(snapshot: dict, now: datetime) -> Dict[str, List[str]]:
    """The decks of each archetype dated in the last `CARD_DAYS` days, by archetype id.

    A deck belongs to the archetype whose results list it, else to the one its event result names.
    """
    membership: Dict[str, str] = {}
    for archetype_id, archetype in snapshot.get("archetypes", {}).items():
        for result in archetype.get("results", []):
            membership.setdefault(result["deck_id"], archetype_id)
    for event in snapshot.get("events", []):
        for result in event.get("results", []):
            if result.get("archetype_id"):
                membership.setdefault(result["deck_id"], result["archetype_id"])
    recent: Dict[str, List[str]] = {}
    for deck_id in sorted(_deck_ids(deck_dates(snapshot), now, CARD_DAYS)):
        if deck_id in membership:
            recent.setdefault(membership[deck_id], []).append(deck_id)
    return recent


def _event_header(event: dict) -> dict:
    """What an event row of explore.json's `recent_events` shows of an event, for a deck's header."""
    return {
        "id": event["event_id"],
        "name": name_without_date(event["event_name"], event["date"][:10]),
        "kind": event.get("kind", "other"),
        "prestige": prestige(event),
        "source": event.get("source"),
        "deck_count": len(event["results"]),
    }


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
