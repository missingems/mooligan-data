"""Pure HTML/text parsing of MTGGoldfish pages, kept apart from the browser so it can be tested."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .models import Archetype, ArchetypeResult, DeckCard, Event, EventResult, EventSummary, FeaturedDeck, Meta

BASE_URL = "https://www.mtggoldfish.com"

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PERCENT = re.compile(r"([\d.]+)\s*%")
_COUNT = re.compile(r"\((\d[\d,]*)\)")
_ARCHETYPE_HREF = re.compile(r"/archetype/([^/#?]+)")
_TOURNAMENT_HREF = re.compile(r"^/tournament/(\d+)")
# The archetype deck table links events as /tournaments/<id>.
_ANY_TOURNAMENT_HREF = re.compile(r"^/tournaments?/(\d+)")
_DECK_HREF = re.compile(r"/deck/(\d+)")
_DOWNLOAD_HREF = re.compile(r"^/deck/download/(\d+)")
_DECK_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$")
_COLOR_LETTERS = "WUBRG"
_COLOR_NAMES = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


# Event tiers by name, first match wins. Names are as MTGGoldfish imports them.
EVENT_KINDS = (
    ("pro_tour", re.compile(r"\bpro tour\b|\bworld championship\b|\bmagic world\b", re.I)),
    ("regional_championship", re.compile(r"\bregional championship\b(?!.*\bqualifier\b)|\bRC\b(?!\s*(super\s+)?qualifier)", re.I)),
    ("rcq", re.compile(r"\bRCQ\b|\bqualifier\b|\bclasificatorio\b|\bqualifikation\b", re.I)),
    ("store_championship", re.compile(r"\bstore championship\b", re.I)),
    ("mtgo_league", re.compile(r"\bleague\b", re.I)),
    ("mtgo_challenge", re.compile(r"\bchallenge\b|\bshowcase\b|\bsuper qualifier\b|\bprelim", re.I)),
)
# The one site whose "League" is Magic Online's: a Modern League posted from there is a daily 5-round
# queue. A paper league imported from melee.gg ("Charlotte Legacy League Season 3") is a local event.
MTGO_LEAGUE_SOURCE = "mtgo.com"

# Cyrillic letters that print like a Latin one, which an event's name can carry by copy and paste
# ("Store Championship" spelt with a Cyrillic ES, U+0421, instead of the Latin C), and the Latin letter each stands for.
_LOOKALIKES = str.maketrans(
    {
        # capitals: A B C E H I J K M O P S T X Y
        "\u0410": "A", "\u0412": "B", "\u0421": "C", "\u0415": "E", "\u041d": "H", "\u0406": "I",
        "\u0408": "J", "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0405": "S",
        "\u0422": "T", "\u0425": "X", "\u0423": "Y",
        # lower case: a c e o p x y, then i j s d h l q w
        "\u0430": "a", "\u0441": "c", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0445": "x",
        "\u0443": "y", "\u0456": "i", "\u0458": "j", "\u0455": "s", "\u0501": "d", "\u04bb": "h",
        "\u04cf": "l", "\u051b": "q", "\u051d": "w",
    }
)


def latin_lookalikes(text: str) -> str:
    """The text with lookalike Cyrillic letters turned into Latin ones, and compatibility forms (full-width letters) folded.

    For matching a name against the patterns here, never for what is stored or shown.
    """
    return unicodedata.normalize("NFKC", text).translate(_LOOKALIKES)


def event_kind(event_name: str, source: Optional[str] = None) -> str:
    """Which tier an event belongs to, from its name; "other" for local and unnamed events.

    `source` is the site the results came from. A League is Magic Online's only when that is mtgo.com,
    so a paper league from melee.gg (or one with no known source) falls through to the later tiers and,
    named only "League", ends as "other".
    """
    name = latin_lookalikes(event_name)
    for kind, pattern in EVENT_KINDS:
        if kind == "mtgo_league" and source != MTGO_LEAGUE_SOURCE:
            continue
        if pattern.search(name):
            return kind
    return "other"


class ParseError(ValueError):
    """The page did not look the way the parser expects (layout change or a challenge page)."""


def parse_date(text: str) -> Optional[datetime]:
    match = _DATE.search(text or "")
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)


def parse_meta(html: str, format: str, timeframe: str) -> Meta:
    soup = BeautifulSoup(html, "html.parser")
    archetypes: List[Archetype] = []
    for tile in soup.select(".archetype-tile"):
        # Each tile has an online and a paper title link; the paper one comes last.
        links = tile.select(".archetype-tile-title a[href]")
        value = tile.select_one(".metagame-percentage .archetype-tile-statistic-value")
        if not links or value is None:
            continue
        link = links[-1]
        slug = _ARCHETYPE_HREF.search(link["href"])
        percent = _PERCENT.search(value.get_text(" ", strip=True))
        if not slug or not percent:
            continue
        count = _COUNT.search(value.get_text(" ", strip=True))
        archetypes.append(
            Archetype(
                name=link.get_text(strip=True),
                percentage=float(percent.group(1)),
                id=slug.group(1),
                deck_count=int(count.group(1).replace(",", "")) if count else None,
                colors=_tile_colors(tile),
                key_cards=_tile_key_cards(tile),
            )
        )
    if not archetypes:
        raise ParseError(f"No archetype tiles on the {format} metagame page")
    return Meta(format=format, timeframe=timeframe, archetypes=archetypes)


def _tile_colors(tile) -> List[str]:
    """The colours a tile shows, as WUBRG letters in WUBRG order; empty for colourless or no pips."""
    return _manacost_colors(tile.select_one(".manacost-container .manacost"))


def _manacost_colors(manacost) -> List[str]:
    """The colours of a `manacost` span, as WUBRG letters in WUBRG order; empty for colourless, no pips or no span.

    The pips are a span labelled "colors: blue red" on a metagame tile and "mana cost: white black green" on
    a tournament page, with an `ms-u ms-r` icon each. The label is read first, and the icons only when it
    names no colour.
    """
    if manacost is None:
        return []
    words = re.findall(r"[a-z]+", (manacost.get("aria-label") or "").lower())
    found = {_COLOR_NAMES[word] for word in words if word in _COLOR_NAMES}
    if not found:
        for icon in manacost.select("i"):
            found |= {letter for letter in _COLOR_LETTERS if f"ms-{letter.lower()}" in icon.get("class", [])}
    return [letter for letter in _COLOR_LETTERS if letter in found]


def _tile_key_cards(tile) -> List[str]:
    """The card names in a tile's key card list, at most three."""
    names = (item.get_text(" ", strip=True) for item in tile.select(".archetype-tile-description ul li"))
    return [name for name in names if name][:3]


def selected_period(html: str) -> Optional[str]:
    """The metagame window the page currently shows, in days (for example "30")."""
    option = BeautifulSoup(html, "html.parser").select_one("select#period option[selected]")
    return option.get("value") if option else None


def parse_tournament_list(html: str) -> List[EventSummary]:
    soup = BeautifulSoup(html, "html.parser")
    events: List[EventSummary] = []
    seen = set()
    for heading in soup.select("h4"):
        link = heading.find("a", href=_TOURNAMENT_HREF)
        if link is None:
            continue
        event_id = _TOURNAMENT_HREF.match(link["href"]).group(1)
        if event_id in seen:
            continue
        seen.add(event_id)
        events.append(
            EventSummary(
                event_id=event_id,
                event_name=link.get_text(strip=True),
                date=parse_date(heading.get_text(" ", strip=True)),
            )
        )
    return events


def parse_tournament_search(html: str) -> Tuple[List[EventSummary], bool]:
    """One page of /tournament_searches/create results, newest first, and whether a next page exists."""
    soup = BeautifulSoup(html, "html.parser")
    events: List[EventSummary] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td", recursive=False)
        link = cells[1].find("a", href=_TOURNAMENT_HREF) if len(cells) >= 2 else None
        if link is None:
            continue
        count = cells[3].get_text(strip=True) if len(cells) >= 4 else ""
        events.append(
            EventSummary(
                event_id=_TOURNAMENT_HREF.match(link["href"]).group(1),
                event_name=link.get_text(strip=True),
                date=parse_date(cells[0].get_text(strip=True)),
                decklists=int(count) if count.isdigit() else None,
            )
        )
    has_next = soup.select_one("ul.pagination li.next:not(.disabled) a[href]") is not None
    return events, has_next


def parse_tournament(html: str, event_id: str, format: str, summary: Optional[EventSummary] = None) -> Event:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.table-tournament")
    if table is None:
        raise ParseError(f"No results table on tournament {event_id}")

    results: List[EventResult] = []
    for row in table.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue  # header and the hidden expand-deck rows
        deck_link = cells[1].find("a", href=_DECK_HREF)
        if deck_link is None:
            continue
        results.append(
            EventResult(
                player=cells[2].get_text(" ", strip=True),
                archetype=deck_link.get_text(strip=True),
                finish=_finish(cells[0].get_text(" ", strip=True)),
                deck_id=_DECK_HREF.search(deck_link["href"]).group(1),
                # Only when the row shows pips: a deck with none is colourless or unknown, which the page can't tell.
                colors=_manacost_colors(cells[1].select_one(".manacost")) or None,
            )
        )

    name = _event_name(soup) or (summary.event_name if summary and summary.event_name else f"Tournament {event_id}")
    date = _labelled_date(soup) or (summary.date if summary else None) or parse_date(name)
    if date is None:
        raise ParseError(f"No date on tournament {event_id}")
    source = _source(soup)
    return Event(
        event_id=event_id,
        event_name=name,
        format=format,
        date=date,
        results=results,
        url=f"{BASE_URL}/tournament/{event_id}",
        kind=event_kind(name, source),
        source=source,
    )


def parse_archetype(html: str, archetype_id: str) -> FeaturedDeck:
    """The deck an archetype page features, and who played it."""
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", href=_DOWNLOAD_HREF)
    if link is None:
        raise ParseError(f"No featured deck on archetype {archetype_id}")
    author = soup.select_one("h1.title .author")
    player = re.sub(r"^by\s+", "", author.get_text(" ", strip=True)) if author else ""
    return FeaturedDeck(deck_id=_DOWNLOAD_HREF.match(link["href"]).group(1), player=player)


def parse_archetype_decks(html: str, archetype_id: str) -> Tuple[List[ArchetypeResult], bool]:
    """One page of /archetype/<id>/decks, newest first, and whether a next page exists."""
    soup = BeautifulSoup(html, "html.parser")
    table = next(
        (t for t in soup.select("table") if [th.get_text(strip=True) for th in t.select("th")][:5] == ["Date", "Deck", "Author", "Event", "Place"]),
        None,
    )
    if table is None:
        raise ParseError(f"No deck table on archetype {archetype_id}")
    results: List[ArchetypeResult] = []
    for row in table.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        deck_link = cells[1].find("a", href=_DECK_HREF)
        date = parse_date(cells[0].get_text(strip=True))
        if deck_link is None or date is None:
            continue
        event_link = cells[3].find("a", href=_ANY_TOURNAMENT_HREF)
        results.append(
            ArchetypeResult(
                deck_id=_DECK_HREF.search(deck_link["href"]).group(1),
                date=date,
                player=cells[2].get_text(" ", strip=True),
                event_id=_ANY_TOURNAMENT_HREF.match(event_link["href"]).group(1) if event_link else None,
                event_name=cells[3].get_text(" ", strip=True),
                finish=_finish(cells[4].get_text(" ", strip=True)),
            )
        )
    has_next = soup.select_one("ul.pagination li.next:not(.disabled) a[href]") is not None
    return results, has_next


def parse_decklist(text: str) -> Tuple[List[DeckCard], List[DeckCard]]:
    """Splits MTGGoldfish's plain-text download: mainboard, a blank line, then sideboard."""
    if "<html" in text[:500].lower():
        raise ParseError("Deck download returned an HTML page instead of a list")
    boards: List[List[DeckCard]] = [[]]
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            if boards[-1]:
                boards.append([])
            continue
        if line.strip().lower() in ("sideboard", "sideboard:"):
            if boards[-1]:
                boards.append([])
            continue
        match = _DECK_LINE.match(line)
        if not match:
            raise ParseError(f"Unexpected decklist line: {line!r}")
        boards[-1].append(DeckCard(quantity=int(match.group(1)), card_name=match.group(2)))
    boards = [board for board in boards if board]
    if not boards:
        raise ParseError("Empty decklist")
    mainboard = boards[0]
    sideboard = [card for board in boards[1:] for card in board]
    return mainboard, sideboard


def _finish(text: str) -> str:
    """Challenges show "1st"; leagues show a record like "5 - 0"."""
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"\d+(st|nd|rd|th)", text):
        return f"{text} Place"
    return re.sub(r"\s*-\s*", "-", text)


def _event_name(soup: BeautifulSoup) -> Optional[str]:
    for heading in soup.select("h2"):
        text = heading.get_text(" ", strip=True)
        if _DATE.search(text):
            return text
    return None


def _source(soup: BeautifulSoup) -> Optional[str]:
    """The site MTGGoldfish imported the results from, as its host name."""
    label = soup.find(string=re.compile(r"Source:"))
    link = label.find_next("a", href=True) if label else None
    if link is None:
        return None
    host = re.sub(r"^https?://(www\.)?", "", link["href"]).split("/")[0]
    return host or None


def _labelled_date(soup: BeautifulSoup) -> Optional[datetime]:
    label = soup.find(string=re.compile(r"Date:\s*\d{4}-\d{2}-\d{2}"))
    return parse_date(str(label)) if label else None
