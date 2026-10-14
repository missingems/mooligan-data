"""today.json: what matters today in one response, for Explore's Today widgets, published each run.

Built from files already published: up to three breakout cards from `breakouts/{format}.json`, from three formats
where three have one (the strongest first: most decks and top 8s over the formats), the day's biggest mover
and loser from `movers/all.json` with their price history, the EDH commander whose deck count rose fastest since
EDHREC was last asked about it (from the commander check times in `state/edhrec-commanders.json` and the snapshot
this file keeps of them), and a preview, one of the printings Scryfall added since the last run, from a set not released yet (see previews.py).
See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .cards import slug as card_slug
from .movers import FORMATS
from .previews import NewPrintings, pick

log = logging.getLogger(__name__)

SCHEMA = 2

# How many breakout cards the file holds at most.
MAX_BREAKOUTS = 3
# The breakout row's fields a breakout card keeps, in this order; `scryfall_id` and `price` are missing from a row
# that has none.
CARD_FIELDS = ("name", "oracle_id", "scryfall_id", "type", "decks", "share", "previous_share", "new", "first_seen", "top8", "wins", "price")
# The archetypes kept per breakout card, most decks first.
MAX_ARCHETYPES = 3
# The mover's fields, as movers/all.json publishes them, `history` included.
MOVER_FIELDS = ("name", "slug", "oracle_id", "scryfall_id", "set", "price", "previous", "change", "percent", "history")
# A format's place when a card's rows tie on decks: the published order, and formats not in it after, alphabetically.
FORMAT_ORDER = {format: place for place, format in enumerate(FORMATS)}

# The rising commander: what EDHREC last said of each commander, kept from one run to the next to see what rose.
COMMANDER_STATE = "state/edhrec-commanders.json"
COMMANDER_SNAPSHOT = "state/today-commanders.json"
# The floor a rise must clear: enough decks that the commander is played, a rise of at least this many decks and of
# at least this percent of the decks before. Small commanders swing by a deck or two, and most commanders barely move.
MIN_DECKS = 50
MIN_RISE = 10
MIN_RISE_PERCENT = 10.0
# The cards kept from each of the commander's lists.
MAX_COMMANDER_CARDS = 3
# EDHREC's section tags: the cards most of its decks play, and the cards its decks play far more than others of the
# same colours (EDHREC calls them high synergy, and lately high lift).
TOP_CARDS = ("topcards",)
SYNERGY_CARDS = ("highsynergycards", "highliftcards")
ATTRIBUTION = {"name": "EDHREC", "url": "https://edhrec.com"}


def build_today(
    breakouts: Dict[str, dict],
    movers_all: Optional[dict],
    now: datetime,
    new_printings: Iterable[dict] = (),
    commander: Optional[dict] = None,
    archetype_pages=None,
) -> dict:
    """The file: `breakouts` is each format's breakouts document by format id, `movers_all` is movers/all.json (None if missing).

    `new_printings` are the printings new since the last run, as `NewPrintings.cards` has them; `commander` is the
    rising commander as `rising_commander` gives it; `archetype_pages` reads an archetype's `archetypes/{id}.json` (a
    mapping, or anything with `get`), for its colours.
    """
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "breakouts": _breakouts(breakouts, archetype_pages or {}),
        "movers": _movers(movers_all),
        "commander": commander,
        "preview": {"card": pick(new_printings, now.astimezone(timezone.utc).date())},
    }


# ---- Breakouts


def _breakouts(breakouts: Dict[str, dict], archetype_pages) -> List[dict]:
    """Up to three cards, from three different formats where three formats have one.

    The cards are ranked as one list by strength (see `_rank`; a card new to a format only breaks a tie), one entry
    per card, and the best-ranked card of each format comes first: a card whose busiest format already has a card is
    taken only when fewer than three formats have a breakout. The cards keep their ranked order.
    """
    cards: Dict[str, List[Tuple[str, dict]]] = {}
    for key, document in breakouts.items():
        format = document.get("format") or key
        for row in document.get("cards") or []:
            cards.setdefault(_identity(row), []).append((format, row))
    ranked: List[Tuple[str, dict, str]] = []
    for identity in sorted(cards, key=lambda card: _rank(card, cards[card])):
        format, row = min(cards[identity], key=_home)
        ranked.append((format, row, identity))
    # The best card of each format, then, while there is room, the next best whatever its format.
    places: List[int] = []
    formats = set()
    for place, (format, _, _) in enumerate(ranked):
        if format not in formats and len(places) < MAX_BREAKOUTS:
            formats.add(format)
            places.append(place)
    for place in range(len(ranked)):
        if len(places) == MAX_BREAKOUTS:
            break
        if place not in places:
            places.append(place)
    return [_card(format, row, [found for found, _ in cards[identity]], archetype_pages) for format, row, identity in (ranked[place] for place in sorted(places))]


def _identity(row: dict) -> str:
    return row.get("oracle_id") or row.get("name", "")


def _rank(identity: str, rows: List[Tuple[str, dict]]) -> tuple:
    """Strongest first: the decks and top 8s added up over the formats the card breaks out in, then its largest
    gain in share, then a card new to its busiest format before one that is not, then name.

    A top 8 is a deck too, so it counts twice. Decks over the formats make a card that breaks out in several formats
    strong and a four-deck card weak whatever its share; `new` says only that no deck of the weeks before played the
    card, which a few decks of an obscure format do as easily as a release.
    """
    home = min(rows, key=_home)[1]
    return (
        -sum(row.get("decks", 0) + row.get("top8", 0) for _, row in rows),
        -max(row.get("share", 0) - row.get("previous_share", 0) for _, row in rows),
        not home.get("new"),
        rows[0][1].get("name", ""),
        identity,
    )


def _home(entry: Tuple[str, dict]) -> tuple:
    """Most decks, then the format's place in the published order (formats not in it after, alphabetically)."""
    format, row = entry
    return (-row.get("decks", 0), _format_place(format))


def _format_place(format: str) -> tuple:
    return (FORMAT_ORDER.get(format, len(FORMAT_ORDER)), format if format not in FORMAT_ORDER else "")


def _card(format: str, row: dict, formats: List[str], archetype_pages) -> dict:
    """The card as its busiest format's row has it, with every format it breaks out in and the archetypes playing it there."""
    others = sorted(set(formats) - {format}, key=_format_place)
    return {
        "format": format,
        "formats": [format, *others],
        **{field: row[field] for field in CARD_FIELDS if field in row},
        "archetypes": _archetypes(row.get("results") or [], archetype_pages),
    }


def _archetypes(results: List[dict], archetype_pages) -> List[dict]:
    """The tracked archetypes of the decks that play the card, most decks first, then name, with their colours; a deck
    outside the tracked archetypes (one with no `archetype_id`, named by its pilot) is left out."""
    decks: Dict[Tuple[str, str], int] = {}
    for result in results:
        if result.get("archetype_id") and result.get("archetype"):
            key = (result["archetype_id"], result["archetype"])
            decks[key] = decks.get(key, 0) + 1
    ordered = sorted(decks, key=lambda key: (-decks[key], key[1], key[0]))
    archetypes = []
    for archetype_id, name in ordered[:MAX_ARCHETYPES]:
        archetype = {"name": name, "id": archetype_id, "decks": decks[(archetype_id, name)]}
        colors = _archetype_colors(archetype_id, results, archetype_pages)
        if colors is not None:
            archetype["colors"] = colors
        archetypes.append(archetype)
    return archetypes


def _archetype_colors(archetype_id: str, results: List[dict], archetype_pages) -> Optional[List[str]]:
    """An archetype's colours as WUBRG letters in that order, `[]` for colourless; None when unknown.

    Its tracked colours first: those of its `archetypes/{id}.json` (its tile's, else its featured deck's, as in
    `explore.json`'s standings). Else the colours most of its decks among `results` have (ties to the one listed first).
    """
    page = archetype_pages.get(archetype_id) or {}
    if isinstance(page.get("colors"), list):
        return _wubrg(page["colors"])
    counts: Dict[Tuple[str, ...], int] = {}
    for result in results:
        if result.get("archetype_id") == archetype_id and isinstance(result.get("colors"), list):
            colors = tuple(_wubrg(result["colors"]))
            counts[colors] = counts.get(colors, 0) + 1
    if not counts:
        return None
    # max() keeps the first of equal counts, and a dict keeps the order the results list them in.
    return list(max(counts, key=lambda colors: counts[colors]))


def _wubrg(colors: Iterable[str]) -> List[str]:
    """The colour letters among `colors`, once each, in WUBRG order."""
    present = {color for color in colors if isinstance(color, str)}
    return [color for color in "WUBRG" if color in present]


# ---- Movers


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


# ---- The rising commander


def rising_commander(checked: Dict[str, dict], snapshot: Optional[Dict[str, dict]], pages: Dict[str, dict]) -> Optional[dict]:
    """The commander whose deck count rose fastest, as a percent a day, since EDHREC was last asked about it.

    `checked` is state/edhrec-commanders.json as this run left it, `snapshot` what the last run's file kept of it (None
    on a first run, when nothing can have risen), and `pages` reads a commander's `edh/commanders/{slug}.json` (a
    mapping, or anything with `get`). Only a commander checked again since the snapshot, which had a count then, can
    rise; it must clear the floor (`MIN_DECKS`, `MIN_RISE`, `MIN_RISE_PERCENT`). The commanders that do are ranked by
    their percent rise a day, over the days between the dates of the two checks (at least 1), as the checks are
    days or weeks apart; ties go to the larger rise in decks a day, then the larger rise, then the slug.
    """
    if not snapshot:
        return None
    rising = []
    for slug, now in checked.items():
        before = snapshot.get(slug)
        if not isinstance(before, dict) or not isinstance(now, dict) or before.get("checked_at") == now.get("checked_at"):
            continue
        decks, previous = now.get("decks"), before.get("decks")
        if not isinstance(decks, int) or not isinstance(previous, int) or previous <= 0:
            continue
        rise = decks - previous
        percent = rise * 100 / previous
        if decks >= MIN_DECKS and rise >= MIN_RISE and percent >= MIN_RISE_PERCENT:
            days = _days(before.get("checked_at"), now.get("checked_at"))
            rising.append((-percent / days, -rise / days, -rise, slug))
    if not rising:
        return None
    slug = min(rising)[-1]
    now, before = checked[slug], snapshot[slug]
    rise = now["decks"] - before["decks"]
    days = _days(before.get("checked_at"), now.get("checked_at"))
    page = pages.get(slug) or {}
    return {
        "slug": slug,
        "name": page.get("name") or now.get("name") or slug,
        "scryfall_id": page.get("scryfall_id"),
        "color_identity": page.get("color_identity"),
        "decks": now["decks"],
        "previous_decks": before["decks"],
        "rise": rise,
        "rise_percent": round(rise * 100 / before["decks"], 1),
        "since": (before.get("checked_at") or "")[:10] or None,
        "days": days,
        "rise_per_day": round(rise / days, 1),
        "rise_percent_per_day": round(rise * 100 / before["decks"] / days, 2),
        "url": page.get("url") or f"https://edhrec.com/commanders/{slug}",
        "top_cards": _commander_cards(page, TOP_CARDS),
        "synergy_cards": _commander_cards(page, SYNERGY_CARDS),
        "attribution": ATTRIBUTION,
    }


def _days(before: Optional[str], after: Optional[str]) -> int:
    """The days between the dates of two check times, at least 1 (also when either is missing or not a date)."""
    try:
        return max(1, (date.fromisoformat(after[:10]) - date.fromisoformat(before[:10])).days)
    except (TypeError, ValueError):
        return 1


def _commander_cards(page: dict, tags: Tuple[str, ...]) -> List[dict]:
    """The first few cards of the commander's first section with one of `tags`, with the share of its decks playing them."""
    sections = {section.get("tag"): section for section in page.get("sections") or []}
    for tag in tags:
        if tag in sections:
            cards = []
            for card in (sections[tag].get("cards") or [])[:MAX_COMMANDER_CARDS]:
                of_decks = card.get("of_decks") or page.get("decks") or 0
                cards.append({
                    "name": card.get("name", ""),
                    "decks": card.get("decks", 0),
                    "share": round(card.get("decks", 0) * 100 / of_decks, 1) if of_decks else None,
                    "synergy": card.get("synergy"),
                })
            return cards
    return []


def read_commanders(directory: Path) -> Tuple[Dict[str, dict], Optional[Dict[str, dict]]]:
    """This run's commander check times and counts, and the snapshot the last run kept of them (None when there is none)."""
    path = directory / COMMANDER_STATE
    checked = json.loads(path.read_text()) if path.exists() else {}
    snapshot_path = directory / COMMANDER_SNAPSHOT
    try:
        snapshot = json.loads(snapshot_path.read_text()).get("commanders") if snapshot_path.exists() else None
    except (ValueError, AttributeError):
        snapshot = None
    # A snapshot of some other shape is no snapshot, so the run still publishes, with no commander.
    return checked if isinstance(checked, dict) else {}, snapshot if isinstance(snapshot, dict) else None


def write_commander_snapshot(directory: Path, checked: Dict[str, dict]) -> None:
    """Keeps each commander's count and check time, for the next run to compare with."""
    path = directory / COMMANDER_SNAPSHOT
    path.parent.mkdir(parents=True, exist_ok=True)
    commanders = {
        slug: {"decks": state["decks"], "checked_at": state.get("checked_at")}
        for slug, state in sorted(checked.items())
        if isinstance(state.get("decks"), int)
    }
    path.write_text(json.dumps({"schema": 1, "commanders": commanders}, sort_keys=True, separators=(",", ":")))


class _Pages:
    """Reads the pages of one folder of the work directory when asked (`edh/commanders/{slug}.json`,
    `archetypes/{id}.json`), None for a page that isn't there or can't be read."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def get(self, name: str) -> Optional[dict]:
        path = self._folder / f"{name}.json"
        try:
            page = json.loads(path.read_text()) if path.exists() else None
        except ValueError:
            return None
        return page if isinstance(page, dict) else None


# ---- Oracle ids


def _with_oracle_ids(document: dict, catalog: Optional[Dict[str, dict]]) -> None:
    """Adds the oracle ids `catalog` knows by card name, in place; the names it doesn't know are logged.

    The commander and its top and synergy cards get an `oracle_id` (null when unknown), as EDHREC has none. A
    breakout, the mover, the loser and the preview card keep the one they have and get one only when theirs is null.
    """
    if not catalog:
        return
    missing: List[str] = []
    commander = document.get("commander")
    if commander:
        document["commander"] = _placed(commander, catalog, missing)
        for key in ("top_cards", "synergy_cards"):
            document["commander"][key] = [_placed(card, catalog, missing) for card in commander.get(key) or []]
    movers = document.get("movers") or {}
    cards = [*(document.get("breakouts") or []),movers.get("mover"), movers.get("loser"), (document.get("preview") or {}).get("card")]
    for card in cards:
        if card and not card.get("oracle_id"):
            oracle_id = _oracle_id(card.get("name"), catalog)
            if oracle_id:
                card["oracle_id"] = oracle_id
            else:
                missing.append(card.get("name") or "")
    if missing:
        log.warning("Today: no oracle id for %s", ", ".join(sorted(set(missing))))


def _oracle_id(name: Optional[str], catalog: Dict[str, dict]) -> Optional[str]:
    return catalog.get(card_slug(name or ""), {}).get("oracle_id")


def _placed(entry: dict, catalog: Dict[str, dict], missing: List[str]) -> dict:
    """The commander or card with `oracle_id` right after its `name`."""
    oracle_id = _oracle_id(entry.get("name"), catalog)
    if not oracle_id:
        missing.append(entry.get("name") or "")
    placed: dict = {}
    for key, value in entry.items():
        if key != "oracle_id":
            placed[key] = value
        if key == "name":
            placed["oracle_id"] = oracle_id
    return placed


# ---- Reading and writing


def read_published(directory: Path) -> Tuple[Dict[str, dict], Optional[dict]]:
    """The breakouts documents by format id and movers/all.json from a work directory; a file not there is left out."""
    breakouts = {path.stem: json.loads(path.read_text()) for path in sorted((directory / "breakouts").glob("*.json"))}
    path = directory / "movers" / "all.json"
    return breakouts, json.loads(path.read_text()) if path.exists() else None


def write_today(directory: Path, now: datetime, new_printings: Optional[NewPrintings] = None, catalog: Optional[Dict[str, dict]] = None) -> List[str]:
    """Builds today.json from the published files in `directory`, writes it there and returns its path.

    `catalog` is the card catalog by slug (see `scryfall.card_catalog`): with it, the commander and its cards get
    an `oracle_id`, and a breakout, mover, loser or preview with none gets the one its name has there.

    The preview needs `new_printings` read to the end of Scryfall's file. Without that (the movers were off, or the
    file could not be read through) it is null and the saved printing ids stay as they were; with it, they move
    on to this run's once the file is written. The commander snapshot moves on to this run's every time.
    """
    breakouts, movers_all = read_published(directory)
    checked, snapshot = read_commanders(directory)
    commander = rising_commander(checked, snapshot, _Pages(directory / "edh" / "commanders"))
    finished = new_printings if new_printings is not None and new_printings.complete else None
    document = build_today(breakouts, movers_all, now, finished.cards if finished else (), commander, _Pages(directory / "archetypes"))
    _with_oracle_ids(document, catalog)
    (directory / "today.json").write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    if finished:
        finished.save(directory)
    if checked:
        write_commander_snapshot(directory, checked)
    return ["today.json"]
