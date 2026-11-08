"""Pure parsing of mtgo.com's decklist pages: the month index and the event pages, kept apart from the network."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from .models import Deck, DeckCard, Event, EventResult
from .parsing import ParseError, event_kind

BASE_URL = "https://www.mtgo.com"
SOURCE = "mtgo.com"

MTGO_FORMATS = {
    "modern": "modern",
    "standard": "standard",
    "pioneer": "pioneer",
    "legacy": "legacy",
    "pauper": "pauper",
    "vintage": "vintage",
    "premodern": "premodern",
    "duel_commander": "duel-commander",
}

_DECKLIST_HREF = re.compile(r"^/decklist/(.+)$")
_SLUG_TAIL = re.compile(r"^(?P<head>.+?)-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?P<id>\d+)$")
_CHALLENGE_WORDS = re.compile(r"challenge|showcase|super-qualifier|prelim")
_DATA_MARKER = "window.MTGO.decklists.data = "


@dataclass
class EventRef:
    """An event as the month index lists it. `event_id` is mtgo.com's own number; publish `event_id(ref)`."""

    event_id: str
    slug: str
    format: str
    name: str
    date: datetime
    kind: str


def event_id(ref: EventRef) -> str:
    """The published event id: `mtgo-{id}` for a Challenge, `mtgo-{id}-{yyyy-mm-dd}` for a League, whose number repeats every day."""
    if ref.kind == "mtgo_league":
        return f"mtgo-{ref.event_id}-{ref.date:%Y-%m-%d}"
    return f"mtgo-{ref.event_id}"


def _split_format(head: str) -> Optional[Tuple[str, str]]:
    for name, prefix in sorted(MTGO_FORMATS.items(), key=lambda item: -len(item[1])):
        if head.startswith(prefix + "-"):
            return name, head[len(prefix) + 1 :]
    return None


def _kind(words: str, name: str) -> str:
    if words == "league":
        return "mtgo_league"
    if _CHALLENGE_WORDS.search(words):
        return "mtgo_challenge"
    return event_kind(name, SOURCE)


def parse_month(html: str) -> List[EventRef]:
    """The events of a month page in the supported formats, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    refs: List[EventRef] = []
    seen = set()
    for link in soup.select("li.decklists-item a.decklists-link[href]"):
        href = _DECKLIST_HREF.match(link["href"])
        if not href:
            continue
        slug = href.group(1)
        tail = _SLUG_TAIL.match(slug)
        split = _split_format(tail.group("head")) if tail else None
        if tail is None or split is None or slug in seen:
            continue
        seen.add(slug)
        format, words = split
        heading = link.find("h3")
        name = heading.get_text(" ", strip=True) if heading else words.replace("-", " ").title()
        date = datetime(int(tail.group("year")), int(tail.group("month")), int(tail.group("day")), tzinfo=timezone.utc)
        refs.append(
            EventRef(
                event_id=tail.group("id"),
                slug=slug,
                format=format,
                name=name,
                date=date,
                kind=_kind(words, name),
            )
        )
    return refs


def _event_data(html: str, slug: str) -> Dict[str, Any]:
    start = html.find(_DATA_MARKER)
    if start < 0:
        raise ParseError(f"No decklist data on mtgo.com event {slug}")
    try:
        data, _ = json.JSONDecoder().raw_decode(html[start + len(_DATA_MARKER) :])
    except json.JSONDecodeError as error:
        raise ParseError(f"Unreadable decklist data on mtgo.com event {slug}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("decklists"), list):
        raise ParseError(f"No decklists on mtgo.com event {slug}")
    return data


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _cards(entries: List[Dict[str, Any]]) -> List[DeckCard]:
    quantities: Dict[str, int] = {}
    for entry in entries:
        name = entry["card_attributes"]["card_name"]
        quantities[name] = quantities.get(name, 0) + int(entry["qty"])
    return [DeckCard(quantity=quantity, card_name=name) for name, quantity in quantities.items()]


def _deck_number(decklist: Dict[str, Any]) -> str:
    if decklist.get("decktournamentid"):
        return decklist["decktournamentid"]
    for entry in decklist.get("main_deck", []) + decklist.get("sideboard_deck", []):
        if entry.get("leaguedeckid"):
            return entry["leaguedeckid"]
    return decklist["loginplayeventcourseid"]


def _places(data: Dict[str, Any]) -> Dict[str, int]:
    places = {row["loginid"]: int(row["rank"]) for row in data.get("standings", [])}
    places.update({row["loginid"]: int(row["rank"]) for row in data.get("final_rank", [])})
    return places


def _league_finish(decklist: Dict[str, Any]) -> str:
    record = decklist.get("wins") or {}
    return f"{record.get('wins', 5)}-{record.get('losses', 0)}"


def parse_event(html: str, ref: EventRef) -> Tuple[Event, List[Deck]]:
    """An event page's results and decklists. Archetypes are left empty, to be named later."""
    data = _event_data(html, ref.slug)
    published = event_id(ref)
    is_league = ref.kind == "mtgo_league"
    places = {} if is_league else _places(data)

    entries: List[Tuple[int, EventResult]] = []
    decks: List[Deck] = []
    for index, decklist in enumerate(data["decklists"]):
        deck_id = f"mtgo-{_deck_number(decklist)}"
        player = decklist["player"]
        if is_league:
            place, finish = index, _league_finish(decklist)
        else:
            if decklist["loginid"] not in places:
                raise ParseError(f"No place for {player} on mtgo.com event {ref.slug}")
            place = places[decklist["loginid"]]
            finish = f"{_ordinal(place)} Place"
        entries.append((place, EventResult(player=player, archetype="", finish=finish, deck_id=deck_id)))
        decks.append(
            Deck(
                deck_id=deck_id,
                player=player,
                archetype="",
                mainboard=_cards(decklist.get("main_deck", [])),
                sideboard=_cards(decklist.get("sideboard_deck", [])),
                format=ref.format,
                event_id=published,
            )
        )

    entries.sort(key=lambda entry: entry[0])
    name = data.get("name") if is_league else data.get("description")
    event = Event(
        event_id=published,
        event_name=name or ref.name,
        format=ref.format,
        date=ref.date,
        results=[result for _, result in entries],
        url=f"{BASE_URL}/decklist/{ref.slug}",
        kind=ref.kind,
        source=SOURCE,
    )
    return event, decks
