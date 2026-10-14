"""today.json's preview, and previews.json: the cards Scryfall added to its default-cards file, from sets not released yet.

A printing is new when its id is not among the ids the last run saved. today.json's preview is one of those new since
the last run; previews.json lists every eligible printing first seen in the last 7 days, from the date each was first
seen (`state/printing-first-seen.json.gz`). The movers already stream the file once a run, so both watch the same
stream. See docs/data-format.md.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set

from .scryfall import SKIPPED_LAYOUTS

log = logging.getLogger(__name__)

# Every printing id of the last run's default-cards file, sorted, as a gzipped JSON array (about 2.4 MB for 118,000
# printings). Ids, because a printing's Scryfall id never changes, and a per-set count and hash would say that a set
# changed but not which of its printings are new.
STATE = "state/printing-ids.json.gz"
# When each recent, eligible printing was first seen, as a gzipped JSON object of id to ISO date. It holds only the
# printings that can still be listed (see KEEP_DAYS): a printing in STATE but not here was seen long enough ago to be
# old, so pruning an entry never makes an old printing look new, since newness is decided by STATE alone.
FIRST_SEEN_STATE = "state/printing-first-seen.json.gz"
# The published list of printings first seen in the last WINDOW_DAYS days, next to today.json.
PUBLISHED = "previews.json"
SCHEMA = 1
# A printing is listed while the day it was first seen is at most this many days before today (so for 8 daily runs).
WINDOW_DAYS = 7
# A first-seen entry is pruned once it is older than this, or the printing was released more than this long ago.
KEEP_DAYS = 30
# Sets whose printings are not cards: tokens, art cards and other memorabilia, minigame inserts.
SKIPPED_SET_TYPES = {"token", "memorabilia", "minigame"}
# Scryfall's `preview` object: when and where a card was shown first, credited when present.
PREVIEW_FIELDS = ("previewed_at", "source", "source_uri")


def read_seen(directory: Path) -> Optional[Set[str]]:
    """The printing ids the last run saved, or None when there is no such file (a first run) or it cannot be read."""
    path = directory / STATE
    if not path.exists():
        return None
    try:
        ids = json.loads(gzip.decompress(path.read_bytes()))
        if not isinstance(ids, list):
            raise ValueError("not a list of ids")
        seen = set(ids)
    except (OSError, EOFError, zlib.error, ValueError, TypeError) as error:
        log.warning("Last run's printing ids could not be read, so this run has no preview: %s", error)
        return None
    return seen or None


def write_seen(directory: Path, ids: Iterable[str]) -> None:
    """Saves the printing ids to the state file, the same bytes for the same ids."""
    path = directory / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(sorted(ids), separators=(",", ":")).encode(), mtime=0))


def read_first_seen(directory: Path) -> Optional[Dict[str, str]]:
    """The first-seen date by printing id the last run saved, or None when there is no such file or it cannot be read.

    None is what makes the next run a bootstrap (see `NewPrintings`); an empty file is a mapping with no entries.
    """
    path = directory / FIRST_SEEN_STATE
    if not path.exists():
        return None
    try:
        mapping = json.loads(gzip.decompress(path.read_bytes()))
        if not isinstance(mapping, dict):
            raise ValueError("not an object of dates")
    except (OSError, EOFError, zlib.error, ValueError, TypeError) as error:
        log.warning("Last run's first-seen dates could not be read, so this run starts them again: %s", error)
        return None
    return {key: value for key, value in mapping.items() if isinstance(key, str) and _day(value)}


def write_first_seen(directory: Path, first_seen: Dict[str, str]) -> None:
    """Saves the first-seen dates, the same bytes for the same dates."""
    path = directory / FIRST_SEEN_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(first_seen, sort_keys=True, separators=(",", ":")).encode(), mtime=0))


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass
class NewPrintings:
    """The printings of one pass over Scryfall's default-cards file that the last run's `seen` did not have.

    `seen` is None on a first run, when nothing is new. `ids` is every id the stream had, `cards` the new printings that
    can be a preview (trimmed to what `pick` needs), and `complete` says the stream was read to its end.

    `first_seen` is the dates the last run saved (None when it saved none: the bootstrap) and `today` the UTC day of this
    run. A printing that can be a preview is given a first-seen date: the one saved, else `today` when it is new, else,
    on the bootstrap only, the day Scryfall says it was previewed when that is in the last WINDOW_DAYS days and the
    printing is not released yet. Every other existing printing is old, with no date. `recorded` is those dates after
    pruning, to save, and `tracked` the same printings trimmed, for `build_previews`.
    """

    seen: Optional[Set[str]]
    first_seen: Optional[Dict[str, str]] = None
    today: date = field(default_factory=_utc_today)
    ids: Set[str] = field(default_factory=set)
    cards: List[dict] = field(default_factory=list)
    recorded: Dict[str, str] = field(default_factory=dict)
    tracked: List[dict] = field(default_factory=list)
    complete: bool = False

    def watch(self, cards: Iterable[dict]) -> Iterator[dict]:
        """Passes every card through as it comes, noting its id and whether it is new."""
        for card in cards:
            printing = card.get("id")
            if printing:
                self.ids.add(printing)
                if _candidate(card):
                    is_new = self.seen is not None and printing not in self.seen
                    if is_new:
                        self.cards.append(_trimmed(card))
                    self._track(card, is_new)
            yield card
        # A stream that fails partway never gets here, and a partial read must not be saved:
        # every printing it missed would look new the next run.
        self.complete = True

    def _track(self, card: dict, is_new: bool) -> None:
        day = self._first_day(card, is_new)
        if day is None or self._pruned(day, card):
            return
        self.recorded[card["id"]] = day
        self.tracked.append({**_trimmed(card), "first_seen": day})

    def _first_day(self, card: dict, is_new: bool) -> Optional[str]:
        saved = (self.first_seen or {}).get(card["id"])
        if saved:
            return saved
        if is_new:
            return self.today.isoformat()
        if self.first_seen is None and _day(card.get("released_at")) > self.today.toordinal():
            previewed = (card.get("preview") or {}).get("previewed_at")
            if self.today.toordinal() - WINDOW_DAYS <= _day(previewed) <= self.today.toordinal():
                return previewed
        return None

    def _pruned(self, day: str, card: dict) -> bool:
        oldest = self.today.toordinal() - KEEP_DAYS
        released = _day(card.get("released_at"))
        return _day(day) < oldest or 0 < released < oldest

    def save(self, directory: Path) -> None:
        """Saves the first-seen dates, then the ids: a run that stops between them leaves new printings dated, not lost."""
        write_first_seen(directory, self.recorded)
        write_seen(directory, self.ids)


def _candidate(card: dict) -> bool:
    """Whether a printing can be a preview: a paper card, not a token, art card, emblem, oversized card or memorabilia."""
    return bool(
        card.get("name")
        and card.get("id")
        and not card.get("digital")
        and not card.get("oversized")
        and card.get("layout") not in SKIPPED_LAYOUTS
        and card.get("set_type") not in SKIPPED_SET_TYPES
    )


def _trimmed(card: dict) -> dict:
    """What the pick and the published card need of a printing, so many new printings stay small."""
    return {
        "id": card["id"],
        "name": card["name"],
        "oracle_id": card.get("oracle_id") or (card.get("card_faces") or [{}])[0].get("oracle_id"),
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "released_at": card.get("released_at"),
        "reprint": card.get("reprint"),
        **({"preview": card["preview"]} if card.get("preview") else {}),
    }


def pick(cards: Iterable[dict], today: date) -> Optional[dict]:
    """The one preview card, as published, from the new printings (`NewPrintings.cards`); None when none is upcoming.

    Only a printing released after `today` can be the preview, so one with no usable `released_at` cannot. That is
    eligibility only: the release date does not rank. Among the eligible, a card's first printing comes before a
    reprint, then the most recently previewed card first (a card with no preview date after those with one, since it was
    added since the last run all the same), then the set code and collector number.
    """
    upcoming = [card for card in cards if _day(card.get("released_at")) > today.toordinal()]
    if not upcoming:
        return None
    return _published(min(upcoming, key=_order))


def build_previews(tracked: Iterable[dict], now: datetime) -> dict:
    """previews.json: every tracked printing first seen in the last WINDOW_DAYS days and not released by `now`'s UTC day.

    Newest first seen first, then the most recently previewed (a card with no preview date after those with one), then
    the set code, the collector number and the id; never the release date, which only decides who is listed.
    """
    now = now.astimezone(timezone.utc)
    today = now.date().toordinal()
    listed = [
        card for card in tracked
        if _day(card.get("released_at")) > today and _day(card.get("first_seen")) >= today - WINDOW_DAYS
    ]
    listed.sort(key=lambda card: (
        -_day(card["first_seen"]), -_day((card.get("preview") or {}).get("previewed_at")), card.get("set") or "",
        _number(card.get("collector_number")), card["id"],
    ))
    cards = [_listed(card) for card in listed]
    return {
        "schema": SCHEMA,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": WINDOW_DAYS,
        "count": len(cards),
        "cards": cards,
    }


def write_previews(directory: Path, now: datetime, new: NewPrintings) -> List[str]:
    """Writes previews.json from the printings `new` tracked and returns its path."""
    document = build_previews(new.tracked, now)
    (directory / PUBLISHED).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return [PUBLISHED]


def _listed(card: dict) -> dict:
    return {
        "name": card["name"],
        "oracle_id": card.get("oracle_id"),
        "scryfall_id": card["id"],
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "collector_number": card.get("collector_number"),
        "released_at": card.get("released_at"),
        "first_seen": card["first_seen"],
        "previewed_at": (card.get("preview") or {}).get("previewed_at") or None,
    }


def _order(card: dict) -> tuple:
    """First printing before reprint, then the newest preview, set and collector number."""
    previewed = _day((card.get("preview") or {}).get("previewed_at"))
    return (bool(card.get("reprint")), -previewed, card.get("set") or "", _number(card.get("collector_number")))


def _published(card: dict) -> dict:
    preview = card.get("preview") or {}
    return {
        "name": card["name"],
        "oracle_id": card.get("oracle_id"),
        "scryfall_id": card["id"],
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "released_at": card.get("released_at"),
        **{key: preview[key] for key in PREVIEW_FIELDS if preview.get(key)},
    }


def _day(value: Optional[str]) -> int:
    """An ISO date as a day number, 0 when it is missing or not a date."""
    try:
        return date.fromisoformat(value).toordinal()
    except (TypeError, ValueError):
        return 0


def _number(collector_number: Optional[str]) -> tuple:
    """A collector number in natural order: "9" before "10" before "10a"."""
    text = collector_number or ""
    digits = re.match(r"\d*", text).group()
    return (int(digits) if digits else 0, text)
