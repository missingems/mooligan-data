"""Archetype primers for api.mooligan.com, written by Claude from the published metagame and checked before they go up.

A primer is the playgraph Markdown an archetype page shows on its Primers tab (its format is the API's `format_guide`).
Each of the six main formats' archetypes is set against the primers the API lists: first the first `--count` (16) of
`explore.json`'s 30-day standings, then every other archetype with MIN_RESULTS (10) results or more in
`snapshots/{format}.json`, at most BACKFILL (25) of those a run: each format's with the most results first, the formats
taking turns, so one with many results (Modern) does not keep the others waiting. A primer is written for each one
that is due:

- missing: the archetype has no primer. The app finds a primer by the archetype's id, so a primer of an archetype since
  merged into this one (the snapshot's `merges`) does not count: a new one is written under this archetype's id,
  starting from that primer's text, which is left as it is.
- changed: the archetype's consensus main deck moved by CHANGED_SLOTS (6) cards or more since the primer was written,
  or its top card (the first of `hand`) is one the primer's deck did not play. `state/primers.json` keeps the consensus
  each primer written here came from. A primer written by hand (or edited since) has none, so its own `Main cards` grid
  stands in; the grid lists only the main cards, so it counts only copies that left the deck (a card the grid has at 4
  and the deck now plays at 1 is 3 cards), and its top card counts as new when the primer never names it.
- old: the primer was last updated STALE_DAYS (90) or more days ago, and its main deck has moved by a card or more since
  it was written (counted as for "changed"). A primer whose deck is the same is left alone, however old.

Other archetypes, and their primers, are left alone. Commander primers are not written here: a commander's
primer is shaped differently (its abilities, its builds by bracket) and needs other facts than a decklist.

A missing primer is written by MODEL (claude-opus-5-5) at effort EFFORT (high). A refresh of one that exists (changed
or old) is a revision by REVISION_MODEL (claude-sonnet-5-5) at effort REVISION_EFFORT (medium): it is told to keep what
still holds in the primer it has now and rewrite what the changes make wrong, and replies with the whole primer.

Claude is sent the archetype's shares, consensus list and other cards its lists play, its recent results, the format's
other top archetypes, the Oracle text of every card, and the primer it has now. The primers of a run go as one Message
Batch, at half the price of single calls: `Writer` submits it, polls until it ends (at most `--minutes`, WAIT_MINUTES
(60) when 0), and each primer is checked as its answer comes back: by the API's `validate_primer` (the parser that
rejects a primer on publish); that every [[card]] is one Scryfall knows, or a token one of the facts' cards makes; that
every matchup is an archetype of the format; that every `in:` card is one of the deck's sideboard cards and every `out:`
card one of its main deck cards; and that each matchup takes out as many cards as it brings in. A draft with problems is
sent back once with them, as a single streamed call at the standard price, and one that still has them is not published.
Every draft is written to DIR/primers/{id}.md.

A batch still running when the wait is over is kept in `state/primer-batch.json` (the primer and model of each request).
The next run collects it first, once it has ended: a primer of it that is still due is checked and published as if it
had come back at once, and is not sent again; the others are dropped. A batch still running keeps its primers out of
that run's batch. The file is written as {"batches": []} when none is left, since ops/primers.sh never deletes in R2.

`--publish` puts each passing draft with PRIMERS_ADMIN_TOKEN as a new version of the primer's id. `--budget` stops
asking Claude before the run would pass that many dollars: the primers picked for the batch are the first, in order,
whose estimates (ESTIMATES, at batch prices) fit what is left, and a draft is sent back only if its call fits too. The
primers left wait for the next run, the first archetypes' before the rest and the missing ones first. `--plan` lists
what is due and why, and `--check` validates the published primers; neither needs a key.

It reads ANTHROPIC_API_KEY (and ANTHROPIC_WORKSPACE_ID for a key not scoped to one workspace) and PRIMERS_ADMIN_TOKEN
from the environment, and never logs them.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .explore import WINDOW_DAYS, _places

log = logging.getLogger(__name__)

FORMATS = ("standard", "pioneer", "modern", "legacy", "pauper", "vintage")
# Which archetypes get a primer: the first COUNT of each format's 30-day standings, then every other one with
# MIN_RESULTS results or more in its snapshot, at most BACKFILL of those a run, the formats taking turns.
COUNT = 16
MIN_RESULTS = 10
BACKFILL = 25
# When a primer is written again: its deck moved by CHANGED_SLOTS cards, or it is STALE_DAYS old and its deck moved at all.
STALE_DAYS = 90
CHANGED_SLOTS = 6
STATE_PATH = "state/primers.json"
BATCH_PATH = "state/primer-batch.json"
DRAFTS = "primers"
API_URL = "https://api.mooligan.com"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
EXAMPLE = Path(__file__).with_name("primer_example.md")

# A missing primer is written by MODEL; a refresh of one that exists is a revision by REVISION_MODEL.
MODEL = "claude-opus-5-5"
EFFORT = "high"
REVISION_MODEL = "claude-sonnet-5-5"
REVISION_EFFORT = "medium"
EFFORTS = {MODEL: EFFORT, REVISION_MODEL: REVISION_EFFORT}
MAX_TOKENS = 64000
# The batch is polled this often, for at most the run's minutes (WAIT_MINUTES when it has none).
WAIT_MINUTES = 60
POLL_SECONDS = 30
CACHE = {"type": "ephemeral", "ttl": "1h"}
# A refusal is run again on the model Anthropic recommends for its category, in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# A draft with problems goes back this many times.
REPAIRS = 1
# Dollars per million tokens: input, output, cache write (the 1-hour cache, twice the input), cache read. Thinking is
# billed as output. A fallback is billed at its own model's prices; an unknown model at the dearest here. A batch is
# billed at half.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 8.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 4.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 10.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 10.00, 0.50),
}
# What one primer is taken to cost at batch prices, which picks the primers a budget covers: about 13k tokens of facts
# and up to 25k of thinking and primer. A draft sent back is a call at the standard price, twice that.
ESTIMATES = {MODEL: 0.30, REVISION_MODEL: 0.15}
# Cards some lists play beyond the consensus, from this share of the lists.
FLEX_SHARE = 25.0
FLEX_CARDS = 15
OPPONENTS = 8
RESULTS = 6
AUTHOR = "greg"
AUTHOR_NAME = "Greg"
TYPES = ("aggro", "tempo", "midrange", "control", "combo", "ramp", "prison")

SYSTEM = """You write archetype primers for Mooligan, a Magic: The Gathering app. A primer teaches a player who has just picked up a deck how it plays, how it wins, what to watch out for and how to sideboard. Players rely on every rules statement in it, so accuracy comes before everything else.

You are given one archetype's facts: its share of the format, its consensus decklist and the other cards its lists play, its recent results, the format's other top archetypes, the Oracle text of the cards, and, when it has one, the primer it has now. Write the whole primer in playgraph Markdown, in the format described below, and reply with the Markdown only: start with the front matter's opening `---` line, with nothing before it and nothing after the primer.

A primer has, in this order:
- Front matter with exactly the archetype, format, title, author, written and updated values you are given, and `type:` as one to three of: """ + ", ".join(TYPES) + """.
- `## The deck`: what the deck does and how it wins, in a paragraph or two, and how much of the format plays it, from the shares given.
- `## Main cards`: one `:::cards` grid of the eight to twelve cards that define the deck, each with its copies in the consensus list and a short line on its job.
- One to three sections on how the deck plays and wins (its engine, its combo, its key turns), each with at least one `playgraph` diagram. Title them for this deck.
- `## Gotchas and tips`: four to seven `:::gotcha` and `:::tip` blocks on the rules details and play patterns that trip players up.
- `## Matchups and sideboarding`: one sentence saying Mooligan has no head-to-head records yet, so these say what to bring in and why, based on the number of lists given over the days given. Then a `:::matchup` block against each of four to six of the top archetypes given (the mirror only if the deck itself is among them), with no `verdict` and no `record`, each with an `about:` line on what that deck does, `key:` naming one to three of its cards from the facts, `in:` and `out:` lines, and a sentence or two on why.

Rules for the content:
- Take every number from the facts: shares, list counts, copies. Never invent a statistic, a result or a decklist.
- Name a card only when it is in the facts or you are certain it exists under exactly that name, and write it exactly as the facts write it. A token is written as `token [[Name]]` in a diagram, named as the card that makes it names it.
- Every rules statement must follow from the Oracle text given and the Comprehensive Rules. Never describe an interaction, combo or loop the Oracle text does not support. When you are not sure something works, leave it out.
- Mark a diagram `verified` only when every step in it follows from the Oracle text given; otherwise mark it `unverified`.
- `in:` cards come only from the deck's sideboard (its consensus sideboard, or the other sideboard cards its lists play), at most as many copies as its lists play. `out:` cards come only from its main deck. Each matchup takes out as many cards as it brings in.
- A matchup's `archetype=` is exactly the id given for that archetype.
- When the archetype has a primer already, keep what is still right in it (its explanations, its structure, its voice) and change what the current lists, results and format no longer support.

Write plain, confident second person for a player who knows the rules of Magic but not this deck. Short sentences. No hype and no filler, no headings beyond the sections above, and no mention of where the data comes from beyond the list counts."""


class PrimerError(Exception):
    pass


# --- the API ------------------------------------------------------------------------------------------------------


def http(method: str, url: str, body: Optional[dict] = None, headers: Optional[dict] = None) -> Tuple[int, object]:
    """The status and the JSON body (None when it has none) of one request."""
    data = json.dumps(body).encode() if body is not None else None
    sent = {"User-Agent": USER_AGENT, "Accept": "application/json, text/event-stream", **(headers or {})}
    if data is not None:
        sent["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=sent)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"null")
        except ValueError:
            return error.code, None


@dataclass
class Published:
    """A primer as `GET /v1/primers` lists it."""

    id: str
    archetype: str
    format: str
    title: str
    written: str
    updated: str
    version: int

    @staticmethod
    def of(row: dict) -> "Published":
        return Published(
            str(row["id"]), str(row.get("archetype") or ""), str(row.get("format") or ""), str(row.get("title") or ""),
            str(row.get("written") or ""), str(row.get("updated") or ""), int(row.get("version") or 0),
        )


class Api:
    """api.mooligan.com: the primers it lists, their Markdown, its `validate_primer` and `format_guide` tools (over MCP,
    which needs no token), and the admin PUT that publishes a primer."""

    def __init__(self, base: str = API_URL, token: Optional[str] = None, request: Callable = http) -> None:
        self.base = base.rstrip("/")
        self._token = token
        self._request = request
        self._sources: Dict[str, Optional[dict]] = {}

    @property
    def can_publish(self) -> bool:
        return bool(self._token)

    def primers(self) -> List[Published]:
        status, body = self._request("GET", f"{self.base}/v1/primers")
        if status != 200:
            raise PrimerError(f"GET /v1/primers: HTTP {status}")
        rows = body if isinstance(body, list) else (body or {}).get("primers") or []
        return [Published.of(row) for row in rows]

    def source(self, primer_id: str) -> Optional[dict]:
        """`{ markdown, author, version, ... }` of a primer's current version, None when there is none."""
        if primer_id not in self._sources:
            status, body = self._request("GET", f"{self.base}/v1/primers/{urllib.parse.quote(primer_id)}/source")
            if status not in (200, 404):
                raise PrimerError(f"GET /v1/primers/{primer_id}/source: HTTP {status}")
            self._sources[primer_id] = body if status == 200 else None
        return self._sources[primer_id]

    def tool(self, name: str, arguments: dict) -> str:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        status, reply = self._request("POST", f"{self.base}/mcp", body, {"MCP-Protocol-Version": "2025-06-18"})
        result = (reply or {}).get("result") if isinstance(reply, dict) else None
        if status != 200 or not result:
            raise PrimerError(f"MCP {name}: HTTP {status} {(reply or {}).get('error') if isinstance(reply, dict) else ''}".strip())
        text = "".join(part.get("text") or "" for part in result.get("content") or [])
        if result.get("isError"):
            raise PrimerError(f"MCP {name}: {text}")
        return text

    def validate(self, markdown: str) -> dict:
        return json.loads(self.tool("validate_primer", {"markdown": markdown}))

    def format_guide(self) -> str:
        return self.tool("format_guide", {})

    def publish(self, primer_id: str, markdown: str, note: str, author: str = AUTHOR) -> int:
        """Adds a version of the primer and returns its number. The API checks the Markdown again and answers 422 with
        its diagnostics when it has errors."""
        if not self._token:
            raise PrimerError("publishing needs PRIMERS_ADMIN_TOKEN")
        status, body = self._request(
            "PUT", f"{self.base}/v1/primers/{urllib.parse.quote(primer_id)}", {"markdown": markdown, "author": author, "note": note},
            {"Authorization": f"Bearer {self._token}"},
        )
        if status != 201:
            raise PrimerError(f"PUT /v1/primers/{primer_id}: HTTP {status} {json.dumps(body)[:500]}")
        return int(body["version"])


# --- what is due ----------------------------------------------------------------------------------------------------


def consensus(archetype: dict, board: str = "main") -> Dict[str, int]:
    return {card["name"]: int(card["quantity"]) for card in ((archetype.get("consensus") or {}).get(board) or [])}


def top_card(archetype: dict) -> Optional[str]:
    hand = archetype.get("hand") or []
    return hand[0]["name"] if hand else None


CARD_LINE = re.compile(r"^\s*(\d+)\s+\[\[([^\]|]+)")
LINK = re.compile(r"\[\[([^\]|]+)")


def grid(markdown: str) -> Dict[str, int]:
    """The copies of each card in the primer's `Main cards` grid (else its first grid)."""
    lines = markdown.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip().lower() == "## main cards"), 0)
    cards: Dict[str, int] = {}
    inside = False
    for line in lines[start:]:
        if line.strip().startswith(":::cards"):
            inside = True
        elif inside and line.strip() == ":::":
            break
        elif inside:
            match = CARD_LINE.match(line)
            if match:
                cards[match.group(2).strip()] = int(match.group(1))
    return cards


def linked(markdown: str) -> Set[str]:
    return {name.strip() for name in LINK.findall(markdown)}


def moved(before: Dict[str, int], now: Dict[str, int], partial: bool = False) -> int:
    """The cards of the main deck that changed: copies added or taken out, whichever is more. With `partial` (a grid of
    some of the deck's cards) only the copies that left can be seen."""
    removed = sum(max(0, copies - now.get(name, 0)) for name, copies in before.items())
    if partial:
        return removed
    return max(removed, sum(max(0, copies - before.get(name, 0)) for name, copies in now.items()))


def age(primer: Published, today: date) -> Optional[int]:
    try:
        return (today - date.fromisoformat(primer.updated[:10])).days
    except ValueError:
        return None


@dataclass
class Item:
    """One archetype whose primer is due."""

    format: dict
    row: dict
    archetype: dict
    primer: Optional[Published]
    primer_id: str
    reasons: List[str]
    rank: int
    # The primer of an archetype since merged into this one, which the new primer starts from.
    merged_from: Optional[Published] = None
    # 0 for the first archetypes of the standings, 1 for the ones past them.
    tier: int = 0

    @property
    def id(self) -> str:
        return self.row["id"]

    @property
    def model(self) -> str:
        """A primer that exists is revised by the cheaper model; a missing one (or one starting from a merged archetype's
        primer) is written by the better."""
        return REVISION_MODEL if self.primer else MODEL

    @property
    def effort(self) -> str:
        return EFFORTS[self.model]

    @property
    def estimate(self) -> float:
        return ESTIMATES[self.model]

    @property
    def previous(self) -> Optional[Published]:
        """The primer whose text the new one starts from."""
        return self.primer or self.merged_from


def standing(snapshot: dict, archetype_id: str, today: date) -> dict:
    """An archetype's row as explore.json's standings would have it, for one past them."""
    meta = snapshot.get("meta") or {}
    month = next((each for each in (meta.get("30d") or {}).get("archetypes") or [] if each["id"] == archetype_id), {})
    week = next((each for each in (meta.get("7d") or {}).get("archetypes") or [] if each["id"] == archetype_id), {})
    results = ((snapshot.get("archetypes") or {}).get(archetype_id) or {}).get("results") or []
    now = datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc)
    places = _places(results, now - timedelta(days=WINDOW_DAYS), now)
    return {
        "id": archetype_id,
        "name": month.get("name") or ((snapshot.get("archetypes") or {}).get(archetype_id) or {}).get("name") or archetype_id,
        "share_30d": month.get("percentage"),
        "share_7d": week.get("percentage"),
        "deck_count_30d": month.get("deck_count"),
        "top8_30d": sum(1 for place in places if place <= 8),
        "wins_30d": sum(1 for place in places if place == 1),
        "colors": month.get("colors") or [],
        "key_cards": month.get("key_cards") or [],
        "results": len(results),
    }


def covered(block: dict, snapshot: Optional[dict], count: int, min_results: int, today: date) -> List[Tuple[dict, int]]:
    """The archetypes of a format that get a primer, each with its tier: the first `count` of the 30-day standings (0),
    then every other archetype with `min_results` results or more in the snapshot, most results first (1)."""
    archetypes = (snapshot or {}).get("archetypes") or {}
    rows = [({**row, "results": len(archetypes.get(row["id"], {}).get("results") or [])}, 0) for row in (block.get("standings") or [])[:count]]
    first = {row["id"] for row, _ in rows}
    counts = sorted(((len(body.get("results") or []), archetype_id) for archetype_id, body in archetypes.items()), key=lambda each: -each[0])
    rows += [(standing(snapshot, archetype_id, today), 1) for results, archetype_id in counts if results >= min_results and archetype_id not in first]
    return rows


def match_primers(rows: Sequence[dict], primers: Sequence[Published], merges: Dict[str, str]) -> Dict[str, Tuple[Published, bool]]:
    """Each archetype's primer, and whether it is instead the primer of an archetype since merged into it (`merges`
    maps each id merged away to the one it went into). An archetype with several primers keeps the one named after it,
    else the one updated last."""
    ids = {row["id"] for row in rows}
    matched: Dict[str, Tuple[Published, bool]] = {}
    newest = sorted(primers, key=lambda each: each.updated, reverse=True)
    for primer in sorted(newest, key=lambda each: each.id != each.archetype):
        if primer.archetype in ids and primer.archetype not in matched:
            matched[primer.archetype] = (primer, False)
    for primer in newest:
        leader = merges.get(primer.archetype) or merges.get(primer.id)
        if primer.archetype not in ids and leader in ids and leader not in matched:
            matched[leader] = (primer, True)
    return matched


def reasons_for(archetype: dict, primer: Published, entry: Optional[dict], markdown: Optional[str], today: date) -> Tuple[List[str], int]:
    """Why the archetype's primer is due, and its rank (changed 1, old 2); [] when it is not. An old primer is due only if
    its deck has moved at all."""
    found: List[Tuple[int, str]] = []
    now = consensus(archetype)
    top = top_card(archetype)
    slots = 0
    if entry and entry.get("version") == primer.version and entry.get("consensus"):
        before = entry["consensus"]
        slots = moved(before, now)
        if slots >= CHANGED_SLOTS:
            found.append((1, f"{slots} main deck cards changed since it was written"))
        if top and top not in before:
            found.append((1, f"its top card {top} is new to the deck"))
    elif markdown:
        slots = moved(grid(markdown), now, partial=True)
        if slots >= CHANGED_SLOTS:
            found.append((1, f"{slots} of its main cards' copies left the deck"))
        if top and top not in linked(markdown):
            found.append((1, f"its top card {top} is not in the primer"))
    days = age(primer, today)
    if days is not None and days >= STALE_DAYS and slots:
        found.append((2, f"updated {days} days ago"))
    return [reason for _, reason in found], min((rank for rank, _ in found), default=3)


def plan(
    explore: dict, formats: Sequence[str], count: int, primers: Sequence[Published], read: Callable[[str], Optional[dict]],
    state: Dict[str, dict], api: Api, today: date, only: Sequence[str] = (), min_results: int = MIN_RESULTS,
    backfill: int = BACKFILL,
) -> Tuple[List[Item], List[str]]:
    """The archetypes whose primer is due: the first of the standings by share, then the ones past them (at most
    `backfill`), each format's by results and the formats taking turns; missing first, then changed, then old. And a
    note for each one skipped or left."""
    items: List[Tuple[Tuple[int, int, int, float], Item]] = []
    notes: List[str] = []
    blocks = {block["format"]: block for block in explore.get("formats") or []}
    for name in formats:
        block = blocks.get(name)
        if not block:
            notes.append(f"{name}: not in explore.json")
            continue
        snapshot = read(f"snapshots/{name}.json")
        if not snapshot:
            notes.append(f"{name}: snapshots/{name}.json could not be read, so only its first {count} archetypes")
        rows = covered(block, snapshot, count, 0 if only else min_results, today)
        if only:
            rows = [(row, tier) for row, tier in rows if row["id"] in only]
        mine = [primer for primer in primers if primer.format.lower() == block["name"].lower()]
        matched = match_primers([row for row, _ in rows], mine, (snapshot or {}).get("merges") or {})
        # How many of this format's archetypes past the first are due before this one, so the formats take turns.
        turn = 0
        for row, tier in rows:
            archetype = read(f"archetypes/{row['id']}.json")
            if not archetype or not consensus(archetype):
                notes.append(f"{row['id']}: no stored lists, so no primer")
                continue
            primer, merged = matched.get(row["id"], (None, False))
            merged_from = primer if merged else None
            if merged:
                primer = None
                reasons, rank = [f"no primer, but {merged_from.id} was written for {merged_from.archetype}, since merged into it"], 0
            elif primer is None:
                reasons, rank = ["no primer"], 0
            else:
                entry = state.get(primer.id)
                markdown = None
                if not (entry and entry.get("version") == primer.version):
                    markdown = (api.source(primer.id) or {}).get("markdown")
                reasons, rank = reasons_for(archetype, primer, entry, markdown, today)
            if only and not reasons:
                reasons, rank = ["asked for"], 1
            if reasons:
                item = Item(block, row, archetype, primer, primer.id if primer else row["id"], reasons, rank, merged_from, tier)
                weight = (row.get("results") if tier else row.get("share_30d")) or 0.0
                items.append(((tier, rank, turn if tier else 0, -weight), item))
                turn += tier
    items.sort(key=lambda each: each[0])
    due: List[Item] = []
    waiting = 0
    for _, item in items:
        if item.tier and not only and sum(1 for each in due if each.tier) >= backfill:
            waiting += 1
            continue
        due.append(item)
    if waiting:
        notes.append(f"{waiting} past the first {count} wait for the next runs, at most {backfill} a run")
    return due, notes


# --- the facts Claude is given ---------------------------------------------------------------------------------------


Lookup = Callable[[str], Optional[dict]]


def oracle_line(name: str, lookup: Lookup) -> str:
    card = lookup(name) or {}
    text = " / ".join(line.strip() for line in (card.get("oracle_text") or "").splitlines() if line.strip())
    parts = [part for part in (card.get("mana_cost"), card.get("type_line")) if part]
    return f"- {name}" + (f" ({'; '.join(parts)})" if parts else "") + (f": {text}" if text else ": (not in Scryfall's catalog)" if not card else "")


def flex(archetype: dict, board: str) -> List[dict]:
    """The cards some of the lists play on a board that the consensus does not."""
    listed = consensus(archetype, board)
    cards = ((archetype.get("cards") or {}).get(board)) or []
    return [card for card in cards if card["name"] not in listed and (card.get("share") or 0) >= FLEX_SHARE][:FLEX_CARDS]


def percent(value) -> str:
    return "not played" if value is None else f"{value}%"


def opponents(item: Item, read: Callable[[str], Optional[dict]]) -> List[Tuple[dict, List[str]]]:
    """The format's top archetypes but this one, each with its key cards."""
    found = []
    for row in (item.format.get("standings") or [])[: OPPONENTS + 1]:
        if row["id"] == item.id or len(found) >= OPPONENTS:
            continue
        document = read(f"archetypes/{row['id']}.json") or {}
        cards = [card["name"] for card in document.get("hand") or row.get("key_cards") or []][:5]
        found.append((row, cards))
    return found


def front_matter(item: Item, today: date) -> Dict[str, str]:
    primer = item.primer
    keep = primer is not None and primer.archetype == item.id
    return {
        "archetype": item.id,
        "format": item.format["name"],
        "title": primer.title if keep and primer.title else item.archetype.get("name") or item.row["name"],
        "author": AUTHOR_NAME,
        "written": (primer.written[:10] if primer and primer.written else today.isoformat()),
        "updated": today.isoformat(),
    }


def facts(item: Item, read: Callable[[str], Optional[dict]], lookup: Lookup, previous: Optional[str], today: date) -> Tuple[str, List[str]]:
    """The message Claude is sent for one archetype, and the cards it names."""
    archetype, row = item.archetype, item.row
    cards_block = archetype.get("cards") or {}
    days = 7 if cards_block.get("window") == "7d" else 30
    shares = archetype.get("shares") or {}
    if item.primer and previous:
        lines = [
            "Revise the primer this archetype has now, given at the end. Keep what still holds, and rewrite what the changes "
            "make wrong: the Main cards grid, the sideboard and matchups, and anything said about cards the deck no longer "
            "plays or now plays. Reply with the whole revised primer.",
            f"Why it is revised: {'; '.join(item.reasons)}.",
            "",
            "## Front matter",
        ]
    else:
        lines = ["Write the primer for this archetype.", "", "## Front matter"]
    lines += [f"{key}: {value}" for key, value in front_matter(item, today).items()]
    lines += [
        "",
        f"## {row['name']} in {item.format['name']}",
        f"Archetype id: {item.id}",
        f"Colours: {''.join(archetype.get('colors') or row.get('colors') or []) or 'colourless'}",
        f"Share of the format's decks: {percent(shares.get('30d'))} over 30 days, {percent(shares.get('14d'))} over 14, {percent(shares.get('7d'))} over 7.",
        f"Last 30 days: {row.get('deck_count_30d') or 'unknown'} decks, {row.get('top8_30d') or 0} top-8 finishes, {row.get('wins_30d') or 0} wins.",
        f"The lists below are {cards_block.get('list_count') or 0} decklists of its {cards_block.get('deck_count') or 0} decks of the last {days} days.",
        "",
        "## Consensus main deck",
    ]
    named: List[str] = []
    tally = {(board, card["name"]): card for board in ("main", "side") for card in cards_block.get(board) or []}
    for board, title in (("main", None), ("side", "## Consensus sideboard")):
        if title:
            lines += ["", title]
        for name, copies in consensus(archetype, board).items():
            share = (tally.get((board, name)) or {}).get("share")
            lines.append(f"{copies} {name}" + (f" (in {share}% of the lists)" if share is not None else ""))
            named.append(name)
    for board, title in (("main", "## Other main deck cards some lists play"), ("side", "## Other sideboard cards some lists play")):
        extra = flex(archetype, board)
        if extra:
            lines += ["", title]
            for card in extra:
                lines.append(f"{card['name']}: in {card['share']}% of the lists, {card['copies']} copies on average")
                named.append(card["name"])
    results = [
        deck for deck in archetype.get("decks") or []
        if (deck.get("event") or {}).get("prestige", 0) >= 2 and re.match(r"^[1-8](st|nd|rd|th) Place$", deck.get("finish") or "")
    ][:RESULTS]
    if results:
        lines += ["", "## Recent top-8 finishes"]
        lines += [f"{deck['date']}: {deck['finish']}, {deck.get('event_name') or deck['event']['name']}" for deck in results]
    lines += ["", f"## The format's other top archetypes (for matchups; use these ids)"]
    others = opponents(item, read)
    for other, cards in others:
        lines.append(f"- {other['name']} (id {other['id']}): {percent(other.get('share_30d'))} of the format over 30 days; key cards: {', '.join(cards) or 'none listed'}")
        named += cards
    named = list(dict.fromkeys(named))
    lines += ["", "## Oracle text"]
    lines += [oracle_line(name, lookup) for name in named]
    if previous and item.merged_from:
        lines += ["", f"## The primer of {item.merged_from.archetype}, since merged into this archetype", "", previous.strip()]
    elif previous:
        lines += ["", "## The primer it has now", "", previous.strip()]
    return "\n".join(lines), named


def system_prompt(format_guide: str, example: str) -> str:
    return f"{SYSTEM}\n\n# The primer format\n\n{format_guide.strip()}\n\n# An example primer\n\n{example.strip()}\n"


# --- checks ---------------------------------------------------------------------------------------------------------


@dataclass
class Problem:
    kind: str
    message: str
    blocking: bool = True

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


MATCHUP = re.compile(r'^:::matchup\s+"([^"]*)"(.*)$')
QUANTITY = re.compile(r"(\d+)\s*\[\[([^\]|]+)")


def matchups(markdown: str) -> List[dict]:
    """Each `:::matchup` block's name, archetype and in and out cards."""
    found: List[dict] = []
    current: Optional[dict] = None
    for line in markdown.splitlines():
        stripped = line.strip()
        match = MATCHUP.match(stripped)
        if match:
            archetype = re.search(r"\barchetype=(\S+)", match.group(2))
            current = {"name": match.group(1), "archetype": archetype.group(1) if archetype else None, "in": [], "out": []}
            found.append(current)
        elif current is not None and stripped == ":::":
            current = None
        elif current is not None:
            for key in ("in", "out"):
                if stripped.lower().startswith(f"{key}:"):
                    current[key] += [(int(copies), name.strip()) for copies, name in QUANTITY.findall(stripped)]
    return found


def check(
    markdown: str, validation: dict, item: Item, lookup: Lookup, known: Set[str], named: Iterable[str],
) -> List[Problem]:
    """What is wrong with a primer of `item`'s archetype. `validation` is the API's `validate_primer` answer for it,
    `known` the format's archetype ids and `named` the cards of its facts, whose Oracle text names the tokens it makes."""
    problems: List[Problem] = []
    for each in validation.get("diagnostics") or []:
        where = f"{each.get('block')}, line {each.get('line')}" if each.get("block") else "the primer"
        problems.append(Problem("format", f"{where}: {each.get('message')}", each.get("severity") == "error"))
    if not validation.get("valid", False) and not any(problem.blocking for problem in problems):
        problems.append(Problem("format", "validate_primer says it is not valid"))
    if validation.get("archetype") != item.id:
        problems.append(Problem("format", f"front matter archetype is {validation.get('archetype')!r}, not {item.id!r}"))
    if (validation.get("format") or "").lower() != item.format["name"].lower():
        problems.append(Problem("format", f"front matter format is {validation.get('format')!r}, not {item.format['name']!r}"))
    texts = " ".join(((lookup(name) or {}).get("oracle_text") or "") for name in named).lower()
    for name in validation.get("cards") or []:
        token = re.search(rf"\b{re.escape(name.lower())}\b", texts) or f"token [[{name}]]" in markdown
        if lookup(name) is None and not token:
            problems.append(Problem("card", f"[[{name}]] is not a card Scryfall knows, nor a token the deck's cards make"))
    cards = item.archetype.get("cards") or {}
    main = {card["name"] for card in cards.get("main") or []} | set(consensus(item.archetype))
    side = {card["name"] for card in cards.get("side") or []} | set(consensus(item.archetype, "side"))
    for matchup in matchups(markdown):
        label = f"matchup {matchup['name']!r}"
        if matchup["archetype"] not in known:
            problems.append(Problem("matchup", f"{label}: archetype={matchup['archetype']} is not an archetype of {item.format['name']}"))
        for _, name in matchup["in"]:
            if name not in side:
                problems.append(Problem("matchup", f"{label}: in: [[{name}]] is not one of the deck's sideboard cards"))
        for _, name in matchup["out"]:
            if name not in main:
                problems.append(Problem("matchup", f"{label}: out: [[{name}]] is not one of the deck's main deck cards"))
        brought, taken = sum(copies for copies, _ in matchup["in"]), sum(copies for copies, _ in matchup["out"])
        if brought != taken:
            problems.append(Problem("matchup", f"{label}: brings in {brought} cards and takes out {taken}"))
    return problems


def format_ids(block: dict) -> Set[str]:
    """Every archetype id of a format's standings, in any window."""
    rows = list(block.get("standings") or [])
    for window in (block.get("standings_by_window") or {}).values():
        rows += window or []
    return {row["id"] for row in rows if isinstance(row, dict) and row.get("id")}


# --- writing --------------------------------------------------------------------------------------------------------


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, usage) -> None:
        for name in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))

    def dollars(self, model: str, batch: bool = False) -> float:
        prices = PRICES.get(model) or max(PRICES.values())
        counts = (self.input_tokens, self.output_tokens, self.cache_creation_input_tokens, self.cache_read_input_tokens)
        return sum(count * price for count, price in zip(counts, prices)) / 1_000_000 / (2 if batch else 1)


@dataclass
class Budget:
    """Dollars a run may spend."""

    limit: float
    spent: float = 0.0

    def allows(self, dollars: float) -> bool:
        return self.spent + dollars <= self.limit

    def spend(self, dollars: float) -> None:
        self.spent += dollars


def affordable(items: Sequence[Item], budget: Budget) -> Tuple[List[Item], List[Item]]:
    """The first of the items, in order, whose estimates (at batch prices) the budget left covers, and the rest."""
    total = 0.0
    for count, item in enumerate(items):
        if not budget.allows(total + item.estimate):
            return list(items[:count]), list(items[count:])
        total += item.estimate
    return list(items), []


def markdown_of(message) -> str:
    """The primer in a finished message: its text from the front matter's opening line, without a code fence around it."""
    if message.stop_reason == "refusal":
        raise PrimerError("Claude declined to write it")
    if message.stop_reason == "max_tokens":
        raise PrimerError(f"Claude ran out of tokens ({MAX_TOKENS})")
    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == "---"), None)
    if start is None:
        raise PrimerError("the reply has no front matter")
    lines = lines[start:]
    while lines and (not lines[-1].strip() or lines[-1].strip().startswith("```")):
        lines.pop()
    return "\n".join(lines) + "\n"


@dataclass
class Batch:
    """A submitted batch: its id and, for each request, the primer it is for with its archetype, format and model."""

    id: str
    items: Dict[str, dict]

    def json(self) -> dict:
        return {"id": self.id, "items": self.items}

    @staticmethod
    def of(body: dict) -> "Batch":
        return Batch(body["id"], dict(body.get("items") or {}))


@dataclass
class Collected:
    """What an ended batch gave: each request's finished message by custom_id, why the others have none, its tokens and
    what it cost at batch prices."""

    messages: Dict[str, object] = field(default_factory=dict)
    failed: Dict[str, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    dollars: float = 0.0


@dataclass
class Writer:
    """Asks Claude for primers: a run's as one Message Batch, a draft sent back as one streamed Messages call."""

    client: object
    system: str
    wait_minutes: float = WAIT_MINUTES
    poll_seconds: float = POLL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def write(self, messages: List[dict], model: str, effort: str):
        with self.client.beta.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": effort},
            system=[{"type": "text", "text": self.system, "cache_control": CACHE}],
            messages=messages,
        ) as stream:
            return stream.get_final_message()

    def submit(self, items: Sequence[Item], prompts: Sequence[str]) -> Batch:
        """The Batches API takes no betas and no fallbacks. A primer id can pass the 64 characters a custom_id may have,
        so the requests are numbered."""
        entries = {
            f"p{index}": {"primer_id": item.primer_id, "archetype": item.id, "format": item.format["format"], "model": item.model}
            for index, item in enumerate(items)
        }
        requests = [
            {
                "custom_id": custom_id,
                "params": {
                    "model": item.model,
                    "max_tokens": MAX_TOKENS,
                    "output_config": {"effort": item.effort},
                    "system": [{"type": "text", "text": self.system, "cache_control": CACHE}],
                    "messages": [{"role": "user", "content": prompt}],
                },
            }
            for custom_id, item, prompt in zip(entries, items, prompts)
        ]
        batch = self.client.messages.batches.create(requests=requests)
        log.info("Primers: batch %s submitted with %d primers", batch.id, len(requests))
        return Batch(batch.id, entries)

    def ended(self, batch: Batch) -> bool:
        return self.client.messages.batches.retrieve(batch.id).processing_status == "ended"

    def wait(self, batch: Batch) -> bool:
        """True once the batch has ended; False when it is still running after `wait_minutes`."""
        deadline = self.clock() + self.wait_minutes * 60
        while not self.ended(batch):
            if self.clock() >= deadline:
                log.warning("Primers: batch %s is still running after %.0f minutes; the next run collects it", batch.id, self.wait_minutes)
                return False
            self.sleep(self.poll_seconds)
        return True

    def collect(self, batch: Batch) -> Collected:
        collected = Collected()
        for result in self.client.messages.batches.results(batch.id):
            entry = batch.items.get(result.custom_id)
            if entry is None:
                continue
            if result.result.type != "succeeded":
                collected.failed[result.custom_id] = result.result.type
                continue
            message = result.result.message
            usage = Usage()
            usage.add(message.usage)
            collected.usage.add(message.usage)
            collected.dollars += usage.dollars(getattr(message, "model", None) or entry["model"], batch=True)
            collected.messages[result.custom_id] = message
        usage = collected.usage
        log.info(
            "Primers: batch %s: %d answered, %d not; tokens: %d input, %d output, %d cache write, %d cache read; cost $%.4f",
            batch.id, len(collected.messages), len(collected.failed), usage.input_tokens, usage.output_tokens,
            usage.cache_creation_input_tokens, usage.cache_read_input_tokens, collected.dollars,
        )
        return collected


def make_client():
    """The Anthropic client, or None when there is no ANTHROPIC_API_KEY."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(api_key=key, default_headers={"anthropic-workspace-id": workspace} if workspace else None)


def repair_message(problems: Sequence[Problem]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems if problem.blocking)
    return (
        "The primer has these problems:\n" + listed + "\n\nFix every one and reply with the whole corrected primer, Markdown only, "
        "starting with the front matter's `---` line."
    )


@dataclass
class Result:
    published: List[str] = field(default_factory=list)
    drafted: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    spent: float = 0.0


def write_draft(directory: Path, primer_id: str, markdown: str, problems: Sequence[Problem]) -> None:
    folder = directory / DRAFTS
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{primer_id}.md").write_text(markdown)
    report = folder / f"{primer_id}.problems.txt"
    if problems:
        report.write_text("".join(f"{problem}{'' if problem.blocking else ' (warning)'}\n" for problem in problems))
    elif report.exists():
        report.unlink()


def prompt_of(item: Item, api: Api, read: Callable[[str], Optional[dict]], lookup: Lookup, today: date) -> Tuple[str, List[str]]:
    previous = (api.source(item.previous.id) or {}).get("markdown") if item.previous else None
    return facts(item, read, lookup, previous, today)


def settle(
    item: Item, message, model: str, *, directory: Path, writer: Writer, api: Api, read: Callable[[str], Optional[dict]],
    lookup: Lookup, budget: Budget, publish: bool, state: Dict[str, dict], today: date, result: Result,
) -> None:
    """Checks the primer in the batch's answer for `item`, sends it back once if it has problems (a streamed call at the
    standard price to `model`, the one the batch asked), and with `publish` publishes it."""
    prompt, named = prompt_of(item, api, read, lookup, today)
    known = format_ids(item.format)
    messages: List[dict] = [{"role": "user", "content": prompt}]
    markdown, problems, written = None, [Problem("claude", "not written")], getattr(message, "model", None) or model
    for attempt in range(1 + REPAIRS):
        if attempt:
            if not budget.allows(2 * ESTIMATES[model]):
                break
            message = writer.write(messages, model, EFFORTS[model])
            written = getattr(message, "model", None) or model
            usage = Usage()
            usage.add(message.usage)
            cost = usage.dollars(written)
            budget.spend(cost)
            result.usage.add(message.usage)
            log.info(
                "Primer %s: sent back to %s; tokens: %d input, %d output, %d cache write, %d cache read; cost $%.4f",
                item.primer_id, written, usage.input_tokens, usage.output_tokens, usage.cache_creation_input_tokens,
                usage.cache_read_input_tokens, cost,
            )
        try:
            markdown = markdown_of(message)
        except PrimerError as error:
            problems = [Problem("claude", str(error))]
            break
        problems = check(markdown, api.validate(markdown), item, lookup, known, named)
        write_draft(directory, item.primer_id, markdown, problems)
        if not any(problem.blocking for problem in problems):
            break
        messages += [{"role": "assistant", "content": message.content}, {"role": "user", "content": repair_message(problems)}]
    blocking = [problem for problem in problems if problem.blocking]
    if blocking or markdown is None:
        log.warning("Primer %s not published: %s", item.primer_id, "; ".join(str(problem) for problem in blocking[:5]))
        result.failed.append(item.primer_id)
        return
    if not publish:
        result.drafted.append(item.primer_id)
        return
    cards = item.archetype.get("cards") or {}
    note = (
        f"Written by {written} from {cards.get('list_count') or 0} lists of the last {7 if cards.get('window') == '7d' else 30} days "
        f"on {today.isoformat()}: {'; '.join(item.reasons)}"
    )
    try:
        version = api.publish(item.primer_id, markdown, note)
    except PrimerError as error:
        log.warning("Primer %s: %s", item.primer_id, error)
        result.failed.append(item.primer_id)
        return
    state[item.primer_id] = {
        "archetype": item.id,
        "format": item.format["format"],
        "version": version,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": written,
        "lists": cards.get("list_count") or 0,
        "window": cards.get("window"),
        "consensus": consensus(item.archetype),
    }
    state_path = directory / STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, sort_keys=True, indent=1))
    result.published.append(item.primer_id)
    log.info("Primer %s: published as version %d (%s)", item.primer_id, version, "; ".join(item.reasons))


def save_batches(path: Path, batches: Sequence[Batch]) -> None:
    """The batches still running. The file is written even with none, since ops/primers.sh never deletes a file in R2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batches": [batch.json() for batch in batches]}, sort_keys=True, indent=1))


def collect_batch(
    batch: Batch, due: Dict[str, Item], *, writer: Writer, budget: Budget, result: Result, handle: Callable[..., None],
) -> Set[str]:
    """Reads an ended batch: each primer in it that is still due is settled with its item, the others are dropped and
    logged. Returns the ids of the primers it settled."""
    collected = writer.collect(batch)
    budget.spend(collected.dollars)
    result.usage.add(collected.usage)
    taken: Set[str] = set()
    for custom_id, entry in batch.items.items():
        item = due.get(entry["primer_id"])
        if item is None:
            log.info("Primer %s: dropped from batch %s, it is not due any more", entry["primer_id"], batch.id)
            continue
        taken.add(item.primer_id)
        message = collected.messages.get(custom_id)
        if message is None:
            log.warning("Primer %s: batch %s gave no primer (%s)", item.primer_id, batch.id, collected.failed.get(custom_id, "no result"))
            result.failed.append(item.primer_id)
            continue
        handle(item, message, entry["model"])
    return taken


def run(
    directory: Path, items: Sequence[Item], *, writer: Writer, api: Api, read: Callable[[str], Optional[dict]], lookup: Lookup,
    budget: Budget, publish: bool, state: Dict[str, dict], today: date,
) -> Result:
    """Collects the batches earlier runs left that have ended, then writes the primers of the items still to do, as many as
    the budget covers, as one batch and waits for it (`writer.wait_minutes`). Each primer is checked and, with `publish`,
    published as its answer is read; a batch still running is kept in BATCH_PATH."""
    result = Result()
    path = directory / BATCH_PATH
    due = {item.primer_id: item for item in items}
    handle = partial(
        settle, directory=directory, writer=writer, api=api, read=read, lookup=lookup, budget=budget, publish=publish,
        state=state, today=today, result=result,
    )
    collect = partial(collect_batch, due=due, writer=writer, budget=budget, result=result, handle=handle)
    running: List[Batch] = []
    taken: Set[str] = set()
    for batch in [Batch.of(body) for body in (read(BATCH_PATH) or {}).get("batches") or []]:
        if writer.ended(batch):
            taken |= collect(batch)
        else:
            log.info("Primers: batch %s is still running", batch.id)
            running.append(batch)
    held = {entry["primer_id"] for batch in running for entry in batch.items.values()}
    fresh = [item for item in items if item.primer_id not in taken | held]
    chosen, deferred = affordable(fresh, budget)
    if deferred:
        result.deferred = [item.primer_id for item in deferred]
        log.info(
            "$%.2f of $%.2f is left, which covers %d primers, so %d wait for the next run",
            budget.limit - budget.spent, budget.limit, len(chosen), len(deferred),
        )
    if chosen:
        batch = writer.submit(chosen, [prompt_of(item, api, read, lookup, today)[0] for item in chosen])
        running.append(batch)
        save_batches(path, running)
        if writer.wait(batch):
            running.remove(batch)
            collect(batch)
    save_batches(path, running)
    result.pending = [entry["primer_id"] for batch in running for entry in batch.items.values()]
    result.spent = budget.spent
    return result


# --- check mode -----------------------------------------------------------------------------------------------------


def check_published(
    explore: dict, formats: Sequence[str], count: int, api: Api, read: Callable[[str], Optional[dict]], lookup: Lookup,
    today: date, min_results: int = MIN_RESULTS,
) -> Tuple[int, int]:
    """Validates the published primer of each archetype of `formats` that gets one, as a draft of it would be (a primer
    under an archetype since merged away is not that archetype's: the app does not find it). Prints each one's
    problems and returns how many primers were checked and how many have a format or card problem (one the app or the
    API would trip on); matchup problems are the lists having moved since the primer was written."""
    primers = api.primers()
    blocks = {block["format"]: block for block in explore.get("formats") or []}
    checked = broken = 0
    for name in formats:
        block = blocks.get(name)
        if not block:
            continue
        rows = [row for row, _ in covered(block, read(f"snapshots/{name}.json"), count, min_results, today)]
        matched = match_primers(rows, [primer for primer in primers if primer.format.lower() == block["name"].lower()], {})
        for row in rows:
            primer, _ = matched.get(row["id"], (None, False))
            archetype = read(f"archetypes/{row['id']}.json")
            if primer is None or not archetype:
                continue
            markdown = (api.source(primer.id) or {}).get("markdown") or ""
            item = Item(block, row, archetype, primer, primer.id, [], 0)
            named = [card["name"] for board in ("main", "side") for card in ((archetype.get("cards") or {}).get(board) or [])]
            named += [card for _, cards in opponents(item, read) for card in cards]
            problems = check(markdown, api.validate(markdown), item, lookup, format_ids(block), named)
            checked += 1
            serious = [problem for problem in problems if problem.blocking and problem.kind in ("format", "card")]
            broken += bool(serious)
            print(f"{name:8} {primer.id}: " + ("ok" if not problems else f"{len(problems)} problems"))
            for problem in problems:
                print(f"    {problem}{'' if problem.blocking else ' (warning)'}")
    return checked, broken


# --- the command ----------------------------------------------------------------------------------------------------


def main(argv: Sequence[str], load_catalog=None, api: Optional[Api] = None, client=None, source=None, today: Optional[date] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mtgmeta primers", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="work directory: state/primers.json and the drafts; the data is read from DATA_URL")
    parser.add_argument("--format", action="append", default=[], help=f"a format, repeatable or comma-separated (default: {', '.join(FORMATS)})")
    parser.add_argument(
        "--count", type=int, default=COUNT,
        help=f"the first N archetypes of each format's 30-day standings, before the ones with {MIN_RESULTS} results (default {COUNT})",
    )
    parser.add_argument("--budget", type=float, default=5.0, help="the most dollars the run may spend on Claude (default 5)")
    parser.add_argument(
        "--minutes", type=float, default=0,
        help=f"wait this long for the batch; one still running is collected by the next run (default {WAIT_MINUTES})",
    )
    parser.add_argument("--archetype", action="append", default=[], help="an archetype id to write a primer for even when it is not due; repeatable")
    parser.add_argument("--publish", action="store_true", help="publish each passing primer (needs PRIMERS_ADMIN_TOKEN)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="list the primers that are due and why, and stop")
    mode.add_argument("--check", action="store_true", help="validate the published primers of the archetypes that get one, and stop")
    args = parser.parse_args(list(argv))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    formats = [part.strip().lower() for each in args.format for part in each.split(",") if part.strip()] or list(FORMATS)
    unknown = [name for name in formats if name not in FORMATS]
    if unknown:
        log.error("No primers for %s: only %s (Commander primers are not written here)", ", ".join(unknown), ", ".join(FORMATS))
        return 2
    if source is None:
        from .guides import Source

        source = Source(args.directory, os.environ.get("DATA_URL", "https://data.mooligan.com"))
    cache: Dict[str, Optional[dict]] = {}

    def read(path: str) -> Optional[dict]:
        if path not in cache:
            cache[path] = source.read(path)
        return cache[path]

    api = api or Api(os.environ.get("PRIMERS_API_URL", API_URL), os.environ.get("PRIMERS_ADMIN_TOKEN") or None)
    explore = read("explore.json")
    if not explore:
        log.error("explore.json could not be read")
        return 1
    today = today or datetime.now(timezone.utc).date()
    lookup = None
    if args.check or not args.plan:
        if load_catalog is None:
            from .scryfall import card_catalog as load_catalog
        from .guides import catalog_lookup

        lookup = catalog_lookup(load_catalog())
    if args.check:
        checked, broken = check_published(explore, formats, args.count, api, read, lookup, today)
        print(f"{checked} primers checked, {broken} with a format or card problem")
        return 1 if broken else 0

    state = read(STATE_PATH) or {}
    items, notes = plan(explore, formats, args.count, api.primers(), read, state, api, today, args.archetype)
    for note in notes:
        log.info("%s", note)
    if args.plan:
        for item in items:
            label = item.id if item.primer_id == item.id else f"{item.id} (primer {item.primer_id})"
            print(f"{item.format['format']:8} {label:60} {', '.join(item.reasons)}")
        chosen, _ = affordable(items, Budget(args.budget))
        print(
            f"{len(items)} primers due. At batch prices a primer costs about ${ESTIMATES[MODEL]:.2f} by {MODEL} and a revision "
            f"${ESTIMATES[REVISION_MODEL]:.2f} by {REVISION_MODEL} (a draft sent back once costs a call at twice that), so a budget "
            f"of ${args.budget:.2f} writes about {len(chosen)} of them this run."
        )
        return 0
    if not items:
        print("No primer is due")
        return 0
    client = client or make_client()
    if client is None:
        log.error("Writing primers needs ANTHROPIC_API_KEY (or --plan or --check)")
        return 2
    if args.publish and not api.can_publish:
        log.error("--publish needs PRIMERS_ADMIN_TOKEN")
        return 2
    writer = Writer(client, system_prompt(api.format_guide(), EXAMPLE.read_text()), wait_minutes=args.minutes or WAIT_MINUTES)
    result = run(
        args.directory, items, writer=writer, api=api, read=read, lookup=lookup, budget=Budget(args.budget),
        publish=args.publish, state=dict(state), today=today,
    )
    usage = result.usage
    print(
        f"{len(result.published)} published, {len(result.drafted)} drafted, {len(result.failed)} failed, "
        f"{len(result.deferred)} left for the next run, {len(result.pending)} in a batch still running; "
        f"tokens: {usage.input_tokens} input, {usage.output_tokens} output, "
        f"{usage.cache_creation_input_tokens} cache write, {usage.cache_read_input_tokens} cache read; cost ${result.spent:.2f}"
    )
    if result.failed:
        print(f"Failed: {', '.join(result.failed)} (drafts and their problems in {args.directory / DRAFTS})")
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
