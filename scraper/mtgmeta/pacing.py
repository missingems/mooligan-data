"""Paces the decklist downloads like a reader, and stops quickly and cleanly when MTGGoldfish refuses them.

Everything here is pure: the random numbers, the sleeping and the clock are passed in, so the tests run
instantly. The scraper supplies what to download and what to do with the answers.
"""
from __future__ import annotations

import json
import logging
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Sequence

from .browser import BlockedError, Fetched

log = logging.getLogger(__name__)

# Now and then a reader stops on a deck: the chance after each batch, and how long (seconds).
LONG_PAUSE_CHANCE = 0.04
LONG_PAUSE = (20.0, 60.0)
# Decks downloaded per page visit.
GROUP_SIZE = (6, 14)
# Seconds on a visited page before its decks.
DWELL = (1.5, 5.0)
# Seconds waited after the first refusal; each further one doubles it, with some jitter.
BACKOFF = 30.0
# The longest single wait, whatever Retry-After says.
MAX_BACKOFF = 600.0
# Consecutive refused attempts that end the deck phase.
MAX_REFUSALS = 3
# How far (in places) a visit may move from its newest-first rank: roughly newest first, never strictly in order.
_SHUFFLE = 4.0


@dataclass
class DeckPacing:
    """How the deck phase moves: `concurrency` decks at a time, a median gap of `delay` seconds between batches,
    at most `minutes` of wall-clock time for every format together, and `per_run` new decks in all."""

    concurrency: int = 2
    delay: float = 2.0
    minutes: float = 40.0
    per_run: int = 800


class Pacer:
    def __init__(
        self,
        pacing: DeckPacing,
        rng: random.Random,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pacing = pacing
        self.rng = rng
        self._sleep = sleep
        self._clock = clock
        self.started = clock()

    def gap(self) -> float:
        """Sleeps the time between two batches and returns it: usually about `delay`, sometimes much longer."""
        delay = self.pacing.delay
        if delay <= 0:
            return 0.0
        seconds = min(max(self.rng.lognormvariate(math.log(delay), 0.5), 0.4 * delay), 5 * delay)
        if self.rng.random() < LONG_PAUSE_CHANCE:
            seconds += self.rng.uniform(*LONG_PAUSE)
        self._sleep(seconds)
        return seconds

    def dwell(self) -> float:
        """Sleeps the time a reader spends on a page before going to its decks."""
        if self.pacing.delay <= 0:
            return 0.0
        seconds = self.rng.uniform(*DWELL)
        self._sleep(seconds)
        return seconds

    def backoff_seconds(self, refusals: int, retry_after: Optional[float] = None) -> float:
        """How long to wait after the `refusals`-th refusal in a row, without waiting."""
        seconds = BACKOFF * 2 ** (refusals - 1) * self.rng.uniform(0.8, 1.2)
        if retry_after is not None and retry_after > seconds:
            seconds = retry_after
        return min(seconds, MAX_BACKOFF)

    def wait(self, seconds: float) -> None:
        self._sleep(seconds)

    def elapsed(self) -> float:
        return self._clock() - self.started

    def time_left(self) -> float:
        return self.pacing.minutes * 60 - self.elapsed()


class _Wanted(Protocol):
    deck_id: str
    format: str
    event_id: Optional[str]
    archetype_id: Optional[str]


@dataclass
class Visit:
    """One look at a page, and the decks a reader would open from it."""

    path: str
    decks: List


def deck_path(deck_id: str) -> str:
    return f"/deck/download/{deck_id}"


def _source_page(deck: _Wanted) -> str:
    """The page a reader would come to this deck from."""
    if deck.event_id:
        return f"/tournament/{deck.event_id}"
    if deck.archetype_id:
        return f"/archetype/{deck.archetype_id}"
    return f"/metagame/{deck.format}"


def _format_visits(decks: Sequence, rng: random.Random) -> List[Visit]:
    """One format's visits: its decks grouped by source page, each group cut into visits, roughly newest first."""
    groups: Dict[str, List[int]] = {}
    for place, deck in enumerate(decks):
        groups.setdefault(_source_page(deck), []).append(place)
    keyed = []
    for path, places in groups.items():
        previous = -math.inf
        start = 0
        while start < len(places):
            size = rng.randint(*GROUP_SIZE)
            chunk = [decks[place] for place in places[start : start + size]]
            rng.shuffle(chunk)
            # A visit sits near the place of its newest deck. Visits of one page never swap.
            key = max(places[start] + rng.uniform(0, _SHUFFLE), previous)
            keyed.append((key, Visit(path, chunk)))
            previous = key
            start += size
    keyed.sort(key=lambda pair: pair[0])
    return [visit for _, visit in keyed]


def build_plan(wanted: Dict[str, Sequence], pacing: DeckPacing, rng: random.Random) -> List[Visit]:
    """The visits of a run, from each format's decks (already newest first, featured first, and cut to its allowance).

    Formats take turns, one visit each, and the plan holds at most `per_run` decks.
    """
    queues = [_format_visits(decks, rng) for decks in wanted.values()]
    plan: List[Visit] = []
    count = 0
    position = 0
    while any(position < len(queue) for queue in queues):
        for queue in queues:
            if position >= len(queue):
                continue
            visit = queue[position]
            room = pacing.per_run - count
            if room <= 0:
                return plan
            if len(visit.decks) > room:
                visit = Visit(visit.path, visit.decks[:room])
            plan.append(visit)
            count += len(visit.decks)
        position += 1
    return plan


@dataclass
class DeckOutcome:
    # Decks that got an answer other than a refusal (including a deleted deck).
    downloaded_attempted: int = 0
    # Decks of the plan that never got one.
    left: int = 0
    # "done", "time" (the budget ran out) or "blocked" (too many refusals in a row).
    reason: str = "done"
    # What the first refusal looked like, for the log and the report.
    refusal: Optional[str] = None
    refusals_total: int = 0


class _Downloads:
    """The state of one run of `run_downloads`."""

    def __init__(self, browser, pacer: Pacer, handle: Callable[[Visit, List[Fetched]], None]) -> None:
        self.browser = browser
        self.pacer = pacer
        self.handle = handle
        self.outcome = DeckOutcome()
        self.consecutive = 0
        self.stopped = False

    def stop(self, reason: str) -> None:
        self.outcome.reason = reason
        self.stopped = True

    def refused(self, detail: str, retry_after: Optional[float]) -> bool:
        """Counts a refusal and waits it out. False when the phase should end instead."""
        outcome = self.outcome
        outcome.refusals_total += 1
        self.consecutive += 1
        if outcome.refusal is None:
            outcome.refusal = detail
            log.warning("MTGGoldfish refused a deck download: %s", detail)
        else:
            log.info("Refused again (%d in a row): %s", self.consecutive, detail)
        if self.consecutive >= MAX_REFUSALS:
            self.stop("blocked")
            return False
        seconds = self.pacer.backoff_seconds(self.consecutive, retry_after)
        if seconds > self.pacer.time_left():
            self.stop("blocked")
            return False
        log.info("Waiting %.0f s before trying again", seconds)
        self.pacer.wait(seconds)
        return True

    def enter(self, path: str) -> bool:
        """Visits the page the decks come from, then looks at it for a while. False when the phase ended."""
        while True:
            try:
                self.browser.page(path)
            except BlockedError as error:
                if not self.refused(str(error), None):
                    return False
                continue
            except Exception as error:  # noqa: BLE001 - the downloads go ahead without the visit
                log.info("Could not visit %s: %s", path, error)
            self.pacer.dwell()
            return True

    def batch(self, visit: Visit, decks: List, last: bool) -> bool:
        """Downloads `decks`, retrying what is refused after a wait. False when the phase ended."""
        while decks:
            if self.pacer.time_left() <= 0:
                self.stop("time")
                return False
            by_path = {deck_path(deck.deck_id): deck for deck in decks}
            fetched = self.browser.fetch_batch(list(by_path))
            answered = [f for f in fetched if not f.refused]
            refused = [f for f in fetched if f.refused]
            if answered:
                self.handle(visit, answered)
                self.outcome.downloaded_attempted += len(answered)
            if not refused:
                self.consecutive = 0
                if not last:
                    self.pacer.gap()
                return True
            # Stop sending, wait, look at the page again and ask for only what was refused.
            retry_after = max((f.retry_after for f in refused if f.retry_after is not None), default=None)
            if not self.refused(refused[0].describe(), retry_after) or not self.enter(visit.path):
                return False
            decks = [by_path[f.path] for f in refused if f.path in by_path]
        return True


def run_downloads(
    browser, visits: Sequence[Visit], pacer: Pacer, handle: Callable[[Visit, List[Fetched]], None]
) -> DeckOutcome:
    """Visits each page and downloads its decks `concurrency` at a time, backing off when refused.

    `handle` gets the answers that were not refusals, to parse and save. A refusal never raises.
    """
    run = _Downloads(browser, pacer, handle)
    size = max(1, pacer.pacing.concurrency)
    for index, visit in enumerate(visits):
        if pacer.time_left() <= 0:
            run.stop("time")
            break
        if not run.enter(visit.path):
            break
        for start in range(0, len(visit.decks), size):
            last = index == len(visits) - 1 and start + size >= len(visit.decks)
            if not run.batch(visit, visit.decks[start : start + size], last):
                break
        if run.stopped:
            break
    run.outcome.left = sum(len(visit.decks) for visit in visits) - run.outcome.downloaded_attempted
    return run.outcome


def note_deck_block(path: Path, blocked: bool, detail: Optional[str], now: datetime) -> int:
    """Counts the runs in a row whose deck downloads were blocked, in the JSON file at `path`, and returns the count."""
    try:
        previous = json.loads(path.read_text())
        count = int(previous["blocked_runs"])
        last = previous.get("last_blocked")
    except (OSError, ValueError, KeyError, TypeError):
        count, last = 0, None
    count = count + 1 if blocked else 0
    if blocked:
        last = now.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"blocked_runs": count, "last_blocked": last, "detail": detail}))
    return count
