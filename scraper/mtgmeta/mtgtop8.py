"""Pure HTML parsing of MTGTop8 format and event pages, kept apart from the browser so it can be tested."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

BASE_URL = "https://www.mtgtop8.com"
META_ID = 51

FORMAT_CODES = {
    "modern": "MO",
    "standard": "ST",
    "pioneer": "PI",
    "legacy": "LE",
    "pauper": "PAU",
    "vintage": "VI",
    "premodern": "PREM",
    "duel_commander": "EDH",
}

_LIST_TITLE = re.compile(r"^(LAST 20 EVENTS|Events \d+ to \d+)")
_EVENT_HREF = re.compile(r"event\?e=(\d+)")
_DECK_HREF = re.compile(r"[?&]d=(\d+)")
_THUMB = re.compile(r"/metas_thumbs/(\d+)\.")
_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
_PLAYERS = re.compile(r"(\d+)\s+players?\s*-\s*(\d{2}/\d{2}/\d{2})")
_SOURCE = re.compile(r"Source:\s*(\S+)")


@dataclass
class Listing:
    event_id: str
    name: str
    date: date


@dataclass
class Top8Deck:
    deck_id: str
    place: str
    archetype: str
    family_id: Optional[str]
    player: str


@dataclass
class Top8Event:
    event_id: str
    name: str
    date: date
    players: Optional[int]
    source: Optional[str]
    decks: List[Top8Deck] = field(default_factory=list)


def format_path(format: str, page: int = 1) -> str:
    path = f"/format?f={FORMAT_CODES[format]}&meta={META_ID}"
    return path if page <= 1 else f"{path}&cp={page}"


def event_path(event_id: str, format: str) -> str:
    return f"/event?e={event_id}&f={FORMAT_CODES[format]}"


def deck_path(deck_id: str) -> str:
    return f"/mtgo?d={deck_id}"


def _date(text: str) -> date:
    day, month, year = _DATE.search(text).groups()
    return date(2000 + int(year), int(month), int(day))


def parse_format_events(html: str) -> Tuple[List[Listing], bool]:
    """The dated event list rows (not the major events box), newest first, and whether a Next page exists."""
    soup = BeautifulSoup(html, "html.parser")
    title = next((div for div in soup.find_all("div", class_="w_title") if _LIST_TITLE.match(div.get_text())), None)
    table = title.find_next("table") if title else None
    listings: List[Listing] = []
    seen = set()
    for row in table.find_all("tr") if table else []:
        link = row.find("a", href=_EVENT_HREF)
        stamp = row.find("td", class_="S12")
        if link is None or stamp is None or not _DATE.search(stamp.get_text()):
            continue
        event_id = _EVENT_HREF.search(link["href"]).group(1)
        if event_id in seen:
            continue
        seen.add(event_id)
        listings.append(Listing(event_id, link.get_text(strip=True), _date(stamp.get_text())))
    has_next = any(link.get_text(strip=True) == "Next" and "cp=" in link["href"] for link in soup.find_all("a", href=True))
    return listings, has_next


def parse_event(html: str, event_id: str) -> Top8Event:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("div", class_="event_title")
    name = title.get_text(strip=True).split(" @ ")[0] if title else ""
    arch = soup.find("div", class_="meta_arch")
    header_text = arch.parent.get_text(" ") if arch else soup.get_text(" ")
    header = _PLAYERS.search(header_text)
    stamp = header.group(2) if header else _DATE.search(header_text).group(0)
    source = _SOURCE.search(header_text)
    decks: List[Top8Deck] = []
    for place in soup.find_all("div", class_="S14", style=re.compile(r"width:\s*42px")):
        row = place.parent
        deck_link = row.find("a", href=_DECK_HREF, string=True)
        player = row.find("a", class_="player")
        thumb = row.find("img", src=_THUMB)
        if deck_link is None or player is None:
            continue
        decks.append(
            Top8Deck(
                deck_id=_DECK_HREF.search(deck_link["href"]).group(1),
                place=place.get_text(strip=True),
                archetype=deck_link.get_text(strip=True),
                family_id=_THUMB.search(thumb["src"]).group(1) if thumb else None,
                player=player.get_text(strip=True),
            )
        )
    return Top8Event(event_id, name, _date(stamp), int(header.group(1)) if header else None, source.group(1) if source else None, decks)


def finish(place: str, kind_is_league: bool) -> str:
    if kind_is_league:
        return "5-0"
    parts = [int(part) for part in place.split("-")]
    lowest, highest = parts[0], parts[-1]
    if len(parts) == 1 and lowest in (1, 2):
        return "1st Place" if lowest == 1 else "2nd Place"
    for size in (4, 8, 16, 32):
        if highest <= size:
            return f"Top {size}"
    raise ValueError(f"No finish for place {place}")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def player_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(name))


def match_event(players: Iterable[str], day: date, candidates: List[Top8Event], days: int = 1) -> Optional[Top8Event]:
    keys = {key for key in map(player_key, players) if key}
    best: Optional[Top8Event] = None
    best_shared = 0
    for candidate in candidates:
        if abs(candidate.date - day) > timedelta(days=days):
            continue
        theirs = {key for key in (player_key(deck.player) for deck in candidate.decks) if key}
        shared = len(keys & theirs)
        if shared > best_shared and shared * 2 >= len(theirs):
            best, best_shared = candidate, shared
    return best


def names_by_player(event: Top8Event) -> Dict[str, str]:
    names: Dict[str, str] = {}
    repeated = set()
    for deck in event.decks:
        key = player_key(deck.player)
        if not key:
            continue
        if key in names:
            repeated.add(key)
        names[key] = deck.archetype
    return {key: name for key, name in names.items() if key not in repeated}


def archetype_id(format: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-")
    return f"{format}-{slug}"
