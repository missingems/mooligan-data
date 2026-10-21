"""The summaries of a data-built guide, written from its numbers by template."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

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


def line_text(line: dict) -> str:
    """ "A and B (Infinite colorless mana), cashed in by C for infinite damage"; an outright win names its result alone."""
    text = f"{listing([card['name'] for card in line['pieces']])} ({line['result'].rstrip('.')})"
    if line["outlet"]:
        text += f", cashed in by {listing([card['name'] for card in line['outlet']])} for {line['win'][0].lower() + line['win'][1:]}"
    return text


def style_summary(
    commander: str,
    theme: str,
    decks: int,
    total: int,
    levels: Sequence[int],
    mode: Optional[int],
    signature: Sequence[str],
    line: Optional[Tuple[int, dict]],
) -> str:
    """The style in a few lines: its share of the commander's decks, its signature cards, its brackets, and its first
    win line at the lowest bracket that shows one."""
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
    if line:
        level, shown = line
        parts.append(f"From Bracket {level} it wins with {line_text(shown)}.")
    return " ".join(parts)


def deck_plan(level: int, key: Sequence[str], synergy: Sequence[dict], lines: Sequence[dict]) -> str:
    """One deck in two or three sentences: what it adds at its bracket, what it leans on, and how it wins."""
    parts = []
    if key:
        parts.append(f"At Bracket {level}, {NAMES[level]}, it adds {listing(key[:3])}.")
    leans = [f"{group['name'][0].lower() + group['name'][1:]} such as {listing([card['name'] for card in group['cards'][:2]])}" for group in synergy[:2]]
    if leans:
        parts.append(f"It leans on {' and '.join(leans)}.")
    if lines:
        parts.append(f"It wins with {line_text(lines[0])}.")
    else:
        payoffs = next((group for group in synergy if group["role"] == "payoff"), None)
        parts.append(
            f"It wins through combat and value, with payoffs like {listing([card['name'] for card in payoffs['cards'][:2]])}."
            if payoffs else "It wins through combat and value rather than a combo."
        )
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
