"""Pure HTML/text parsing of MTGGoldfish pages, kept apart from the browser so it can be tested."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .models import Archetype, DeckCard, Event, EventResult, EventSummary, Meta

BASE_URL = "https://www.mtggoldfish.com"

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PERCENT = re.compile(r"([\d.]+)\s*%")
_COUNT = re.compile(r"\((\d[\d,]*)\)")
_ARCHETYPE_HREF = re.compile(r"/archetype/([^/#?]+)")
_TOURNAMENT_HREF = re.compile(r"^/tournament/(\d+)")
_DECK_HREF = re.compile(r"/deck/(\d+)")
_DECK_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$")


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
            )
        )
    if not archetypes:
        raise ParseError(f"No archetype tiles on the {format} metagame page")
    return Meta(format=format, timeframe=timeframe, archetypes=archetypes)


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
            )
        )

    name = _event_name(soup) or (summary.event_name if summary else f"Tournament {event_id}")
    date = _labelled_date(soup) or (summary.date if summary else None) or parse_date(name)
    if date is None:
        raise ParseError(f"No date on tournament {event_id}")
    return Event(
        event_id=event_id,
        event_name=name,
        format=format,
        date=date,
        results=results,
        url=f"{BASE_URL}/tournament/{event_id}",
    )


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


def _labelled_date(soup: BeautifulSoup) -> Optional[datetime]:
    label = soup.find(string=re.compile(r"Date:\s*\d{4}-\d{2}-\d{2}"))
    return parse_date(str(label)) if label else None
