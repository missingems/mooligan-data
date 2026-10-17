"""Archetypes MTGGoldfish names apart that play one deck, found from their decklists. A dry run: it writes nothing.

`python -m mtgmeta clusters DIR --format modern --days 7` reads DIR's snapshots and `state/deck-cards`, and prints
the pairs of archetypes whose average lists look alike, the groups they would merge into, and which results with no
archetype would join a group. See `similarity` for how two lists are compared.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cards import slug
from .popular import _deck_ids, _parse, deck_dates

MAX_COPIES = 4
THRESHOLD = 0.6
REPORT_THRESHOLD = 0.4

Profile = Dict[str, float]


def deck_vector(board: Iterable[Sequence], lands: Set[str]) -> Profile:
    """A mainboard's nonland cards by slug, each at its copies capped at `MAX_COPIES`."""
    copies: Dict[str, int] = {}
    for quantity, name in board:
        key = slug(name)
        if key in lands:
            continue
        copies[key] = copies.get(key, 0) + quantity
    return {key: min(quantity, MAX_COPIES) for key, quantity in copies.items()}


def profile(vectors: Sequence[Profile]) -> Profile:
    """An archetype's average list: each card at the share of decks that play it times its average copies in them.

    That product is the card's capped copies summed over every deck, divided by the decks.
    """
    total: Profile = {}
    for vector in vectors:
        for key, quantity in vector.items():
            total[key] = total.get(key, 0) + quantity
    return {key: quantity / len(vectors) for key, quantity in total.items()} if vectors else {}


def similarity(a: Profile, b: Profile) -> float:
    """The weighted cosine of two lists, 0 to 1.

    Cosine, not weighted Jaccard: a result's single list is also scored against a group's average, and Jaccard's
    sum of maxima charges the list for every flex slot of the average it doesn't play. Cosine squares the weights,
    so the shared core of 4-ofs decides it.
    """
    dot = sum(weight * b[key] for key, weight in a.items() if key in b)
    norms = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
    return dot / norms if norms else 0.0


@dataclass
class Archetype:
    archetype_id: str
    name: str
    decks: int
    vectors: List[Profile]
    profile: Profile = field(default_factory=dict)

    def __post_init__(self):
        if not self.profile:
            self.profile = profile(self.vectors)

    @property
    def lists(self) -> int:
        return len(self.vectors)


@dataclass
class Group:
    archetype_id: str
    name: str
    members: List[Archetype]
    profile: Profile

    @property
    def decks(self) -> int:
        return sum(member.decks for member in self.members)

    @property
    def lists(self) -> int:
        return sum(member.lists for member in self.members)


@dataclass
class Pair:
    score: float
    a: Archetype
    b: Archetype


def score_pairs(archetypes: Sequence[Archetype]) -> List[Pair]:
    """Every pair of archetypes with its similarity, highest first."""
    pairs = [
        Pair(similarity(a.profile, b.profile), a, b)
        for index, a in enumerate(archetypes)
        for b in archetypes[index + 1 :]
    ]
    pairs.sort(key=lambda pair: (-pair.score, pair.a.archetype_id, pair.b.archetype_id))
    return pairs


def _leader(members: Sequence[Archetype]) -> Archetype:
    return max(members, key=lambda member: (member.decks, member.lists, member.archetype_id))


def merge(archetypes: Sequence[Archetype], threshold: float = THRESHOLD, pairs: Optional[List[Pair]] = None) -> List[Group]:
    """The archetypes joined wherever a pair scores at least `threshold`, each group under its member with the most decks.

    Every archetype is in one group, alone when nothing is close to it. Largest groups first.
    """
    parent = {archetype.archetype_id: archetype.archetype_id for archetype in archetypes}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for pair in pairs if pairs is not None else score_pairs(archetypes):
        if pair.score < threshold:
            break
        a, b = root(pair.a.archetype_id), root(pair.b.archetype_id)
        if a != b:
            parent[b] = a
    members: Dict[str, List[Archetype]] = {}
    for archetype in archetypes:
        members.setdefault(root(archetype.archetype_id), []).append(archetype)
    groups = []
    for group in members.values():
        leader = _leader(group)
        ordered = sorted(group, key=lambda member: (member.archetype_id != leader.archetype_id, -member.decks, member.name))
        groups.append(Group(leader.archetype_id, leader.name, ordered, profile([v for m in group for v in m.vectors])))
    groups.sort(key=lambda group: (-group.decks, group.name))
    return groups


def assign(vectors: Dict[str, Profile], groups: Sequence[Group], threshold: float = THRESHOLD) -> Dict[str, Tuple[Group, float]]:
    """Each deck's closest group and its score, for the decks that score at least `threshold` against one."""
    assigned = {}
    for deck_id, vector in vectors.items():
        scored = [(similarity(vector, group.profile), group) for group in groups]
        if not scored:
            continue
        score, group = max(scored, key=lambda item: (item[0], item[1].decks))
        if score >= threshold:
            assigned[deck_id] = (group, score)
    return assigned


@dataclass
class Window:
    decks: int
    lists: int
    archetypes: List[Archetype]
    unassigned: Dict[str, Tuple[str, Optional[Profile]]]


def window(document: dict, deck_cards: Dict[str, dict], lands: Set[str], days: int) -> Window:
    """The archetypes of a snapshot's last `days` days with their decklists, and the results with no archetype.

    A deck belongs to an archetype by the archetype's results first, then by an event result naming its id, as the
    snapshot store counts them. The window ends on the snapshot's own date.
    """
    dates = deck_dates(document)
    in_window = set(_deck_ids(dates, _parse(document["generated_at"]), days))
    names = {key: archetype["name"] for key, archetype in document.get("archetypes", {}).items()}
    membership: Dict[str, str] = {}
    for key, archetype in document.get("archetypes", {}).items():
        for result in archetype.get("results", []):
            membership.setdefault(result["deck_id"], key)
    titles: Dict[str, str] = {}
    for event in document.get("events", []):
        for result in event.get("results", []):
            if result.get("archetype_id"):
                membership.setdefault(result["deck_id"], result["archetype_id"])
                names.setdefault(result["archetype_id"], result.get("archetype") or result["archetype_id"])
            else:
                titles.setdefault(result["deck_id"], result.get("archetype") or "Other")
    counts: Dict[str, int] = {}
    vectors: Dict[str, List[Profile]] = {}
    for deck_id, key in membership.items():
        if deck_id not in in_window:
            continue
        counts[key] = counts.get(key, 0) + 1
        if deck_id in deck_cards:
            vectors.setdefault(key, []).append(deck_vector(deck_cards[deck_id].get("m", []), lands))
    archetypes = [Archetype(key, names[key], counts[key], vectors[key]) for key in sorted(vectors)]
    unassigned = {
        deck_id: (title, deck_vector(deck_cards[deck_id].get("m", []), lands) if deck_id in deck_cards else None)
        for deck_id, title in titles.items()
        if deck_id in in_window and deck_id not in membership
    }
    in_scope = {deck_id for deck_id in in_window if deck_id in membership or deck_id in unassigned}
    return Window(len(in_scope), sum(1 for deck_id in in_scope if deck_id in deck_cards), archetypes, unassigned)


def _label(archetype) -> str:
    return f"{archetype.name} ({archetype.decks} decks, {archetype.lists} lists)"


def report(format: str, days: int, document: dict, deck_cards: Dict[str, dict], lands: Set[str], threshold: float, floor: float) -> List[str]:
    """The dry run's lines for one format and window."""
    found = window(document, deck_cards, lands, days)
    lines = [
        f"== {format} {days}d (snapshot {document['generated_at']}): {found.decks} decks, {found.lists} with lists, "
        f"{len(found.archetypes)} archetypes with lists"
    ]
    pairs = score_pairs(found.archetypes)
    lines.append(f"-- Pairs at or above {floor:.2f}")
    for pair in pairs:
        if pair.score < floor:
            break
        mark = "*" if pair.score >= threshold else " "
        lines.append(f"  {mark} {pair.score:.3f}  {_label(pair.a)}  ~  {_label(pair.b)}")
    groups = merge(found.archetypes, threshold, pairs)
    merged = [group for group in groups if len(group.members) > 1]
    lines.append(f"-- Merges at {threshold:.2f}: {len(merged)} groups from {sum(len(g.members) for g in merged)} archetypes")
    for group in merged:
        leader = group.members[0]
        lines.append(f"  {group.name} [{group.archetype_id}] {group.decks} decks, {group.lists} lists")
        for member in group.members[1:]:
            lines.append(f"      <- {_label(member)}  {similarity(member.profile, leader.profile):.3f} to {leader.name}")
        ids = {member.archetype_id for member in group.members}
        chained = [pair for pair in pairs if pair.score < threshold and pair.a.archetype_id in ids and pair.b.archetype_id in ids]
        for pair in chained:
            lines.append(f"      chained, only {pair.score:.3f}: {pair.a.name} ~ {pair.b.name}")
    with_lists = {deck_id: vector for deck_id, (_, vector) in found.unassigned.items() if vector is not None}
    assigned = assign(with_lists, groups, threshold)
    lines.append(
        f"-- Unassigned: {len(found.unassigned)} results, {len(with_lists)} with lists, {len(assigned)} would join a group at {threshold:.2f}"
    )
    by_group: Dict[str, List[Tuple[str, float]]] = {}
    for deck_id, (group, score) in assigned.items():
        by_group.setdefault(group.name, []).append((found.unassigned[deck_id][0], score))
    for name, joined in sorted(by_group.items(), key=lambda item: (-len(item[1]), item[0])):
        shown = ", ".join(f"{title} {score:.2f}" for title, score in sorted(joined, key=lambda item: -item[1]))
        lines.append(f"  {len(joined):3d} -> {name}: {shown}")
    left = [
        (title, max((similarity(vector, group.profile) for group in groups), default=0.0))
        for deck_id, (title, vector) in found.unassigned.items()
        if vector is not None and deck_id not in assigned
    ]
    if left:
        shown = ", ".join(f"{title} {score:.2f}" for title, score in sorted(left, key=lambda item: -item[1]))
        lines.append(f"  left alone: {shown}")
    return lines


def main(argv: Optional[Sequence[str]] = None, catalog: Optional[Dict[str, dict]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mtgmeta clusters", description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("work"), help="data directory, mirroring the R2 bucket")
    parser.add_argument("--format", default="modern", help="comma-separated formats")
    parser.add_argument("--days", default="7", help="comma-separated windows in days")
    parser.add_argument("--threshold", type=float, default=THRESHOLD, help="merge and assign at or above this score")
    parser.add_argument("--report", type=float, default=REPORT_THRESHOLD, help="print pairs at or above this score")
    args = parser.parse_args(argv)
    if catalog is None:
        from .scryfall import card_catalog

        catalog = card_catalog()
    lands = {key for key, card in catalog.items() if card.get("land")}
    for format in (item.strip().lower() for item in args.format.split(",") if item.strip()):
        document = json.loads((args.directory / "snapshots" / f"{format}.json").read_text())
        cards_path = args.directory / "state" / "deck-cards" / f"{format}.json"
        deck_cards = json.loads(cards_path.read_text()) if cards_path.exists() else {}
        for days in (int(item) for item in args.days.split(",") if item.strip()):
            print("\n".join(report(format, days, document, deck_cards, lands, args.threshold, args.report)), flush=True)
    return 0
