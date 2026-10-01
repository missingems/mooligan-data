"""The colours of a deck, from the mana costs of the cards in it.

Two readings of the same costs: `deck_colors` is the set of colours a deck is built in (what an
MTGGoldfish tile shows as pips), and `color_weights` says how much of each colour its mana symbols
ask for. Both read Scryfall's `mana_cost` as kept by `scryfall.card_catalog`.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence

from .cards import slug

COLORS = "WUBRG"
# What a symbol can ask for: the five colours, and colourless mana.
_MANA = ("W", "U", "B", "R", "G", "C")
_SYMBOL = re.compile(r"\{([^}]+)\}")


def mana_symbols(cost: Optional[str]) -> List[List[str]]:
    """The colours each symbol of a mana cost asks for, as a list per symbol.

    `{R}` is `["R"]`, `{2/W}` (pay two generic or one white) `["W"]`, `{W/U}` `["W", "U"]` and `{C}` `["C"]`.
    Phyrexian symbols (`{R/P}`, payable with life), generic ones (`{3}`), `{X}` and snow `{S}` are skipped.
    """
    symbols = []
    for token in _SYMBOL.findall(cost or ""):
        parts = token.split("/")
        if "P" in parts:
            continue
        colors = [part for part in parts if part in _MANA]
        if colors:
            symbols.append(colors)
    return symbols


def deck_colors(cards: Sequence[Sequence], catalog: Dict[str, dict]) -> Optional[List[str]]:
    """The colours a deck is built in, as WUBRG letters in WUBRG order; `[]` for a colourless deck.

    `cards` are `[quantity, name]` pairs, the mainboard and the sideboard together, and `catalog` is
    the card catalog by slug. A land never counts. The colours are those of the cards' one-colour
    symbols, or, in a deck with none, of its hybrid symbols (a deck of `{W/U}` cards is white and
    blue). Colourless `{C}` is not a colour. `None` when the catalog knows no non-land card of the
    deck, so nothing can be said (an empty or unrecognised list is not a colourless one).
    """
    solid, hybrid, known = set(), set(), False
    for _, name in cards:
        card = catalog.get(slug(name))
        if card is None or card.get("land"):
            continue
        known = True
        for colors in mana_symbols(card.get("mana_cost")):
            colors = [color for color in colors if color != "C"]
            if len(colors) == 1:
                solid.add(colors[0])
            else:
                hybrid.update(colors)
    if not known:
        return None
    found = solid or hybrid
    return [color for color in COLORS if color in found]


def color_weights(mainboard: Sequence[Sequence], catalog: Dict[str, dict]) -> Optional[Dict[str, float]]:
    """How much of each colour a mainboard's mana symbols ask for, as fractions that sum to 1.

    Keys are the colours with some weight, from `W`, `U`, `B`, `R`, `G` and `C` (colourless). Each
    symbol counts once per copy of its card, lands excluded. A hybrid symbol is split among the colours
    it names that the deck plays (see `deck_colors`), or among all of them when it plays none. Phyrexian
    and generic symbols count nothing, so a deck with no symbol at all (artifacts and lands) is
    `{"C": 1.0}`. `None` when the catalog knows no non-land card of the deck.
    """
    played = set(deck_colors(mainboard, catalog) or [])
    weights: Dict[str, float] = {}
    known = False
    for quantity, name in mainboard:
        card = catalog.get(slug(name))
        if card is None or card.get("land"):
            continue
        known = True
        for colors in mana_symbols(card.get("mana_cost")):
            shared = colors
            if len(colors) > 1:
                shared = [color for color in colors if color in played] or colors
            for color in shared:
                weights[color] = weights.get(color, 0.0) + quantity / len(shared)
    if not known:
        return None
    total = sum(weights.values())
    if total == 0:
        return {"C": 1.0}
    return {color: weight / total for color, weight in weights.items()}
