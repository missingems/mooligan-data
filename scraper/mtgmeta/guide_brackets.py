"""Wizards' Commander Brackets as rules a deck is checked against, and Commander Spellbook's reading of a card pool.

The rules (October 2025): no Game Changers at 1 and 2 and at most three at 3; no mass land denial below 4; no extra
turns at 1, a few never chained at 2 and 3; no two-card combos at 1 and 2, none that wins early at 3. Spellbook's
estimate-bracket says which cards are banned, mass land denial or extra turns, and which combos the pool holds; the
Game Changers are the repo's own list (game_changers.json), Spellbook's flags only cross-checking it.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set

from .guide_combos import SPELLBOOK, USER_AGENT, combos

log = logging.getLogger(__name__)

NAMES = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}
GAME_CHANGERS = {1: 0, 2: 0, 3: 3}
EXTRA_TURNS = {1: 0, 2: 2, 3: 2}
MASS_LAND_DENIAL_FROM = 4
DELAY = 1.0


def post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"}, method="POST"
    )
    time.sleep(DELAY)
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


@dataclass
class Pool:
    """Spellbook's reading of a commander's card pool."""

    game_changers: Set[str] = field(default_factory=set)
    banned: Set[str] = field(default_factory=set)
    mass_land_denial: Set[str] = field(default_factory=set)
    extra_turns: Set[str] = field(default_factory=set)
    combos: List[dict] = field(default_factory=list)


def estimate(commanders: List[str], names: Iterable[str], post: Callable[[str, dict], dict] = post_json) -> Pool:
    deck = {"commanders": [{"card": name} for name in commanders], "main": [{"card": name} for name in names if name not in commanders]}
    return read_estimate(post(f"{SPELLBOOK}/estimate-bracket", deck))


def read_estimate(body: dict) -> Pool:
    pool = Pool()
    for entry in body.get("cards") or []:
        name = (entry.get("card") or {}).get("name")
        if not name:
            continue
        if entry.get("gameChanger"):
            pool.game_changers.add(name)
        if entry.get("banned"):
            pool.banned.add(name)
        if entry.get("massLandDenial"):
            pool.mass_land_denial.add(name)
        if entry.get("extraTurn"):
            pool.extra_turns.add(name)
    pool.combos = combos(body.get("combos") or [], limit=None)
    return pool


@dataclass
class Rules:
    """What a deck at one bracket may hold, checked one card at a time as the deck is filled."""

    level: int
    pool: Pool
    commanders: Set[str]
    game_changers: int = 0
    extra_turns: int = 0

    def allows(self, name: str, deck: Set[str]) -> bool:
        if name in self.pool.game_changers and self.game_changers >= GAME_CHANGERS.get(self.level, 99):
            return False
        if name in self.pool.mass_land_denial and self.level < MASS_LAND_DENIAL_FROM:
            return False
        if name in self.pool.extra_turns and self.extra_turns >= EXTRA_TURNS.get(self.level, 99):
            return False
        have = deck | self.commanders | {name}
        return not any(
            combo["bracket"] > self.level and name in names and names <= have
            for combo in self.pool.combos
            for names in [{card["name"] for card in combo["cards"]}]
        )

    def add(self, name: str) -> None:
        self.game_changers += name in self.pool.game_changers
        self.extra_turns += name in self.pool.extra_turns


def deck_bracket(names: Set[str], pool: Pool, commanders: Set[str]) -> int:
    """The lowest bracket whose rules the deck keeps."""
    have = names | commanders
    changers = len(names & pool.game_changers)
    level = 1
    if changers:
        level = 3 if changers <= GAME_CHANGERS[3] else 4
    if names & pool.mass_land_denial:
        level = max(level, MASS_LAND_DENIAL_FROM)
    turns = len(names & pool.extra_turns)
    if turns:
        level = max(level, 2 if turns <= EXTRA_TURNS[2] else 4)
    for combo in pool.combos:
        if {card["name"] for card in combo["cards"]} <= have:
            level = max(level, combo["bracket"])
    return level


def counts(names: Set[str], pool: Pool) -> Dict[str, int]:
    return {
        "game_changers": len(names & pool.game_changers),
        "mass_land_denial": len(names & pool.mass_land_denial),
        "extra_turns": len(names & pool.extra_turns),
    }


def find_pool(commanders: List[str], names: List[str], post: Callable[[str, dict], dict] = post_json) -> Optional[Pool]:
    try:
        return estimate(commanders, names, post)
    except (OSError, ValueError, KeyError) as error:
        log.warning("Spellbook estimate for %s failed: %s", " // ".join(commanders), error)
        return None
