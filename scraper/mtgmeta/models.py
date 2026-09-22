"""Records written to Firestore; field names match functions/src/shared/schema.ts."""
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


@dataclass
class EventSummary:
    """An event as the tournaments list shows it, before its own page is read."""

    event_id: str
    event_name: str
    date: Optional[datetime]


@dataclass
class Event:
    event_id: str
    event_name: str
    format: str
    date: datetime
    results: List[EventResult]
    url: str


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
    event_id: str


def to_document(record: Any, drop: tuple = ()) -> Dict[str, Any]:
    document = asdict(record)
    for key in drop:
        document.pop(key, None)
    return document


@dataclass
class RunReport:
    meta: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    decks_written: int = 0
    decks_skipped: int = 0
    errors: List[str] = field(default_factory=list)
