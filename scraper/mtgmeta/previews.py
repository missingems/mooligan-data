"""today.json's preview: one card Scryfall added since the last run.

It is found by comparing the printings of Scryfall's default-cards bulk file with the ids the last run saved. The
movers already stream that file once a run, so the preview watches the same stream. See docs/data-format.md.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import zlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Set

from .scryfall import SKIPPED_LAYOUTS

log = logging.getLogger(__name__)

# Every printing id of the last run's default-cards file, sorted, as a gzipped JSON array (about 2.4 MB for 118,000
# printings). Ids, because a printing's Scryfall id never changes, and a per-set count and hash would say that a set
# changed but not which of its printings are new.
STATE = "state/printing-ids.json.gz"
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


@dataclass
class NewPrintings:
    """The printings of one pass over Scryfall's default-cards file that the last run's `seen` did not have.

    `seen` is None on a first run, when nothing is new. `ids` is every id the stream had, `cards` the new printings that
    can be a preview (trimmed to what `pick` needs), and `complete` says the stream was read to its end.
    """

    seen: Optional[Set[str]]
    ids: Set[str] = field(default_factory=set)
    cards: List[dict] = field(default_factory=list)
    complete: bool = False

    def watch(self, cards: Iterable[dict]) -> Iterator[dict]:
        """Passes every card through as it comes, noting its id and whether it is new."""
        for card in cards:
            printing = card.get("id")
            if printing:
                self.ids.add(printing)
                if self.seen is not None and printing not in self.seen and _candidate(card):
                    self.cards.append(_trimmed(card))
            yield card
        # A stream that fails partway never gets here, and a partial read must not be saved:
        # every printing it missed would look new the next run.
        self.complete = True

    def save(self, directory: Path) -> None:
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
    """The one preview card, as published, from the new printings (`NewPrintings.cards`); None when there are none.

    The first step with a printing decides: one not released yet (a first printing before a reprint, then one
    Scryfall shows a preview for, newest first), else a Secret Lair one, else any other. Ties go to the newest
    release, then the set code and collector number.
    """
    cards = list(cards)
    upcoming = [card for card in cards if _day(card.get("released_at")) > today.toordinal()]
    # Scryfall has no Secret Lair set type: `sld` is a "box" set, and the other drops (slc, slp, slu) are named for it.
    secret_lair = [card for card in cards if card.get("set") == "sld" or (card.get("set_name") or "").startswith("Secret Lair")]
    for found, previews in ((upcoming, True), (secret_lair, False), (cards, False)):
        if found:
            return _published(min(found, key=lambda card: _order(card, previews)))
    return None


def _order(card: dict, previews: bool) -> tuple:
    """First printing before reprint, then (for an upcoming card) the newest preview, the newest release, set and collector number."""
    previewed = _day((card.get("preview") or {}).get("previewed_at")) if previews else 0
    return (bool(card.get("reprint")), -previewed, -_day(card.get("released_at")), card.get("set") or "", _number(card.get("collector_number")))


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
