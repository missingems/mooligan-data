"""What a commander guide is built from on EDHREC: the commander's page, its theme pages and its bracket pages.

EDHREC's data, used with their permission and read at their pace: one page at a time with a pause between.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)

COMMANDER_URL = "https://json.edhrec.com/pages/commanders"
BRACKET_PAGES = {1: "exhibition", 2: "core", 3: "upgraded", 4: "optimized", 5: "cedh"}
# EDHREC's new cards are a week's guesses, not what the decks settled on.
SKIPPED_LISTS = {"newcards"}


@dataclass
class Card:
    name: str
    decks: int
    of_decks: int
    synergy: float = 0.0
    section: str = ""

    @property
    def inclusion(self) -> float:
        return self.decks / self.of_decks if self.of_decks else 0.0


@dataclass
class Page:
    """One EDHREC commander page: its decks, the cards they play, and how they split by theme and bracket."""

    name: str
    decks: int
    cards: Dict[str, Card]
    color_identity: Optional[List[str]] = None
    scryfall_id: Optional[str] = None
    themes: List[dict] = field(default_factory=list)
    bracket_decks: Dict[int, int] = field(default_factory=dict)
    lands: Optional[int] = None
    basics: Optional[int] = None


def parse_page(body: Optional[dict]) -> Optional[Page]:
    """The page, or None when it has no decks."""
    container = ((body or {}).get("container") or {}).get("json_dict") or {}
    card = container.get("card") or {}
    decks = card.get("num_decks")
    if not isinstance(decks, int) or decks <= 0:
        return None
    cards: Dict[str, Card] = {}
    for cardlist in container.get("cardlists") or []:
        if cardlist.get("tag") in SKIPPED_LISTS:
            continue
        for view in cardlist.get("cardviews") or []:
            name = view.get("name")
            if not name or name in cards or not isinstance(view.get("num_decks"), int):
                continue
            synergy = view.get("synergy")
            cards[name] = Card(
                name=name,
                decks=view["num_decks"],
                of_decks=view.get("potential_decks") or decks,
                synergy=float(synergy) if isinstance(synergy, (int, float)) else 0.0,
                section=cardlist.get("tag") or "",
            )
    themes = [
        {"slug": tag["slug"], "name": tag["value"], "decks": tag["count"]}
        for tag in body.get("tag_counts") or []
        if tag.get("slug") and tag.get("value") and isinstance(tag.get("count"), int)
    ]
    brackets = {int(level): count for level, count in (body.get("bracket_counts") or {}).items() if str(level).isdigit() and isinstance(count, int)}
    return Page(
        name=card.get("name") or "",
        decks=decks,
        cards=cards,
        color_identity=card.get("color_identity"),
        scryfall_id=card.get("id"),
        themes=themes,
        bracket_decks=brackets,
        lands=body.get("land") if isinstance(body.get("land"), int) else None,
        basics=body.get("basic") if isinstance(body.get("basic"), int) else None,
    )


def published_page(page: dict) -> Page:
    """The commander's own page as the scrape publishes it (edh/commanders/{slug}.json), so it is not read again."""
    cards: Dict[str, Card] = {}
    for section in page.get("sections") or []:
        if section.get("tag") in SKIPPED_LISTS:
            continue
        for card in section.get("cards") or []:
            if card.get("name") and card["name"] not in cards and isinstance(card.get("decks"), int):
                cards[card["name"]] = Card(
                    name=card["name"],
                    decks=card["decks"],
                    of_decks=card.get("of_decks") or page.get("decks") or 0,
                    synergy=card.get("synergy") or 0.0,
                    section=section.get("tag") or "",
                )
    return Page(
        name=page.get("name") or "",
        decks=page.get("decks") or 0,
        cards=cards,
        color_identity=page.get("color_identity"),
        scryfall_id=page.get("scryfall_id"),
        themes=list(page.get("themes") or []),
        bracket_decks={int(level): count for level, count in (page.get("bracket_decks") or {}).items()},
        lands=page.get("lands"),
        basics=page.get("basics"),
    )


@dataclass
class SubPages:
    """The commander's theme pages and bracket pages, each None when EDHREC has none."""

    themes: Dict[str, Optional[Page]]
    brackets: Dict[int, Optional[Page]]


def read_sub_pages(
    slug: str,
    themes: List[str],
    fetch: Callable[[str], Optional[dict]],
    delay: float = 1.0,
) -> SubPages:
    """The given theme pages, then the five bracket pages, one at a time with `delay` seconds between."""
    def read(path: str) -> Optional[Page]:
        time.sleep(delay)
        return parse_page(fetch(f"{COMMANDER_URL}/{slug}/{path}.json"))

    return SubPages(
        themes={theme: read(theme) for theme in themes},
        brackets={level: read(path) for level, path in BRACKET_PAGES.items()},
    )
