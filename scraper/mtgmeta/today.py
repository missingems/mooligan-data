"""today.json: what matters today in one response, for Explore's Today widgets, published each run.

Built from files already published: up to three breakout cards from `breakouts/{format}.json` (new cards seeing
play first, then released cards suddenly seeing play), the day's biggest mover and loser from `movers/all.json` with
their price history, the EDH commander whose deck count rose most since EDHREC was last asked about it (from the
commander check times in `state/edhrec-commanders.json` and the snapshot this file keeps of them), and a preview,
one of the printings Scryfall added since the last run (see previews.py). See docs/data-format.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .movers import FORMATS
from .previews import NewPrintings, pick

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
) -> dict:
    """The file: `breakouts` is each format's breakouts document by format id, `movers_all` is movers/all.json (None if missing).

    `new_printings` are the printings new since the last run, as `NewPrintings.cards` has them; `commander` is the
    rising commander as `rising_commander` gives it.
    """
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "breakouts": _breakouts(breakouts),
        "movers": _movers(movers_all),
        "commander": commander,
        "preview": {"card": pick(new_printings, now.astimezone(timezone.utc).date())},
    }


# ---- Breakouts


def _breakouts(breakouts: Dict[str, dict]) -> List[dict]:
    """Up to three cards: new cards seeing play first, then released cards that suddenly see play, one entry per card."""
    found: Dict[bool, List[Tuple[str, dict]]] = {True: [], False: []}
    everywhere: Dict[str, List[str]] = {}
    for key, document in breakouts.items():
        format = document.get("format") or key
        for row in document.get("cards") or []:
            found[bool(row.get("new"))].append((format, row))
            everywhere.setdefault(_identity(row), []).append(format)
    chosen: List[dict] = []
    taken = set()
    for new in (True, False):
        cards: Dict[str, List[Tuple[str, dict]]] = {}
        for format, row in found[new]:
            cards.setdefault(_identity(row), []).append((format, row))
        for identity in sorted(cards, key=lambda card: _rank(card, cards[card])):
            if len(chosen) == MAX_BREAKOUTS:
                return chosen
            if identity in taken:
                continue
            taken.add(identity)
            format, row = min(cards[identity], key=_home)
            chosen.append(_card(format, row, everywhere[identity]))
    return chosen


def _identity(row: dict) -> str:
    return row.get("oracle_id") or row.get("name", "")


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
    return (-row.get("decks", 0), _format_place(format))


def _format_place(format: str) -> tuple:
    return (FORMAT_ORDER.get(format, len(FORMAT_ORDER)), format if format not in FORMAT_ORDER else "")


def _card(format: str, row: dict, formats: List[str]) -> dict:
    """The card as its busiest format's row has it, with every format it breaks out in and the archetypes playing it there."""
    others = sorted(set(formats) - {format}, key=_format_place)
    return {
        "format": format,
        "formats": [format, *others],
        **{field: row[field] for field in CARD_FIELDS if field in row},
        "archetypes": _archetypes(row.get("results") or []),
    }


def _archetypes(results: List[dict]) -> List[dict]:
    """The archetypes of the decks that play the card, most decks first, then name. A deck outside the tracked
    archetypes counts under the tracked archetype of the same name when there is one, else under its pilot's own
    title with a null id."""
    tracked: Dict[str, Tuple[str, str]] = {}
    for result in results:
        if result.get("archetype") and result.get("archetype_id"):
            tracked.setdefault(result["archetype"].casefold(), (result["archetype_id"], result["archetype"]))
    decks: Dict[Tuple[Optional[str], str], int] = {}
    for result in results:
        name = result.get("archetype")
        if not name:
            continue
        key = (result["archetype_id"], name) if result.get("archetype_id") else tracked.get(name.casefold(), (None, name))
        decks[key] = decks.get(key, 0) + 1
    ordered = sorted(decks, key=lambda key: (-decks[key], key[1], key[0] or ""))
    return [{"name": name, "id": archetype_id, "decks": decks[(archetype_id, name)]} for archetype_id, name in ordered[:MAX_ARCHETYPES]]


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
    """The commander whose deck count rose most, as a percent, since EDHREC was last asked about it.

    `checked` is state/edhrec-commanders.json as this run left it, `snapshot` what the last run's file kept of it (None
    on a first run, when nothing can have risen), and `pages` reads a commander's `edh/commanders/{slug}.json` (a
    mapping, or anything with `get`). Only a commander checked again since the snapshot, which had a count then, can
    rise; it must clear the floor (`MIN_DECKS`, `MIN_RISE`, `MIN_RISE_PERCENT`). Ties go to the larger rise in decks,
    then the slug.
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
            rising.append((-percent, -rise, slug))
    if not rising:
        return None
    _, _, slug = min(rising)
    now, before = checked[slug], snapshot[slug]
    page = pages.get(slug) or {}
    return {
        "slug": slug,
        "name": page.get("name") or now.get("name") or slug,
        "scryfall_id": page.get("scryfall_id"),
        "color_identity": page.get("color_identity"),
        "decks": now["decks"],
        "previous_decks": before["decks"],
        "rise": now["decks"] - before["decks"],
        "rise_percent": round((now["decks"] - before["decks"]) * 100 / before["decks"], 1),
        "since": (before.get("checked_at") or "")[:10] or None,
        "url": page.get("url") or f"https://edhrec.com/commanders/{slug}",
        "top_cards": _commander_cards(page, TOP_CARDS),
        "synergy_cards": _commander_cards(page, SYNERGY_CARDS),
        "attribution": ATTRIBUTION,
    }


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
    """Reads `edh/commanders/{slug}.json` from the work directory when asked, None for a page that isn't there."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def get(self, slug: str) -> Optional[dict]:
        path = self._directory / "edh" / "commanders" / f"{slug}.json"
        try:
            return json.loads(path.read_text()) if path.exists() else None
        except ValueError:
            return None


# ---- Reading and writing


def read_published(directory: Path) -> Tuple[Dict[str, dict], Optional[dict]]:
    """The breakouts documents by format id and movers/all.json from a work directory; a file not there is left out."""
    breakouts = {path.stem: json.loads(path.read_text()) for path in sorted((directory / "breakouts").glob("*.json"))}
    path = directory / "movers" / "all.json"
    return breakouts, json.loads(path.read_text()) if path.exists() else None


def write_today(directory: Path, now: datetime, new_printings: Optional[NewPrintings] = None) -> List[str]:
    """Builds today.json from the published files in `directory`, writes it there and returns its path.

    The preview needs `new_printings` read to the end of Scryfall's file. Without that (the movers were off, or the
    file could not be read through) it is null and the saved printing ids stay as they were; with it, they move
    on to this run's once the file is written. The commander snapshot moves on to this run's every time.
    """
    breakouts, movers_all = read_published(directory)
    checked, snapshot = read_commanders(directory)
    commander = rising_commander(checked, snapshot, _Pages(directory))
    finished = new_printings if new_printings is not None and new_printings.complete else None
    document = build_today(breakouts, movers_all, now, finished.cards if finished else (), commander)
    (directory / "today.json").write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    if finished:
        finished.save(directory)
    if checked:
        write_commander_snapshot(directory, checked)
    return ["today.json"]
