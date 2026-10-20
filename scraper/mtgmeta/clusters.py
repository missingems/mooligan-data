"""Archetypes MTGGoldfish names apart that play one deck, found from their decklists, and merged when published.

`plan` decides the groups of a snapshot and `apply` turns the snapshot into the one published, with one archetype per
group (see docs/data-format.md). `python -m mtgmeta clusters DIR --format modern --days 7` is a dry run: it reads DIR's
unmerged snapshots (`state/snapshots/`, else `snapshots/`) and `state/deck-cards`, and prints the pairs of archetypes
whose average lists look alike, the groups each window would merge into, which results with no archetype would join a
group, and the groups `plan` publishes with the overrides of `archetype_overrides.json` and the last run's groups
(`state/archetype-groups/`). See `similarity` for how two lists are compared.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cards import slug
from .colors import COLORS, deck_colors
from .explore import archetype_tiles
from .popular import _deck_ids, _parse, deck_dates

MAX_COPIES = 4
THRESHOLD = 0.8
# A member of the last run's group stays in it at this score; a new one needs `THRESHOLD`.
STICKY_THRESHOLD = 0.75
# A member takes over its group from the last run's leader only with this many times the leader's 30-day decks.
LEADER_MARGIN = 1.2
REPORT_THRESHOLD = 0.6
# The windows a merge is looked for in; the longest ranks a group's leader first.
WINDOW_DAYS = (7, 14, 30)
OVERRIDES = Path(__file__).with_name("archetype_overrides.json")

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
    """Archetypes merged under their leader, `members[0]`; `profile` is the leader's own list."""

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


def _leaders(order: Sequence[str], score: Callable[[str, str], Tuple[float, int]], threshold: float) -> Dict[str, Tuple[str, float, int]]:
    """Each archetype of `order` (biggest first) that joins a leader: `member -> (leader, score, days)`.

    An archetype joins the leader it scores highest against, when that is at least `threshold`, and otherwise leads its
    own group, so every member is close to its leader's own list and no chain of look-alikes forms. A tie goes to
    the bigger leader. `score(member, leader)` is the score and the window it came from.
    """
    leaders: List[str] = []
    joined: Dict[str, Tuple[str, float, int]] = {}
    for key in order:
        best: Optional[Tuple[str, float, int]] = None
        for leader in leaders:
            value, days = score(key, leader)
            if best is None or value > best[1]:
                best = (leader, value, days)
        if best is not None and best[1] >= threshold:
            joined[key] = best
        else:
            leaders.append(key)
    return joined


def _size(archetype: Archetype) -> tuple:
    return (archetype.decks, archetype.lists, archetype.archetype_id)


def merge(archetypes: Sequence[Archetype], threshold: float = THRESHOLD) -> List[Group]:
    """The archetypes of one window in groups, each led by its member with the most decks.

    Taken biggest first, an archetype joins the leader whose own list it scores highest against, when that is at least
    `threshold`; otherwise it leads a group. Every archetype is in one group, alone when nothing is close to it.
    Largest groups first.
    """
    by_id = {archetype.archetype_id: archetype for archetype in archetypes}
    order = [archetype.archetype_id for archetype in sorted(archetypes, key=_size, reverse=True)]
    joined = _leaders(order, lambda member, leader: (similarity(by_id[member].profile, by_id[leader].profile), 0), threshold)
    members: Dict[str, List[Archetype]] = {}
    for key in order:
        members.setdefault(joined[key][0] if key in joined else key, []).append(by_id[key])
    groups = [Group(leader, by_id[leader].name, group, by_id[leader].profile) for leader, group in members.items()]
    groups.sort(key=lambda group: (-group.decks, group.name))
    return groups


def assign(vectors: Dict[str, Profile], groups: Sequence[Group], threshold: float = THRESHOLD) -> Dict[str, Tuple[Group, float]]:
    """Each deck's closest group by its leader's list, and its score, for the decks that score at least `threshold` against one."""
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


@dataclass
class Overrides:
    """A format's hand-kept rules from `archetype_overrides.json`, which win over the scores.

    Two ids of one `keep_apart` set are never in one group, whether one would join the other or both one leader.
    An archetype of an `always_merge` set joins the group of the first of its set placed (the biggest), whatever it
    scores. `disabled` publishes the format unmerged.
    """

    keep_apart: List[Set[str]] = field(default_factory=list)
    always_merge: List[Set[str]] = field(default_factory=list)
    disabled: bool = False

    def apart(self, a: str, b: str) -> bool:
        return any(a in ids and b in ids for ids in self.keep_apart)


def load_overrides(format: str, path: Path = OVERRIDES) -> Overrides:
    """The overrides of one format: `{"disabled": [format, ...], "keep_apart": {format: [[id, ...], ...]}, "always_merge": {...}}`."""
    data = json.loads(path.read_text()) if path.exists() else {}
    return Overrides(
        [set(ids) for ids in data.get("keep_apart", {}).get(format, [])],
        [set(ids) for ids in data.get("always_merge", {}).get(format, [])],
        format in data.get("disabled", []),
    )


@dataclass
class Merging:
    """What `plan` decided for a snapshot: `leaders` maps each merged-away archetype id to `(leader id, score, days)`,
    the window `days` being the one it scored best in; `assigned` maps the deck id of a result with no archetype to
    `(leader id, score)`; `names` is every archetype's name by id. `kept` are the members that stayed in the last
    run's group only by `STICKY_THRESHOLD` (scoring below `THRESHOLD`), and `forced` those an `always_merge` override joined."""

    leaders: Dict[str, Tuple[str, float, int]]
    assigned: Dict[str, Tuple[str, float]]
    names: Dict[str, str]
    kept: Set[str] = field(default_factory=set)
    forced: Set[str] = field(default_factory=set)


def plan(
    document: dict,
    deck_cards: Dict[str, dict],
    lands: Set[str],
    threshold: float = THRESHOLD,
    days: Sequence[int] = WINDOW_DAYS,
    overrides: Optional[Overrides] = None,
    previous: Optional[Dict[str, str]] = None,
) -> Merging:
    """One set of groups for a snapshot, used in every window, so an id means the same thing on every window's list.

    Each window's average lists are built from its own decks. The archetypes are taken biggest first, ranked by their
    decks in the longest window, then the next, then the shortest. `previous` is the last run's groups (member id ->
    leader id): each keeps its leader, unless a member now has more than `LEADER_MARGIN` times the leader's decks in
    the longest window, and each of its members stays while it scores at least `STICKY_THRESHOLD` against the leader.
    Any other archetype joins the leader it scores highest against in any window where both have lists, at
    `threshold` or more, and otherwise leads its own group. `overrides` win over every score (see `Overrides`).
    A result with no archetype joins the leader whose own list over the longest window it scores highest against, at
    `threshold` or more.
    """
    rules = overrides or Overrides()
    ordered = sorted(days)
    windows = {length: window(document, deck_cards, lands, length) for length in ordered}
    found = {length: {archetype.archetype_id: archetype for archetype in windows[length].archetypes} for length in ordered}
    names = {key: archetype.name for length in ordered for key, archetype in found[length].items()}
    if rules.disabled:
        return Merging({}, {}, names)
    keys = set().union(*(set(archetypes) for archetypes in found.values()))
    longest = ordered[-1]

    def size(key: str) -> tuple:
        counts = tuple(found[length][key].decks if key in found[length] else 0 for length in reversed(ordered))
        return counts + (found[longest][key].lists if key in found[longest] else 0, key)

    def score(member: str, leader: str) -> Tuple[float, int]:
        scored = [
            (similarity(found[length][member].profile, found[length][leader].profile), length)
            for length in ordered
            if member in found[length] and leader in found[length]
        ]
        return max(scored, key=lambda item: item[0]) if scored else (0.0, 0)

    last: Dict[str, List[str]] = {}
    for member, leader in (previous or {}).items():
        last.setdefault(leader, []).append(member)
    groups: Dict[str, List[str]] = {}
    stay: Dict[str, str] = {}
    for leader, members in last.items():
        present = [member for member in members if member in keys]
        if leader not in keys or not present:
            continue
        biggest = max(present, key=size)
        kept_leader = biggest if size(biggest)[0] > LEADER_MARGIN * size(leader)[0] else leader
        groups[kept_leader] = [kept_leader]
        for key in [leader] + present:
            if key != kept_leader:
                stay[key] = kept_leader

    def allowed(key: str, leader: str) -> bool:
        return not any(rules.apart(key, other) for other in groups[leader])

    joined: Dict[str, Tuple[str, float, int]] = {}
    kept: Set[str] = set()
    forced: Set[str] = set()
    for key in sorted(keys, key=size, reverse=True):
        if key in groups:
            continue
        placed = [
            joined[other][0] if other in joined else other
            for ids in rules.always_merge
            if key in ids
            for other in sorted(ids - {key}, key=lambda other: size(other) if other in keys else (), reverse=True)
            if other in joined or other in groups
        ]
        leader: Optional[str] = next((leader for leader in placed if allowed(key, leader)), None)
        if leader is not None:
            forced.add(key)
        elif key in stay and stay[key] in groups and allowed(key, stay[key]) and score(key, stay[key])[0] >= STICKY_THRESHOLD:
            leader = stay[key]
            if score(key, leader)[0] < threshold:
                kept.add(key)
        else:
            best: Optional[Tuple[str, float]] = None
            for candidate in groups:
                if allowed(key, candidate):
                    value = score(key, candidate)[0]
                    if best is None or value > best[1]:
                        best = (candidate, value)
            if best is not None and best[1] >= threshold:
                leader = best[0]
        if leader is None:
            groups[key] = [key]
            continue
        joined[key] = (leader, *score(key, leader))
        groups[leader].append(key)

    profiles = [(key, found[longest][key].profile) for key in sorted(groups, key=size, reverse=True) if key in found[longest]]
    assigned: Dict[str, Tuple[str, float]] = {}
    for deck_id, (_, vector) in windows[longest].unassigned.items():
        if vector is None:
            continue
        best = None
        for key, leader_profile in profiles:
            value = similarity(vector, leader_profile)
            if best is None or value > best[1]:
                best = (key, value)
        if best is not None and best[1] >= threshold:
            assigned[deck_id] = best
    return Merging(joined, assigned, names, kept, forced)


def colors_by_deck(document: dict, deck_cards: Dict[str, dict], catalog: Dict[str, dict]) -> Dict[str, List[str]]:
    """The colours of every deck of the snapshot that has known ones: the pips its event page showed, else its stored list's."""
    known: Dict[str, List[str]] = {}
    for event in document.get("events", []):
        for result in event.get("results", []):
            if result.get("colors"):
                known.setdefault(result["deck_id"], list(result["colors"]))
    for deck_id, deck in deck_cards.items():
        if deck_id not in known:
            colors = deck_colors(deck.get("m", []) + deck.get("s", []), catalog)
            if colors is not None:
                known[deck_id] = colors
    return known


def majority_colors(deck_ids: Iterable[str], colors: Dict[str, List[str]]) -> Optional[List[str]]:
    """The colours at least half of the decks with known colours play, in WUBRG order; None when no deck's are known."""
    known = [colors[deck_id] for deck_id in deck_ids if deck_id in colors]
    if not known:
        return None
    return [color for color in COLORS if 2 * sum(1 for deck in known if color in deck) >= len(known)]


def apply(document: dict, merging: Merging, colors: Optional[Dict[str, List[str]]] = None) -> dict:
    """The snapshot as published: one archetype per group, under its leader's id and name.

    In each window's metagame a group is one tile: its members' shares and deck counts added up (the deck count null
    when a member's is), and the leader's key cards and featured deck (from the leader's tile in that window, else its
    tile in the longest window that has one, else the biggest member's). A group that merged anything has the colours
    at least half of its decks with known colours play (`colors`, deck id -> colours; see `majority_colors`), over
    every result of the group, and the leader's tile colours when none is known. The list is then in order of share.
    The leader's results are every member's, and the results with no archetype that joined it; an event result of a
    member, or one that joined, takes the leader's id and name. `merges` maps each merged-away id to its leader.
    The document is not changed; the one returned shares what it leaves alone with it.
    """
    leader_of = {member: leader for member, (leader, _, _) in merging.leaders.items()}

    def name(key: str, fallback: str) -> str:
        return merging.names.get(key, fallback)

    tiles = archetype_tiles(document.get("meta", {}))
    group_decks: Dict[str, Set[str]] = {}
    for key, history in document.get("archetypes", {}).items():
        group_decks.setdefault(leader_of.get(key, key), set()).update(result["deck_id"] for result in history.get("results", []))
    for event in document.get("events", []):
        for result in event.get("results", []):
            key = result.get("archetype_id")
            if key:
                group_decks.setdefault(leader_of.get(key, key), set()).add(result["deck_id"])
            elif result["deck_id"] in merging.assigned:
                group_decks.setdefault(merging.assigned[result["deck_id"]][0], set()).add(result["deck_id"])
    merged_groups = set(leader_of.values()) | {leader for leader, _ in merging.assigned.values()}
    group_colors = {key: majority_colors(group_decks.get(key, ()), colors or {}) for key in merged_groups}
    meta = {}
    for timeframe, listing in document.get("meta", {}).items():
        grouped: Dict[str, List[dict]] = {}
        for tile in listing.get("archetypes", []):
            grouped.setdefault(leader_of.get(tile["id"], tile["id"]), []).append(tile)
        merged = []
        for key, members in grouped.items():
            shown = group_colors.get(key)
            if len(members) == 1 and members[0]["id"] == key and shown is None:
                merged.append(members[0])
                continue
            base = next((tile for tile in members if tile["id"] == key), None) or tiles.get(key) or members[0]
            counts = [tile.get("deck_count") for tile in members]
            merged.append(
                {
                    **base,
                    "id": key,
                    "name": name(key, base["name"]),
                    "percentage": round(sum(tile["percentage"] for tile in members), 1),
                    "deck_count": None if any(count is None for count in counts) else sum(counts),
                    "colors": shown if shown is not None else base.get("colors", []),
                }
            )
        # sorted() is stable, so equal shares keep MTGGoldfish's order.
        merged.sort(key=lambda tile: tile["percentage"], reverse=True)
        meta[timeframe] = {**listing, "archetypes": merged}

    events = []
    joined: Dict[str, List[dict]] = {}
    for event in document.get("events", []):
        results = []
        for result in event.get("results", []):
            key = result.get("archetype_id")
            if key in leader_of:
                result = {**result, "archetype_id": leader_of[key], "archetype": name(leader_of[key], result.get("archetype") or "")}
            elif not key and result["deck_id"] in merging.assigned:
                leader = merging.assigned[result["deck_id"]][0]
                result = {**result, "archetype_id": leader, "archetype": name(leader, result.get("archetype") or "")}
                joined.setdefault(leader, []).append(
                    {
                        "deck_id": result["deck_id"],
                        "date": event["date"],
                        "player": result["player"],
                        "event_id": event["event_id"],
                        "event_name": event["event_name"],
                        "finish": result["finish"],
                    }
                )
            results.append(result)
        events.append({**event, "results": results})

    histories: Dict[str, List[dict]] = {}
    for key, history in document.get("archetypes", {}).items():
        histories.setdefault(leader_of.get(key, key), []).append(history)
    for leader in joined:
        histories.setdefault(leader, [])
    archetypes = {}
    for key, members in histories.items():
        if len(members) == 1 and members[0]["archetype_id"] == key and key not in joined:
            archetypes[key] = members[0]
            continue
        base = next((history for history in members if history["archetype_id"] == key), None)
        if base is None:
            base = {"archetype_id": key, "name": name(key, key), "deck_id": None, "featured_player": None}
            if members:
                base["last_updated"] = members[0].get("last_updated")
        seen: Set[str] = set()
        results = []
        for result in [result for history in sorted(members, key=lambda h: h is not base) for result in history.get("results", [])] + joined.get(key, []):
            if result["deck_id"] not in seen:
                seen.add(result["deck_id"])
                results.append(result)
        # Stable, so results of one day keep the order the leader's, then its members', had them in.
        results.sort(key=lambda result: result["date"], reverse=True)
        archetypes[key] = {**base, "archetype_id": key, "name": name(key, base["name"]), "results": results}

    merges = {member: leader_of[member] for member in sorted(leader_of)}
    return {**document, "meta": meta, "events": events, "archetypes": dict(sorted(archetypes.items())), "merges": merges}


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
    groups = merge(found.archetypes, threshold)
    merged = [group for group in groups if len(group.members) > 1]
    lines.append(f"-- Merges at {threshold:.2f}: {len(merged)} groups from {sum(len(g.members) for g in merged)} archetypes")
    for group in merged:
        leader = group.members[0]
        lines.append(f"  {group.name} [{group.archetype_id}] {group.decks} decks, {group.lists} lists")
        for member in group.members[1:]:
            lines.append(f"      <- {_label(member)}  {similarity(member.profile, leader.profile):.3f} to {leader.name}")
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


def report_plan(
    format: str,
    document: dict,
    deck_cards: Dict[str, dict],
    lands: Set[str],
    threshold: float,
    overrides: Optional[Overrides] = None,
    previous: Optional[Dict[str, str]] = None,
) -> List[str]:
    """The dry run's lines for the groups published, which hold in every window."""
    rules = overrides or Overrides()
    merging = plan(document, deck_cards, lands, threshold, overrides=rules, previous=previous)
    lines = [f"== {format} published groups at {threshold:.2f} (members of the last run's {len(previous or {})} stay at {STICKY_THRESHOLD:.2f})"]
    lines.append("-- Overrides" + (": merging disabled for this format" if rules.disabled else ""))
    for label, sets in (("keep apart", rules.keep_apart), ("always merge", rules.always_merge)):
        for ids in sets:
            lines.append(f"  {label}: " + ", ".join(f"{merging.names.get(key, '?')} [{key}]" for key in sorted(ids)))
    lines.append(f"-- {len(merging.leaders)} archetypes merged away")
    by_leader: Dict[str, List[Tuple[str, float, int]]] = {}
    for member, (leader, score, days) in merging.leaders.items():
        by_leader.setdefault(leader, []).append((member, score, days))
    for leader, members in sorted(by_leader.items(), key=lambda item: (-len(item[1]), merging.names[item[0]])):
        lines.append(f"  {merging.names[leader]} [{leader}]")
        for member, score, days in sorted(members, key=lambda item: -item[1]):
            how = " (always merge)" if member in merging.forced else " (kept from the last run)" if member in merging.kept else ""
            lines.append(f"      <- {merging.names[member]} [{member}]  {score:.3f} in {days}d{how}")
    counts: Dict[str, int] = {}
    for leader, _ in merging.assigned.values():
        counts[leader] = counts.get(leader, 0) + 1
    lines.append(f"-- {len(merging.assigned)} results with no archetype join a leader")
    for leader, count in sorted(counts.items(), key=lambda item: (-item[1], merging.names[item[0]])):
        lines.append(f"  {count:3d} -> {merging.names[leader]}")
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
        raw = args.directory / "state" / "snapshots" / f"{format}.json"
        document = json.loads((raw if raw.exists() else args.directory / "snapshots" / f"{format}.json").read_text())
        cards_path = args.directory / "state" / "deck-cards" / f"{format}.json"
        deck_cards = json.loads(cards_path.read_text()) if cards_path.exists() else {}
        for days in (int(item) for item in args.days.split(",") if item.strip()):
            print("\n".join(report(format, days, document, deck_cards, lands, args.threshold, args.report)), flush=True)
        groups_path = args.directory / "state" / "archetype-groups" / f"{format}.json"
        previous = json.loads(groups_path.read_text()) if groups_path.exists() else {}
        print("\n".join(report_plan(format, document, deck_cards, lands, args.threshold, load_overrides(format), previous)), flush=True)
    return 0
