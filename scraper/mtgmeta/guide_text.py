"""The summaries of a data-built guide, written from its numbers by template."""
from __future__ import annotations

from typing import List, Optional, Sequence

from .guide_brackets import NAMES

RULES = {
    1: "No Game Changers, no mass land denial, no extra turns and no two-card combos.",
    2: "No Game Changers, no mass land denial, a couple of extra turns at most and no two-card combos.",
    3: "Up to three Game Changers, no mass land denial, a couple of extra turns at most, and no two-card combo that wins early.",
    4: "Anything legal goes: Game Changers, fast mana, mass land denial, extra turns and compact combos.",
    5: "Anything legal goes, tuned to win as fast and as reliably as the competitive metagame demands.",
}


def short_name(name: str) -> str:
    """ "Atraxa, Praetors' Voice" -> "Atraxa"; a partner pair keeps both first names."""
    return " and ".join(half.strip().split(",")[0] for half in name.split("//"))


def listing(names: Sequence[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def levels_text(levels: Sequence[int]) -> str:
    low, high = min(levels), max(levels)
    return f"Bracket {low}" if low == high else f"Brackets {low} to {high}"


def combo_text(combo: dict) -> str:
    return f"{listing([card['name'] for card in combo['cards']])} ({combo['results'][0].rstrip('.')})"


def style_summary(
    commander: str,
    theme: str,
    decks: int,
    total: int,
    levels: Sequence[int],
    mode: Optional[int],
    signature: Sequence[str],
    combo: Optional[dict],
) -> str:
    who = short_name(commander)
    share = decks * 100 / total if total else 0
    parts = [
        f"{theme} is how {decks:,} of {who}'s {total:,} decks on EDHREC are built ({share:.0f}%)."
        if decks < total else f"The cards most of {who}'s {total:,} decks on EDHREC play."
    ]
    if signature:
        parts.append(f"It leans on {listing(signature)}.")
    played = f"It is played at {levels_text(levels)}"
    parts.append(f"{played}, most often {mode} ({NAMES[mode]})." if mode else f"{played}.")
    if combo:
        parts.append(f"Its most played combo, from Bracket {combo['bracket']}, is {combo_text(combo)}.")
    return " ".join(parts)


def bracket_summary(commander: str, level: int, decks: Optional[int], lifted: List[str]) -> str:
    who = short_name(commander)
    parts = []
    if decks:
        parts.append(f"{decks:,} of {who}'s decks on EDHREC are built for Bracket {level}, {NAMES[level]}.")
    parts.append(RULES[level])
    if lifted:
        parts.append(f"Compared with {who}'s other decks, these play more of {listing(lifted)}.")
    return " ".join(parts)
