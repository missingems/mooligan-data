"""movers/{format}.json: the cards whose price rose or fell most over the last day, week and month.

Prices come from the price catalog the card catalog workflow publishes (`catalog/prices/history.bin.gz`,
MTGJSON's TCGplayer retail price of every printing, day by day; its layout is at the top of
generators/Sources/Prices/main.swift). Play data is a card, not a printing, so a card's price is the cheapest
of its paper printings that come in the regular finish: what it costs to play it. A move compares only the
printings priced at both ends of its window, so a printing priced for the first time is no move. Scryfall's
default-cards bulk file says which printings are one card, and where the card is legal. See docs/data-format.md.
"""
from __future__ import annotations

import gzip
import heapq
import logging
import re
import urllib.request
import uuid
from array import array
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from itertools import accumulate
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .cards import slug
from .scryfall import DEFAULT_CARDS_URL, HEADERS, SKIPPED_LAYOUTS, _bulk_download_uri, bulk_cards

log = logging.getLogger(__name__)

SCHEMA = 1

# Each window and how many days back its price is compared with.
WINDOWS = (("1d", 1), ("7d", 7), ("30d", 30))
# Days of each printing's history kept: the longest window, and the day it starts from.
KEPT_DAYS = max(days for _, days in WINDOWS) + 1
# A printing's price holds over a day MTGJSON skipped, for at most this many days. Longer, and it has no price.
HELD_DAYS = 3
# Cards in each list.
LIMIT = 30
# A card moves only when it cost at least MIN_CENTS at both ends and at least NOTABLE_CENTS at one of them, and
# moved by at least MIN_CHANGE_CENTS: a bulk rare going from 10 cents to 30 is a 200% gain nobody wants to see.
MIN_CENTS = 50
NOTABLE_CENTS = 100
MIN_CHANGE_CENTS = 25
# The published formats and Scryfall's name for each in `legalities`. `all` is every card, legal anywhere or not.
FORMATS = {
    "modern": "modern",
    "standard": "standard",
    "pioneer": "pioneer",
    "legacy": "legacy",
    "pauper": "pauper",
    "vintage": "vintage",
    "premodern": "premodern",
    "penny_dreadful": "penny",
    "duel_commander": "duel",
}
LEGAL = {"legal", "restricted"}
# Sets whose printings are not the card to play with: gold-bordered World Championship decks and other
# memorabilia, tokens, minigames, and the Un-sets and playtest cards (Scryfall's "funny").
SKIPPED_SET_TYPES = {"memorabilia", "token", "minigame", "funny"}

NO_PRICE = -1


@dataclass
class PriceHistory:
    """Each printing's regular-finish TCGplayer price in cents over the last `KEPT_DAYS` days, `NO_PRICE` where it had none."""

    last_day: date
    prices: Dict[str, array]


def read_history(data: bytes, wanted: Optional[Iterable[str]] = None) -> PriceHistory:
    """Decodes `history.bin` (format 1), keeping the printings in `wanted` (Scryfall ids), or every one when it is None.

    Only the regular finish is kept, and only its last `KEPT_DAYS` days, each day's price filled in from the last
    one MTGJSON had, for up to `HELD_DAYS` days. The file holds about 13 million points: a series not kept is
    skipped by a regular expression, and a kept one is split into its varints by one, so no Python loop runs per byte.
    """
    if data[:4] != b"MTGH" or data[4] != 1:
        raise ValueError("not a format 1 price history")
    first_day = int.from_bytes(data[5:9], "little")
    last_day = int.from_bytes(data[9:13], "little")
    count = int.from_bytes(data[13:17], "little")
    keep = set(wanted) if wanted is not None else None
    start = last_day - KEPT_DAYS + 1
    position = 17

    def varint() -> int:
        nonlocal position
        match = _VARINT.match(data, position)
        position = match.end()
        return _value(match.group())

    prices: Dict[str, array] = {}
    for _ in range(count):
        printing = str(uuid.UUID(bytes=bytes(data[position:position + 16])))
        history_mask, latest_mask = data[position + 16], data[position + 17]
        position += 18
        for finish in range(3):
            if not history_mask & (1 << finish):
                continue
            points = varint()
            match = _varints(2 * points).match(data, position)
            position = match.end()
            if finish == 0 and (keep is None or printing in keep):
                series = _series(match.group(), first_day, start, last_day)
                if series is not None:
                    prices[printing] = series
        for _ in range(2 * bin(latest_mask).count("1")):
            varint()
    return PriceHistory(last_day=date(1970, 1, 1) + timedelta(days=last_day), prices=prices)


_VARINT = re.compile(rb"[\x80-\xff]*[\x00-\x7f]")


@lru_cache(maxsize=None)
def _varints(count: int) -> "re.Pattern[bytes]":
    return re.compile(rb"(?:[\x80-\xff]*[\x00-\x7f]){%d}" % count)


def _value(encoded: bytes) -> int:
    value = 0
    for shift, byte in enumerate(encoded):
        value |= (byte & 0x7F) << (7 * shift)
    return value


def _series(encoded: bytes, first_day: int, start: int, last_day: int) -> Optional[array]:
    """One series' points (day and price deltas, as prices.swift writes them) as its last `KEPT_DAYS` days of prices."""
    # The first point counts from zero cents, so it takes a few bytes; after it, nearly every delta fits one
    # (a day apart, a few cents moved), and then the bytes are the values.
    head = _varints(2).match(encoded)
    first_days, first_cents = (_value(one) for one in _VARINT.findall(head.group()))
    rest = encoded[head.end():]
    if max(rest, default=0) >= 0x80:
        rest = [_value(one) for one in _VARINT.findall(rest)]
    days = accumulate(rest[0::2], initial=first_day + first_days)
    cents = accumulate(((change >> 1) ^ -(change & 1) for change in rest[1::2]), initial=(first_cents >> 1) ^ -(first_cents & 1))
    series = array("i", [NO_PRICE] * KEPT_DAYS)
    held_from, held_cents = None, NO_PRICE
    for day, price in zip(days, cents):
        if day < start - HELD_DAYS:
            held_from, held_cents = day, price
            continue
        if held_from is not None:
            _hold(series, start, held_from, held_cents, day)
        if day >= start:
            series[day - start] = price
        held_from, held_cents = day, price
    if held_from is not None:
        _hold(series, start, held_from, held_cents, last_day + 1)
    return series if any(value != NO_PRICE for value in series) else None


def _hold(series: array, start: int, day: int, cents: int, until: int) -> None:
    """Fills the days after `day` and before `until` with `cents`, for at most `HELD_DAYS` days."""
    for held in range(day + 1, min(until, day + 1 + HELD_DAYS)):
        if held >= start:
            series[held - start] = cents


def printings(cards: Iterable[dict]) -> Dict[str, dict]:
    """The cards of Scryfall's default-cards file, each with the paper printings that are the card itself.

    oracle id -> `{"name", "slug", "legal": {format, ...}, "printings": {scryfall id: set code}}`. A foil-only
    printing is left out: the price history's regular finish is not a price of it that anyone can pay.
    """
    by_card: Dict[str, dict] = {}
    for card in cards:
        if (
            "paper" not in (card.get("games") or [])
            or card.get("oversized")
            or card.get("layout") in SKIPPED_LAYOUTS
            or card.get("set_type") in SKIPPED_SET_TYPES
            or "nonfoil" not in (card.get("finishes") or [])
            or not card.get("name")
        ):
            continue
        oracle_id = card.get("oracle_id") or (card.get("card_faces") or [{}])[0].get("oracle_id")
        if not oracle_id or not card.get("id"):
            continue
        entry = by_card.get(oracle_id)
        if entry is None:
            legalities = card.get("legalities") or {}
            entry = by_card[oracle_id] = {
                "name": card["name"],
                "slug": slug(card["name"]),
                "legal": {format for format, key in FORMATS.items() if legalities.get(key) in LEGAL},
                "printings": {},
            }
        entry["printings"][card["id"]] = card.get("set") or ""
    return by_card


def build_movers(history: PriceHistory, cards: Dict[str, dict], now: datetime) -> Dict[str, dict]:
    """The files to publish: format (and "all") -> its document."""
    moves = {name: _moves(history, cards, days) for name, days in WINDOWS}
    files = {}
    for format in ("all", *FORMATS):
        windows = {}
        for name, _ in WINDOWS:
            legal = [move for move in moves[name] if format == "all" or format in cards[move[2]]["legal"]]
            windows[name] = {
                "gainers": [_row(move, history, cards) for move in heapq.nlargest(LIMIT, (move for move in legal if move[1] > 0))],
                "losers": [_row(move, history, cards) for move in heapq.nsmallest(LIMIT, (move for move in legal if move[1] < 0))],
            }
        files[format] = {
            "schema": SCHEMA,
            "format": format,
            "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price_day": history.last_day.isoformat(),
            "windows": windows,
        }
    return files


def _moves(history: PriceHistory, cards: Dict[str, dict], days: int) -> List[Tuple[float, int, str, int, int, List[str]]]:
    """Every card that moved enough over the last `days` days.

    As (percent, change in cents, oracle id, cents before, cents now, the printings compared). Only the printings
    priced at both ends are compared, the card costing the cheapest of them at each end, so a printing priced for
    the first time in the window can't make the card look cheaper (or dearer) than it was.
    """
    moves = []
    for oracle_id, card in cards.items():
        matched = [
            printing
            for printing in card["printings"]
            if printing in history.prices and history.prices[printing][-1] != NO_PRICE and history.prices[printing][-1 - days] != NO_PRICE
        ]
        if not matched:
            continue
        now = min(history.prices[printing][-1] for printing in matched)
        before = min(history.prices[printing][-1 - days] for printing in matched)
        change = now - before
        if min(now, before) < MIN_CENTS or max(now, before) < NOTABLE_CENTS or abs(change) < MIN_CHANGE_CENTS:
            continue
        moves.append((round(change * 100 / before, 1), change, oracle_id, before, now, matched))
    return moves


def _row(move: Tuple[float, int, str, int, int, List[str]], history: PriceHistory, cards: Dict[str, dict]) -> dict:
    percent, change, oracle_id, before, now, matched = move
    cheapest = min(matched, key=lambda printing: history.prices[printing][-1])
    card = cards[oracle_id]
    series = [min((history.prices[printing][day] for printing in matched if history.prices[printing][day] != NO_PRICE), default=NO_PRICE) for day in range(1, KEPT_DAYS)]
    return {
        "name": card["name"],
        "slug": card["slug"],
        "oracle_id": oracle_id,
        "scryfall_id": cheapest,
        "set": card["printings"][cheapest],
        "price": now / 100,
        "previous": before / 100,
        "change": change / 100,
        "percent": percent,
        # The last 30 days of the printings compared, oldest first, for a sparkline; null on a day with no price.
        "history": [None if cents == NO_PRICE else cents / 100 for cents in series],
    }


def fetch_history(url: str) -> bytes:
    """The published price history, unzipped."""
    request = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(request, timeout=120) as response:
        return gzip.decompress(response.read())


def movers(history_url: str, now: datetime, watch: Optional[Callable[[Iterable[dict]], Iterable[dict]]] = None) -> Dict[str, dict]:
    """Downloads the price history and Scryfall's printings, and builds every format's file.

    `watch` sees Scryfall's printings on their way through, so the preview in today.json reads the same download.
    """
    stream = bulk_cards(_bulk_download_uri(DEFAULT_CARDS_URL))
    cards = printings(watch(stream) if watch else stream)
    wanted = {printing for card in cards.values() for printing in card["printings"]}
    history = read_history(fetch_history(history_url), wanted)
    log.info("Movers: %d cards, %d printings priced up to %s", len(cards), len(history.prices), history.last_day)
    return build_movers(history, cards, now)
