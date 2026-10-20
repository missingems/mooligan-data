"""archetypes/{id}.json and events/{id}.json: what the app opens from an Explore row.

explore.json shows a format's top archetypes and latest events. These files are
one level down: an archetype's recent decks, and an event's whole standings,
each row linking on to `decks/{deck_id}.json`. Built from the snapshot a run
just wrote, so they are never older than it. See docs/data-format.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .cards import slug
from .explore import WINDOWS, Previews, archetype_tiles, deck_key_cards, key_cards, name_without_date, prestige
from .popular import _deck_ids, card_kind, deck_dates

ARCHETYPE_DECKS = 60
ARCHETYPE_KEY_CARDS = 3
# The days of decks an archetype's card tally counts, the days it counts instead when none of those has a stored list,
# and the cards in its hand.
CARD_DAYS = 7
CARD_FALLBACK_DAYS = 30
HAND = 5
BOARDS = (("main", "m"), ("side", "s"))


def build_archetype_pages(
    snapshot: dict,
    now: datetime,
    deck_ids: Set[str],
    decks: Optional[Dict[str, dict]] = None,
    catalog: Optional[Dict[str, dict]] = None,
    hands: Optional[Dict[str, List[dict]]] = None,
) -> Dict[str, dict]:
    """A page per archetype in the format's metagame (any window), by archetype id.

    `deck_ids` are the decklists published, which is what each deck's `published` says. The key cards are
    the first `ARCHETYPE_KEY_CARDS` of the archetype's hand; with no hand, the tile's. A tile
    that shows no key cards takes them from the archetype's featured deck instead, when `decks`
    (the format's stored deck contents) has it and `catalog` (the card catalog) knows its cards, and
    one that shows no colours takes the colours of that deck. `cards` and `hand` are tallied from the
    stored lists of the archetype's decks of the last `CARD_DAYS` days, or of the last `CARD_FALLBACK_DAYS` when
    none of those has one (see `card_tally`, `_card_decks`); `hands` are those of
    `archetype_hands`, worked out here when not given. Its `consensus` is from the same lists
    (see `consensus`), and each deck carries its event's header and, when its list is stored and the archetype
    has a consensus to compare it with, its `changes` from that consensus (see `changes`). An archetype the
    snapshot's `merges` merged into another gets a page too: its leader's, with `merged_into` naming the leader.
    """
    meta = snapshot.get("meta", {})
    previews = Previews(meta, decks, catalog, snapshot.get("archetypes", {}))
    shares = {
        window: {tile["id"]: tile["percentage"] for tile in meta.get(window, {}).get("archetypes", [])}
        for window, _, _ in WINDOWS
    }
    today = _today(now)
    headers = {event["event_id"]: _event_header(event) for event in snapshot.get("events", [])}
    recent = _card_decks(snapshot, now, decks)
    if hands is None:
        hands = archetype_hands(snapshot, now, decks, catalog)
    pages = {}
    for archetype_id, tile in archetype_tiles(meta).items():
        archetype = snapshot.get("archetypes", {}).get(archetype_id, {})
        results = archetype.get("results", [])
        cards = hands.get(archetype_id, [])[:ARCHETYPE_KEY_CARDS] or key_cards(tile, ARCHETYPE_KEY_CARDS, previews.catalog)
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
        days, week = recent.get(archetype_id, (CARD_DAYS, []))
        lists = [(decks or {})[deck_id] for deck_id in week if deck_id in (decks or {})]
        pages[archetype_id]["cards"] = {
            "window": f"{days}d",
            "deck_count": len(week),
            "list_count": len(lists),
            **card_tally(lists, catalog or {}),
        }
        pages[archetype_id]["hand"] = hands.get(archetype_id, [])
        common = consensus(lists, catalog or {})
        pages[archetype_id]["consensus"] = {board: _ranked(common[board].values()) for board in common}
        for deck in pages[archetype_id]["decks"]:
            stored = (decks or {}).get(deck["deck_id"])
            deck["changes"] = changes(stored, common, catalog or {}) if stored is not None and lists else None
    for member, leader in snapshot.get("merges", {}).items():
        if leader in pages:
            pages[member] = {**pages[leader], "merged_into": leader}
    return pages


def archetype_hands(
    snapshot: dict, now: datetime, decks: Optional[Dict[str, dict]] = None, catalog: Optional[Dict[str, dict]] = None
) -> Dict[str, List[dict]]:
    """Each archetype's `hand`, from the stored lists of its decks of the last `CARD_DAYS` days (`CARD_FALLBACK_DAYS` when none has one), by archetype id."""
    return {
        archetype_id: hand([(decks or {})[deck_id] for deck_id in week if deck_id in (decks or {})], catalog or {})
        for archetype_id, (_, week) in _card_decks(snapshot, now, decks).items()
    }


def hand_key_cards(snapshot: dict, hands: Dict[str, List[dict]]) -> dict:
    """The snapshot with each meta tile's key cards the first `ARCHETYPE_KEY_CARDS` of its archetype's hand.

    A tile whose archetype has no hand keeps the key cards it has.
    """
    meta = {
        window: {
            **document,
            "archetypes": [
                {**tile, "key_cards": hands[tile["id"]][:ARCHETYPE_KEY_CARDS]} if hands.get(tile["id"]) else tile
                for tile in document.get("archetypes", [])
            ],
        }
        for window, document in snapshot.get("meta", {}).items()
    }
    return {**snapshot, "meta": meta}


def card_tally(lists: Sequence[dict], catalog: Dict[str, dict]) -> Dict[str, List[dict]]:
    """The cards of some decklists (each `{"m": [[quantity, name], ...], "s": ...}`), per board: `{"main": [...], "side": [...]}`.

    Each is `{"name", "oracle_id", "type", "decks", "share", "copies"}`, named and typed as in popular-cards: `type`
    is the front face's kind of card (`card_kind`, "other" for none), `decks` the lists that play it, `share` their
    percent of the lists to one decimal and `copies` the average copies in them, to one decimal. Most decks first,
    then most copies as shown, then name. Lands and basics are in; a card the catalog doesn't know is left out.
    """
    boards = {}
    for board, key in BOARDS:
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


def consensus(lists: Sequence[dict], catalog: Dict[str, dict]) -> Dict[str, Dict[str, dict]]:
    """The archetype's common list from some decklists, per board and by slug: `{"main": {slug: card}, "side": ...}`.

    A card is in when at least half the lists play it on that board, at its average copies in the lists that play
    it, rounded half up and at least 1: each `{"name", "oracle_id", "quantity"}`, named as in `card_tally`, or as
    the first list writes it with a null `oracle_id` when the catalog doesn't know it.
    """
    boards = {}
    for board, key in BOARDS:
        written = {}
        for deck in lists:
            for card, (name, _) in _board(deck, key).items():
                written.setdefault(card, name)
        boards[board] = {
            card: {**_named(card, written[card], catalog), "quantity": max(1, int(copies / count + 0.5))}
            for card, (count, copies) in _tally(lists, key).items()
            if 2 * count >= len(lists)
        }
    return boards


def changes(deck: dict, common: Dict[str, Dict[str, dict]], catalog: Dict[str, dict]) -> dict:
    """A decklist against a `consensus`: the copies it plays over the consensus's are `added`, those it plays under `removed`.

    Each is `{"name", "oracle_id", "quantity", "board"}` with `board` `"main"` or `"side"`, mainboard first, then
    most copies, then name; `added_count` and `removed_count` add up their quantities.
    """
    added: List[dict] = []
    removed: List[dict] = []
    for board, key in BOARDS:
        played = _board(deck, key)
        for card in sorted(set(played) | set(common[board])):
            expected = common[board][card] if card in common[board] else None
            difference = (played[card][1] if card in played else 0) - (expected["quantity"] if expected else 0)
            if difference == 0:
                continue
            named = {"name": expected["name"], "oracle_id": expected["oracle_id"]} if expected else _named(card, played[card][0], catalog)
            (added if difference > 0 else removed).append({**named, "quantity": abs(difference), "board": board})
    order = {board: index for index, (board, _) in enumerate(BOARDS)}
    for rows in (added, removed):
        rows.sort(key=lambda row: (order[row["board"]], -row["quantity"], row["name"]))
    return {
        "added": added,
        "removed": removed,
        "added_count": sum(row["quantity"] for row in added),
        "removed_count": sum(row["quantity"] for row in removed),
    }


def _ranked(cards) -> List[dict]:
    return sorted(cards, key=lambda card: (-card["quantity"], card["name"]))


def _named(card: str, written: str, catalog: Dict[str, dict]) -> dict:
    known = catalog.get(card)
    return _card(known) if known is not None else {"name": written, "oracle_id": None}


def _board(deck: dict, board: str) -> Dict[str, list]:
    """A list's board (`"m"` or `"s"`) by slug: `[the name as first written, copies]`."""
    cards: Dict[str, list] = {}
    for quantity, name in deck.get(board, []):
        entry = cards.setdefault(slug(name), [name, 0])
        entry[1] += quantity
    return cards


def _card(known: dict) -> dict:
    """A catalog card's name and oracle id: a split card is both halves, "Fire // Ice", any other its front face."""
    name = known["name"] if known.get("layout") == "split" else known["name"].split(" // ")[0]
    return {"name": name, "oracle_id": known.get("oracle_id")}


def _tally(lists: Sequence[dict], board: str) -> Dict[str, List[int]]:
    """Each card on a board (`"m"` or `"s"`) of the lists by slug: `[lists that play it, copies in them]`."""
    tally: Dict[str, List[int]] = {}
    for deck in lists:
        for card, (_, quantity) in _board(deck, board).items():
            entry = tally.setdefault(card, [0, 0])
            entry[0] += 1
            entry[1] += quantity
    return tally


def _card_decks(snapshot: dict, now: datetime, decks: Optional[Dict[str, dict]]) -> Dict[str, Tuple[int, List[str]]]:
    """The days and the decks each archetype's cards are counted from, by archetype id.

    The decks dated in the last `CARD_DAYS` days, or in the last `CARD_FALLBACK_DAYS` when none of those has a stored
    list in `decks` and some of those do.
    """
    week = _recent_decks(snapshot, now, CARD_DAYS)
    month = _recent_decks(snapshot, now, CARD_FALLBACK_DAYS)
    stored = decks or {}
    return {
        archetype_id: (CARD_DAYS, week.get(archetype_id, []))
        if any(deck_id in stored for deck_id in week.get(archetype_id, [])) or not any(deck_id in stored for deck_id in month_ids)
        else (CARD_FALLBACK_DAYS, month_ids)
        for archetype_id, month_ids in month.items()
    }


def _recent_decks(snapshot: dict, now: datetime, days: int) -> Dict[str, List[str]]:
    """The decks of each archetype dated in the last `days` days, by archetype id.

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
    for deck_id in sorted(_deck_ids(deck_dates(snapshot), now, days)):
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
