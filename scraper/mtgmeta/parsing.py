"""Pure parsing shared by the scrapers: event tiers, plain-text decklists and the place a finish stands for."""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

from .models import DeckCard

_DECK_LINE = re.compile(r"^\s*(\d+)\s*x?\s+(.+?)\s*$")
_ORDINAL_PLACE = re.compile(r"^(\d+)(?:st|nd|rd|th) Place$")
_TOP_PLACE = re.compile(r"^Top (\d+)$")


# Event tiers by name, first match wins. Names are as mtgo.com and MTGTop8 write them.
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


def place(finish: str) -> Optional[int]:
    """The place a finish stands for: "5th Place" is 5, "Top 8" its lowest place, 5; None for a record like "5-0"."""
    ordinal = _ORDINAL_PLACE.match(finish or "")
    if ordinal:
        return int(ordinal.group(1))
    top = _TOP_PLACE.match(finish or "")
    if top:
        return int(top.group(1)) // 2 + 1
    return None


def parse_decklist(text: str) -> Tuple[List[DeckCard], List[DeckCard]]:
    """Splits a plain-text decklist: mainboard, a blank line, then sideboard."""
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
