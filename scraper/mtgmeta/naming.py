"""Names the archetypes of an MTGO event's decks: MTGTop8's name for the same player, else the nearest named list, else colours."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .clusters import THRESHOLD, Profile, deck_vector, profile, similarity
from .colors import deck_colors
from .models import Deck, Event, EventResult
from .mtgtop8 import Top8Event, archetype_id, names_by_player, player_key

COLORLESS = "Colorless"
UNKNOWN = "Other"


@dataclass
class NamingStats:
    top8: int = 0
    lists: int = 0
    colors: int = 0


def _board(cards: Iterable) -> List[list]:
    return [[card.quantity, card.card_name] for card in cards]


def _set_name(deck: Deck, results: Dict[str, EventResult], name: str, key: Optional[str]) -> None:
    deck.archetype = name
    deck.archetype_id = key
    result = results.get(deck.deck_id)
    if result is not None:
        result.archetype = name
        result.archetype_id = key


def name_from_top8(event: Event, decks: Sequence[Deck], top8: Top8Event, format: str) -> int:
    """Gives each deck of a player MTGTop8 names once the MTGTop8 name and id, on the deck and on its result. Returns the decks named.

    A player with two decks in the event is skipped, as MTGTop8's own repeated players are.
    """
    names = names_by_player(top8)
    keys = [player_key(deck.player) for deck in decks]
    results = {result.deck_id: result for result in event.results}
    named = 0
    for deck, key in zip(decks, keys):
        if key in names and keys.count(key) == 1:
            _set_name(deck, results, names[key], archetype_id(format, names[key]))
            named += 1
    return named


def name_by_lists(
    unnamed: Sequence[Deck],
    named: Iterable[Deck],
    catalog: Dict[str, dict],
    threshold: float = THRESHOLD,
    results: Iterable[EventResult] = (),
) -> int:
    """Gives each unnamed deck the archetype whose average list scores highest against its own, at `threshold` or more.

    Lists are mainboard non-lands as in clusters.py. `named` are the decks that already have an `archetype_id`;
    a tie goes to the archetype with more decks. A matching result in `results` is named with its deck.
    Returns the decks named.
    """
    lands = {key for key, card in catalog.items() if card.get("land")}
    vectors: Dict[str, List[Profile]] = {}
    names: Dict[str, str] = {}
    for deck in named:
        if deck.archetype_id:
            vectors.setdefault(deck.archetype_id, []).append(deck_vector(_board(deck.mainboard), lands))
            names[deck.archetype_id] = deck.archetype
    profiles = {key: profile(group) for key, group in vectors.items()}
    by_deck = {result.deck_id: result for result in results}
    count = 0
    for deck in unnamed:
        vector = deck_vector(_board(deck.mainboard), lands)
        scored = [(similarity(vector, average), len(vectors[key]), key) for key, average in profiles.items()]
        if not scored:
            continue
        score, _, key = max(scored, key=lambda item: (item[0], item[1], item[2]))
        if score >= threshold:
            _set_name(deck, by_deck, names[key], key)
            count += 1
    return count


def name_by_colors(unnamed: Sequence[Deck], catalog: Dict[str, dict], results: Iterable[EventResult] = ()) -> int:
    """Gives each unnamed deck its colour letters in WUBRG order ("UR") with no id, or "Colorless".

    A deck the catalog knows no spell of is called "Other" and isn't counted. Returns the decks named by colours.
    """
    by_deck = {result.deck_id: result for result in results}
    count = 0
    for deck in unnamed:
        colors = deck_colors(_board(deck.mainboard + deck.sideboard), catalog)
        if colors is None:
            _set_name(deck, by_deck, UNKNOWN, None)
            continue
        _set_name(deck, by_deck, "".join(colors) or COLORLESS, None)
        count += 1
    return count


def name_event(
    format: str,
    event: Event,
    decks: Sequence[Deck],
    top8: Optional[Top8Event],
    reference_decks: Iterable[Deck],
    catalog: Dict[str, dict],
) -> NamingStats:
    """Names an event's results and decks in place: MTGTop8's names, then the nearest named list, then colours.

    `reference_decks` are the named decks of the window; the event's decks MTGTop8 named join them.
    """
    stats = NamingStats()
    if top8 is not None:
        stats.top8 = name_from_top8(event, decks, top8, format)
    named = {deck.deck_id: deck for deck in reference_decks if deck.archetype_id}
    named.update({deck.deck_id: deck for deck in decks if deck.archetype_id})
    stats.lists = name_by_lists([deck for deck in decks if not deck.archetype], named.values(), catalog, results=event.results)
    stats.colors = name_by_colors([deck for deck in decks if not deck.archetype], catalog, event.results)
    return stats
