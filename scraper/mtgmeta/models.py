"""Scraped records; their fields become the published JSON (see docs/data-format.md)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Archetype:
    name: str
    percentage: float
    id: str
    deck_count: Optional[int] = None
    # The featured list on the archetype's MTGGoldfish page, stored in `decks`.
    deck_id: Optional[str] = None


@dataclass
class Meta:
    format: str
    timeframe: str
    archetypes: List[Archetype]

    @property
    def doc_id(self) -> str:
        return f"{self.format}_{self.timeframe}"


@dataclass
class EventResult:
    player: str
    archetype: str
    finish: str
    deck_id: str
    # Set when the deck appears in an archetype's list, whose name then replaces
    # the pilot's own deck title (leagues show titles like "UR").
    archetype_id: Optional[str] = None


@dataclass
class ArchetypeResult:
    """One row of an archetype's deck list on MTGGoldfish."""

    deck_id: str
    date: datetime
    player: str
    event_id: Optional[str]
    event_name: str
    finish: str


@dataclass
class ArchetypeHistory:
    format: str
    archetype_id: str
    name: str
    deck_id: Optional[str]
    featured_player: Optional[str]
    results: List[ArchetypeResult]

    @property
    def doc_id(self) -> str:
        return f"{self.format}_{self.archetype_id}"


@dataclass
class EventSummary:
    """An event as a listing shows it, before its own page is read."""

    event_id: str
    event_name: str
    date: Optional[datetime]
    # The search results give the decklist count; the tournaments list does not.
    decklists: Optional[int] = None


@dataclass
class Event:
    event_id: str
    event_name: str
    format: str
    date: datetime
    results: List[EventResult]
    url: str
    # Pro Tour, Regional Championship, RCQ and so on: see parsing.event_kind.
    kind: str = "other"
    # Where MTGGoldfish took the results from: "mtgo.com", "melee.gg", or None.
    source: Optional[str] = None


@dataclass
class DeckCard:
    quantity: int
    card_name: str


@dataclass
class Deck:
    deck_id: str
    player: str
    archetype: str
    mainboard: List[DeckCard]
    sideboard: List[DeckCard]
    format: str
    # None for an archetype's featured deck, which is not from a scraped event.
    event_id: Optional[str]
    # The archetype's MTGGoldfish id, when the deck is in a tracked archetype's list.
    archetype_id: Optional[str] = None


@dataclass
class FeaturedDeck:
    deck_id: str
    player: str


def to_document(record: Any, drop: tuple = ()) -> Dict[str, Any]:
    document = asdict(record)
    for key in drop:
        document.pop(key, None)
    return document


@dataclass
class RunReport:
    meta: List[str] = field(default_factory=list)
    archetypes: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    decks_written: int = 0
    decks_skipped: int = 0
    errors: List[str] = field(default_factory=list)
