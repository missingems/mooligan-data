"""A guide deck's win lines: its Commander Spellbook combos read as pieces -> result -> outlet -> win.

A combo whose own results win (Spellbook's "Win the game", infinite damage, lifeloss or mill, infinite turns, exiling
every opponent's permanents) is a win line as it is. A combo that only makes a resource (infinite mana, tokens,
lifegain, card draw, self-mill, untaps) needs an outlet that turns it into a win, and it must be in the same deck:
first a Spellbook combo the deck also holds that wins with the enabler's pieces and a few more (its chained combo),
else a card whose rules text spends that resource on the opponents (a mana sink such as Walking Ballista, a drain on
creatures entering or dying, a payoff for gaining life or drawing, a card that wins with an empty library). An enabler
with neither is no win line; it stays among the deck's `combos`.

Which lines a deck shows depends on its bracket: none at 1 and 2, where the brackets allow no two-card combos and the
key cards and synergy carry the deck; slow lines at 3, as its rules allow no early two-card win; fast lines first at 4
and 5. A combo shown at a lower bracket of the same style is shown again only when nothing else fits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

MAX_LINES = 3
# A line of at most this many cards (the commander's not counted) and this much mana value in all is fast.
FAST_CARDS = 2
FAST_MANA_VALUE = 6
SHOWN_FROM = 3
FAST_FROM = 4

# Spellbook's results that end the game, as lowercase substrings, and the win they read as.
WINS = (
    ("win the game", "Win the game"),
    ("loses the game", "Win the game"),
    ("lose the game", "Win the game"),
    ("infinite damage", "Infinite damage"),
    ("near-infinite damage", "Infinite damage"),
    ("infinite lifeloss", "Infinite lifeloss"),
    ("near-infinite lifeloss", "Infinite lifeloss"),
    ("infinite life loss", "Infinite lifeloss"),
    ("infinite mill", "Infinite mill"),
    ("infinite turns", "Infinite turns"),
    ("infinite combat", "Infinite combat"),
    ("exile all permanents opponents control", "Exile every opponent's permanents"),
    ("exile all of your opponents' permanents", "Exile every opponent's permanents"),
)
# Results that make a resource, by what an outlet must spend; the first that matches is the combo's.
RESOURCES = (
    ("self-mill", "library"),
    ("card draw", "draw"),
    ("looting", "draw"),
    ("lifegain", "lifegain"),
    ("mana", "mana"),
    ("treasure", "mana"),
    ("creature tokens", "creatures"),
    ("copies of", "creatures"),
    ("etb", "creatures"),
    ("death triggers", "deaths"),
    ("sacrifice", "deaths"),
    ("ltb", "deaths"),
    ("storm", "casts"),
    ("cast triggers", "casts"),
    ("magecraft", "casts"),
    ("untap", "untaps"),
)

_OPPONENTS = re.compile(
    r"(each opponent loses|target opponent loses|target player loses|damage to each opponent|damage to any target"
    r"|damage to target player|damage to target opponent|damage to each player|damage to each creature and each player"
    r"|damage divided[^.]*among any number of targets)"
)
_MANA_SYMBOL = re.compile(r"\{(\d+|x|[wubrgc]|[wubrg]/[wubrgp])\}")
_TRIGGERS = {
    "creatures": re.compile(r"whenever [^.]*?(creature|permanent|token)[^.]*?enters[^.]*"),
    "tokens": re.compile(r"whenever you create[^.]*?token[^.]*"),
    "deaths": re.compile(r"whenever [^.]*?(creature|permanent)[^.]*?(dies|is put into a graveyard)[^.]*"),
    "lifegain": re.compile(r"whenever you gain life[^.]*"),
    "draw": re.compile(r"whenever you draw[^.]*"),
    "casts": re.compile(r"whenever you cast[^.]*"),
}
_EMPTY_LIBRARY = re.compile(
    r"(you win the game[^.]*library|library[^.]*you win the game|if you would draw a card while your library has no cards, you win)"
)
_PAY_LIFE_DAMAGE = re.compile(r"pay \d+ life:[^\n]*damage")


def _win(clause: str) -> str:
    return "Infinite damage" if "damage" in clause else "Infinite lifeloss"


def win_of(results: Sequence[str]) -> Optional[str]:
    """The win a combo's own results make, or None when they only make a resource."""
    for result in results:
        lowered = result.lower()
        if "self-mill" in lowered:
            continue
        for needle, win in WINS:
            # From a word's start, so "Near-infinite mill" (Spellbook's, often the player's own) is no "infinite mill".
            if re.search(r"(^|\s)" + re.escape(needle), lowered):
                return win
    return None


def resource_of(results: Sequence[str]) -> Optional[str]:
    for result in results:
        lowered = result.lower()
        for needle, resource in RESOURCES:
            if needle in lowered:
                return resource
    return None


def outlet_kinds(entry: dict) -> Dict[str, str]:
    """The resources a card turns into a win, each with the win it makes, read from its rules text.

    A mana sink pays mana (not a tap) for an ability that hurts the opponents, or is an X spell that does (Walking
    Ballista, Crypt Rats, Exsanguinate, Torment of Hailfire). A sacrifice outlet that hurts them spends creatures (Goblin
    Bombardment). A trigger on creatures entering or dying, tokens made, life gained, cards drawn or spells cast that
    hurts them spends that (Impact Tremors, Blood Artist, Mirkwood Bats, Sanguine Bond, Psychosis Crawler, Guttersnipe).
    A card that wins with an empty library spends draws and self-mill (Thassa's Oracle).
    """
    text = (entry.get("oracle_text") or "").lower()
    cost = (entry.get("mana_cost") or "").lower()
    kinds: Dict[str, str] = {}
    for line in text.split("\n"):
        if ":" not in line:
            continue
        paid, effect = line.split(":", 1)
        if "{t}" in paid or "{q}" in paid:
            continue
        hurts = _OPPONENTS.search(effect)
        if _MANA_SYMBOL.search(paid) and (hurts or ("put a +1/+1 counter on" in effect and "remove a +1/+1 counter" in text and "damage" in text)):
            kinds["mana"] = _win(effect if hurts else "damage")
        if re.search(r"sacrifice (a|another) creature", paid) and hurts:
            kinds["creatures"] = kinds["deaths"] = _win(effect)
    if "{x}" in cost and _OPPONENTS.search(text):
        kinds.setdefault("mana", _win(text))
    for kind, trigger in _TRIGGERS.items():
        for match in trigger.finditer(text):
            if _OPPONENTS.search(match.group(0)):
                kinds.setdefault("creatures" if kind == "tokens" else kind, _win(match.group(0)))
    if _PAY_LIFE_DAMAGE.search(text):
        kinds.setdefault("lifegain", "Infinite damage")
    if _EMPTY_LIBRARY.search(text):
        kinds.setdefault("draw", "Win the game")
        kinds["library"] = "Win the game"
    if "storm" in text and "damage" in text:
        kinds.setdefault("casts", "Infinite damage")
    return kinds


def card_ref(name: str, entry: Optional[dict]) -> dict:
    return {"name": (entry or {}).get("name") or name, "oracle_id": (entry or {}).get("oracle_id")}


@dataclass
class Line:
    combo: dict
    outlet: List[str]
    outlet_combo: Optional[str]
    win: str
    order: int
    tier: int
    cards: int
    mana_value: float

    @property
    def speed(self) -> str:
        if self.combo.get("bracket_tag") == "R" or (self.cards <= FAST_CARDS and self.mana_value <= FAST_MANA_VALUE):
            return "fast"
        return "slow"


def deck_lines(
    combos: Sequence[dict], pool: Sequence[dict], deck: Set[str], commanders: Set[str], lookup: Callable[[str], Optional[dict]],
) -> List[Line]:
    """Every win line a deck holds, best first: outright wins, then chained ones, then card outlets; fewer cards, then
    the most played. `combos` are the deck's combos, `pool` every combo of the commander's card pool, most played first."""
    have = deck | commanders
    order = {combo["id"]: index for index, combo in enumerate(pool)}
    winners = [combo for combo in pool if win_of(combo["results"]) and {card["name"] for card in combo["cards"]} <= have]
    outlets = {name: kinds for name in sorted(have) for kinds in [outlet_kinds(lookup(name) or {})] if kinds}
    lines: List[Line] = []

    def mana_value(names: Sequence[str]) -> float:
        return sum((lookup(name) or {}).get("mana_value") or 0.0 for name in names if name not in commanders)

    def counted(names: Sequence[str]) -> int:
        return sum(1 for name in names if name not in commanders)

    for combo in combos:
        pieces = [card["name"] for card in combo["cards"]]
        index = order.get(combo["id"], len(order))
        own = win_of(combo["results"])
        if own:
            lines.append(Line(combo, [], None, own, index, 0, counted(pieces), mana_value(pieces)))
            continue
        chained = sorted(
            (other for other in winners if set(pieces) < {card["name"] for card in other["cards"]}),
            key=lambda other: (len(other["cards"]), order.get(other["id"], len(order))),
        )
        if chained:
            extra = [card["name"] for card in chained[0]["cards"] if card["name"] not in pieces]
            lines.append(Line(combo, extra, chained[0]["id"], win_of(chained[0]["results"]), index, 1, counted(pieces + extra), mana_value(pieces + extra)))
            continue
        resource = resource_of(combo["results"])
        sinks = [name for name, kinds in outlets.items() if resource in kinds and name not in pieces]
        if resource and sinks:
            sink = min(sinks, key=lambda name: ((lookup(name) or {}).get("mana_value") or 0.0, name))
            lines.append(Line(combo, [sink], None, outlets[sink][resource], index, 2, counted(pieces + [sink]), mana_value(pieces + [sink])))
    return sorted(lines, key=lambda line: (line.tier, line.cards, line.order))


def shown(level: int, lines: Sequence[Line], already: Set[str], limit: int = MAX_LINES) -> List[Line]:
    """The lines a deck at `level` shows: none below 3, slow ones at 3, fast ones first from 4; ones not shown at a
    lower level first, and a shown one again only when nothing else fits."""
    if level < SHOWN_FROM:
        return []
    allowed = [line for line in lines if level >= FAST_FROM or line.speed == "slow"]
    if level >= FAST_FROM:
        allowed.sort(key=lambda line: line.speed != "fast")
    fresh = [line for line in allowed if line.combo["id"] not in already][:limit]
    return fresh or allowed[:1]


def line_json(line: Line, lookup: Callable[[str], Optional[dict]]) -> dict:
    return {
        "combo": line.combo["id"],
        "pieces": [{"name": card["name"], "oracle_id": card.get("oracle_id")} for card in line.combo["cards"]],
        "result": line.combo["results"][0],
        "outlet": [card_ref(name, lookup(name)) for name in line.outlet],
        "outlet_combo": line.outlet_combo,
        "win": line.win,
        "speed": line.speed,
    }


def style_lines(
    levels: Sequence[int], deck_combos: Dict[int, List[dict]], deck_names: Dict[int, Set[str]], pool: Sequence[dict],
    commanders: Set[str], lookup: Callable[[str], Optional[dict]],
) -> Dict[int, List[dict]]:
    """Each deck of a style's win lines, lowest bracket first, so a combo is not repeated up the brackets."""
    already: Set[str] = set()
    result: Dict[int, List[dict]] = {}
    for level in sorted(levels):
        picked = shown(level, deck_lines(deck_combos[level], pool, deck_names[level], commanders, lookup), already)
        already |= {line.combo["id"] for line in picked}
        result[level] = [line_json(line, lookup) for line in picked]
    return result
