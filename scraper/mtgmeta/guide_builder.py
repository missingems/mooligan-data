"""A commander deck filled from EDHREC's inclusion rates, as the Mooligan app's Commander builder fills one.

The app's builder (Core/Networking/Sources/Collection/Builder) fills a deck from owned cards; this one fills it from
the cards EDHREC's decks play, best first, under one Commander Bracket's rules. The roles, the role aims, the land
target and the basics split are the app's, so a guide's deck reads the way the app's builder would make it.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

ROLES = ("land", "ramp", "draw", "removal", "counter", "wipe", "protection", "tutor", "payoff", "engine", "combo", "utility")
# The builder's steps with an aim, in the order it fills them; payoffs (everything else) take what is left.
STEPS = (("ramp", ("ramp",), 10), ("draw", ("draw",), 10), ("interaction", ("removal", "counter"), 10), ("wipes", ("wipe",), 3), ("protection", ("protection",), 3))
PAYOFF_ROLES = ("payoff", "engine", "tutor", "combo", "utility")
DEFAULT_LANDS = 36
COLORS = ("W", "U", "B", "R", "G")
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}

_WIPE_NOUNS = (
    "all creatures", "all other creatures", "all nonland permanents", "all other nonland permanents", "all permanents",
    "all artifacts", "all enchantments", "all planeswalkers", "all noncreature", "all nontoken", "all attacking creatures",
    "each creature", "each other creature", "each nonland permanent", "each permanent", "each artifact", "each planeswalker",
)
_GRANT_VERBS = ("gain", "gains", "have", "has")
_DRAW_PHRASES = (
    "draw a card", "draws a card", "draw two", "draws two", "draw three", "draw four", "draw cards", "draws cards",
    "draw x", "draw that many", "draw an additional",
)
_SUPERTYPES = {"Basic", "Elite", "Host", "Legendary", "Ongoing", "Snow", "World"}


def main_types(type_line: str) -> Set[str]:
    types: Set[str] = set()
    for face in type_line.split(" // "):
        types |= {word for word in face.split("—")[0].split() if word not in _SUPERTYPES}
    return types


def _target(text: str, phrase: str) -> Optional[str]:
    index = text.find(phrase)
    if index < 0:
        return None
    after = re.split(r"[.\n]", text[index + len(phrase): index + len(phrase) + 40])[0]
    if "nonland permanent" in after:
        return "nonland"
    if "permanent" in after:
        return "permanent"
    if after.startswith(" artifact") or after.startswith(" enchantment"):
        return "artifact-or-enchantment"
    if "creature" in after:
        return "creature"
    if "planeswalker" in after:
        return "planeswalker"
    return None


def _is_wipe(text: str) -> bool:
    if any(f"{verb} {noun}" in text for verb in ("destroy", "exile", "return") for noun in _WIPE_NOUNS):
        return True
    if "damage to each creature" in text or "damage to each other creature" in text:
        return True
    return any(phrase in text for phrase in ("all creatures get -", "all other creatures get -", "creatures your opponents control get -"))


def _is_removal(text: str) -> bool:
    if _target(text, "destroy target") or _target(text, "exile target"):
        return True
    if "damage to any target" in text or _target(text, "damage to target"):
        return True
    if "to its owner's hand" in text and _target(text, "return target"):
        return True
    return "target creature gets -" in text or "target creature an opponent controls gets -" in text


def _is_ramp(text: str) -> bool:
    if "search your library for" in text and ("land card" in text or "basic land" in text) and "onto the battlefield" in text:
        return True
    if "put a land card from your hand onto the battlefield" in text or "play an additional land" in text:
        return True
    return any(phrase in text for phrase in ("add {", "add one mana", "add two mana", "add three mana"))


def _is_protection(text: str) -> bool:
    if any(f"{verb} {quality}" in text for quality in ("hexproof", "shroud", "protection from") for verb in _GRANT_VERBS):
        return True
    if "phase out" in text or "phases out" in text:
        return True
    return any(f"{verb} indestructible" in text for verb in _GRANT_VERBS)


def role(entry: dict) -> str:
    """The app's `builderRole`: the first job the card's rules text and types say it does."""
    type_line = entry.get("type_line") or ""
    if "Land" in type_line.split(" // ")[0]:
        return "land"
    text = (entry.get("oracle_text") or "").lower()
    types = main_types(type_line)
    if _is_wipe(text):
        return "wipe"
    if "counter target" in text:
        return "counter"
    if _is_removal(text):
        return "removal"
    if _is_ramp(text):
        return "ramp"
    if "search your library for a" in text:
        return "tutor"
    if any(phrase in text for phrase in _DRAW_PHRASES):
        return "draw"
    if _is_protection(text):
        return "protection"
    if types.isdisjoint({"Instant", "Sorcery"}) and ("whenever" in text or "at the beginning of" in text):
        return "engine"
    if types & {"Creature", "Planeswalker"}:
        return "payoff"
    return "utility"


def land_target(ramp: int, average_mana_value: float) -> int:
    return DEFAULT_LANDS - (1 if ramp >= 12 else 0) + (1 if average_mana_value > 3.5 else 0)


@dataclass
class Candidate:
    name: str
    oracle_id: str
    role: str
    score: float
    synergy: float = 0.0
    mana_value: float = 0.0
    mana_cost: str = ""
    price: Optional[float] = None

    @property
    def is_land(self) -> bool:
        return self.role == "land"


def ranked(candidates: Iterable[Candidate]) -> List[Candidate]:
    """The builder's order: inclusion, then synergy, then name."""
    return sorted(candidates, key=lambda card: (-card.score, -card.synergy, card.name))


def average_mana_value(cards: Sequence[Candidate]) -> float:
    spells = [card for card in cards if not card.is_land]
    return sum(card.mana_value for card in spells) / len(spells) if spells else 0.0


def split_basics(count: int, spells: Sequence[Candidate], identity: Sequence[str]) -> Dict[str, int]:
    """The app's `BuilderBasics.split`: the basics shared by the colour pips of the spells, largest remainder first."""
    colors = [color for color in COLORS if color in identity]
    if count <= 0 or not colors:
        return {}
    pips = {color: 0 for color in colors}
    for card in spells:
        for symbol in card.mana_cost.split("}"):
            for color in colors:
                if color in symbol:
                    pips[color] += 1
    total = sum(pips.values())
    weights = pips if total else {color: 1 for color in colors}
    total = sum(weights.values())
    shares = {color: count * weights[color] / total for color in colors}
    split = {color: math.floor(share) for color, share in shares.items()}
    left = count - sum(split.values())
    for color in sorted(colors, key=lambda color: -(shares[color] - split[color]))[:left]:
        split[color] += 1
    return {color: split[color] for color in colors if split[color]}


@dataclass
class Deck:
    cards: List[Candidate]
    basics: Dict[str, int]
    land_target: int

    @property
    def size(self) -> int:
        return len(self.cards) + sum(self.basics.values())


@dataclass
class Filler:
    """Picks cards in the builder's order, each only once and only when `allows` lets it in."""

    allows: Callable[[str, Set[str]], bool]
    on_add: Callable[[str], None]
    names: Set[str] = field(default_factory=set)
    cards: List[Candidate] = field(default_factory=list)

    def take(self, candidates: Iterable[Candidate], count: int) -> List[Candidate]:
        taken: List[Candidate] = []
        for card in candidates:
            if len(taken) >= count:
                break
            if card.name in self.names or not self.allows(card.name, self.names):
                continue
            self.names.add(card.name)
            self.on_add(card.name)
            self.cards.append(card)
            taken.append(card)
        return taken


def fill(
    candidates: Sequence[Candidate],
    slots: int,
    identity: Sequence[str],
    nonbasic_lands: Optional[int] = None,
    allows: Callable[[str, Set[str]], bool] = lambda name, deck: True,
    on_add: Callable[[str], None] = lambda name: None,
) -> Deck:
    """The app's `BuilderAutoFill.fill`, on EDHREC's cards in place of a collection.

    Each step with an aim takes its best cards (ramp, draw and interaction 10 each, wipes and protection 3 each); the
    land target comes from the ramp count and the spells' average mana value; payoffs fill every slot left but the
    lands. The lands are the best nonbasic ones, at most `nonbasic_lands` (EDHREC's average for the decks), and basics
    split by the spells' colour pips make up the rest. A deck the pool cannot fill is topped up with the best cards
    left of any role, so it always has `slots` cards when the pool has them.
    """
    order = ranked(candidates)
    by_role: Dict[str, List[Candidate]] = {}
    for card in order:
        by_role.setdefault(card.role, []).append(card)
    filler = Filler(allows, on_add)
    for _, roles, aim in STEPS:
        filler.take(ranked(card for each in roles for card in by_role.get(each, [])), aim)
    picked = list(filler.cards)
    ramp = sum(1 for card in picked if card.role == "ramp")
    payoffs = ranked(card for each in PAYOFF_ROLES for card in by_role.get(each, []))
    target = land_target(ramp, average_mana_value(picked))
    preview = picked + [card for card in payoffs if card.name not in filler.names][: max(0, slots - target - len(picked))]
    target = land_target(ramp, average_mana_value(preview))
    filler.take(payoffs, max(0, slots - target - len(picked)))
    lands = by_role.get("land", [])
    colors = [color for color in COLORS if color in identity]
    nonbasic = target if not colors or nonbasic_lands is None else min(target, nonbasic_lands)
    filler.take(lands, nonbasic)
    spells = sum(1 for card in filler.cards if not card.is_land)
    if spells < slots - target:
        filler.take([card for card in order if not card.is_land], slots - target - spells)
    if not colors:
        filler.take(order, slots - len(filler.cards))
    spells_played = [card for card in filler.cards if not card.is_land]
    basics = split_basics(slots - len(filler.cards), spells_played, identity)
    return Deck(cards=filler.cards, basics=basics, land_target=target)
