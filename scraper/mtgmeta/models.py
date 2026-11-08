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
    # The archetype's featured list: the newest best-placed deck, stored in `decks`.
    deck_id: Optional[str] = None
    # WUBRG letters in WUBRG order; empty, since no source shows tile pips (the colours come from decklists).
    colors: List[str] = field(default_factory=list)
    # Card names; empty, since no source shows tile key cards (they come from the archetype's hand).
    key_cards: List[str] = field(default_factory=list)


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
    # WUBRG letters in WUBRG order, when a source gives them; None otherwise (the colours come from the decklist).
    colors: Optional[List[str]] = None


@dataclass
class ArchetypeResult:
    """One row of an archetype's deck list."""

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
class Event:
    event_id: str
    event_name: str
    format: str
    date: datetime
    results: List[EventResult]
    url: str
    # Pro Tour, Regional Championship, RCQ and so on: see parsing.event_kind.
    kind: str = "other"
    # Where the results come from: "mtgo.com", or what MTGTop8 names as its source ("melee.gg" and so on), or None.
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
    # The archetype's id, when the deck is in a tracked archetype's list.
    archetype_id: Optional[str] = None


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
    # Decks wanted but left for the next run: past an allowance, or not reached before the downloads stopped.
    decks_deferred: int = 0
    named_by_top8: int = 0
    named_by_lists: int = 0
    named_by_colors: int = 0
    # What a site's refusal looked like, when it stopped the run's requests to that site.
    deck_block: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    # Things worth a look that do not fail the run.
    warnings: List[str] = field(default_factory=list)
