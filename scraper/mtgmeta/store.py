"""The published data set: one snapshot per format, one file per deck, and an index.

The directory mirrors the R2 bucket. The workflow downloads the previous
snapshots and deck id list into it, the scrape updates it, and `finish()`
writes the files the workflow uploads (see docs/data-format.md).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Set

from .cards import FormatDecks, build_card_pages, page_hash
from .models import ArchetypeHistory, ArchetypeResult, Deck, Event, Meta, to_document

SCHEMA = 1

log = logging.getLogger(__name__)


class Store(Protocol):
    def save_meta(self, meta: Meta) -> None: ...
    def save_event(self, event: Event) -> None: ...
    def save_decks(self, decks: List[Deck]) -> None: ...
    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]: ...
    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]: ...
    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]: ...
    def save_archetype(self, history: ArchetypeHistory) -> None: ...
    def ignored_event_ids(self) -> Set[str]: ...
    def missing_deck_ids(self) -> Set[str]: ...
    def mark_missing_decks(self, deck_ids: Iterable[str]) -> None: ...


class SnapshotStore:
    def __init__(self, root: Path, formats: Sequence[str], history_days: int, now: Optional[datetime] = None) -> None:
        self._root = root
        self._now = now or datetime.now(timezone.utc)
        self._cutoff = self._now - timedelta(days=history_days)
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        for format in formats:
            path = root / "snapshots" / f"{format}.json"
            previous = json.loads(path.read_text()) if path.exists() else {}
            self._snapshots[format] = {
                "meta": previous.get("meta", {}),
                "events": {event["event_id"]: event for event in previous.get("events", [])},
                "archetypes": previous.get("archetypes", {}),
            }
        ids_path = root / "state" / "deck-ids.json"
        self._deck_ids: Set[str] = set(json.loads(ids_path.read_text())) if ids_path.exists() else set()
        duplicates_path = root / "state" / "duplicate-event-ids.json"
        self._duplicates: Set[str] = set(json.loads(duplicates_path.read_text())) if duplicates_path.exists() else set()
        missing_path = root / "state" / "missing-deck-ids.json"
        self._missing: Set[str] = set(json.loads(missing_path.read_text())) if missing_path.exists() else set()
        # What each stored deck plays, so card pages can be built without downloading every deck again.
        self._deck_cards: Dict[str, Dict[str, dict]] = {}
        for format in formats:
            cards_path = root / "state" / "deck-cards" / f"{format}.json"
            self._deck_cards[format] = json.loads(cards_path.read_text()) if cards_path.exists() else {}
        hashes_path = root / "state" / "card-hashes.json"
        self._card_hashes: Dict[str, str] = json.loads(hashes_path.read_text()) if hashes_path.exists() else {}

    # ---- Store

    def save_meta(self, meta: Meta) -> None:
        document = _jsonable(to_document(meta, drop=("format",)))
        document["last_updated"] = self._stamp()
        self._snapshot(meta.format)["meta"][meta.timeframe] = document

    def save_event(self, event: Event) -> None:
        document = _jsonable(to_document(event, drop=("format",)))
        document["last_updated"] = self._stamp()
        self._snapshot(event.format)["events"][event.event_id] = document

    def save_decks(self, decks: List[Deck]) -> None:
        for deck in decks:
            path = self._root / "decks" / f"{deck.deck_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            document = _jsonable(to_document(deck))
            document["last_updated"] = self._stamp()
            path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
            self._deck_ids.add(deck.deck_id)
            self._deck_cards.setdefault(deck.format, {})[deck.deck_id] = {
                "m": [[card.quantity, card.card_name] for card in deck.mainboard],
                "s": [[card.quantity, card.card_name] for card in deck.sideboard],
            }

    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]:
        return {deck_id for deck_id in deck_ids if deck_id in self._deck_ids}

    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]:
        stored = set().union(*(snapshot["events"].keys() for snapshot in self._snapshots.values()))
        return {event_id for event_id in event_ids if event_id in stored}

    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]:
        archetype = self._snapshot(format)["archetypes"].get(archetype_id)
        if not archetype:
            return []
        return [ArchetypeResult(**{**result, "date": _parse(result["date"])}) for result in archetype["results"]]

    def ignored_event_ids(self) -> Set[str]:
        """Duplicate events found earlier, which the scrape must not read or count again."""
        return set(self._duplicates)

    def missing_deck_ids(self) -> Set[str]:
        """Decks MTGGoldfish no longer serves; asking again every run would be wasted."""
        return set(self._missing)

    def mark_missing_decks(self, deck_ids: Iterable[str]) -> None:
        self._missing |= set(deck_ids)

    def save_archetype(self, history: ArchetypeHistory) -> None:
        document = _jsonable(to_document(history, drop=("format",)))
        document["last_updated"] = self._stamp()
        self._snapshot(history.format)["archetypes"][history.archetype_id] = document

    # ---- Publishing

    def finish(self) -> List[str]:
        """Writes the snapshots, deck id list and index, and returns the snapshot paths written."""
        written = []
        formats = {}
        card_decks: Dict[str, FormatDecks] = {}
        for format, snapshot in self._snapshots.items():
            self._duplicates |= _duplicate_event_ids(snapshot["events"].values())
            duplicates = self._duplicates
            events = sorted(
                (
                    event
                    for event in snapshot["events"].values()
                    if _parse(event["date"]) >= self._cutoff and event["event_id"] not in duplicates
                ),
                key=lambda event: (event["date"], event["event_id"]),
                reverse=True,
            )
            archetypes = {}
            for archetype_id, archetype in sorted(snapshot["archetypes"].items()):
                results = [result for result in archetype["results"] if result.get("event_id") not in duplicates]
                # Archetypes no longer in the metagame drop out once their results age past the window.
                if any(_parse(result["date"]) >= self._cutoff for result in results):
                    archetypes[archetype_id] = {**archetype, "results": results}
            if not snapshot["meta"] and not events and not archetypes:
                continue
            document = {
                "schema": SCHEMA,
                "format": format,
                "generated_at": self._stamp(),
                "meta": dict(sorted(snapshot["meta"].items())),
                "events": events,
                "archetypes": archetypes,
            }
            # Decks of this format still in the window, newest first, with their archetype.
            membership: Dict[str, tuple] = {}
            for archetype in archetypes.values():
                if archetype["deck_id"]:
                    membership.setdefault(archetype["deck_id"], (archetype["archetype_id"], archetype["name"]))
                for result in archetype["results"]:
                    membership.setdefault(result["deck_id"], (archetype["archetype_id"], archetype["name"]))
            # Decks seen only in an event still count, under the name that event gave them.
            for event in events:
                for result in event["results"]:
                    membership.setdefault(result["deck_id"], (result.get("archetype_id") or "", result.get("archetype") or "Other"))
            stored = self._deck_cards.get(format, {})
            self._deck_cards[format] = {deck_id: stored[deck_id] for deck_id in membership if deck_id in stored}
            card_decks[format] = FormatDecks(self._deck_cards[format], membership)

            body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
            relative = f"snapshots/{format}.json"
            self._write(relative, body)
            written.append(relative)
            formats[format] = {
                "path": relative,
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "generated_at": document["generated_at"],
                "events": len(events),
                "archetypes": len(archetypes),
            }
        for format, contents in self._deck_cards.items():
            self._write(f"state/deck-cards/{format}.json", json.dumps(contents, ensure_ascii=False, separators=(",", ":")).encode())
        written += self._write_card_pages(card_decks)
        self._write("state/deck-ids.json", json.dumps(sorted(self._deck_ids)).encode())
        self._write("state/duplicate-event-ids.json", json.dumps(sorted(self._duplicates)).encode())
        self._write("state/missing-deck-ids.json", json.dumps(sorted(self._missing)).encode())
        # Written last: the workflow uploads it last, so it never points at a snapshot not yet uploaded.
        index = {"schema": SCHEMA, "generated_at": self._stamp(), "formats": formats}
        self._write("index.json", json.dumps(index, indent=2).encode())
        return written

    def _write_card_pages(self, card_decks: Dict[str, FormatDecks]) -> List[str]:
        """Writes a page per card, skipping the ones whose numbers did not move."""
        pages, index = build_card_pages(card_decks, self._stamp())
        written = []
        hashes = {}
        for card_slug, page in pages.items():
            hashes[card_slug] = page_hash(page)
            if self._card_hashes.get(card_slug) == hashes[card_slug]:
                continue
            self._write(f"cards/{card_slug}.json", json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode())
            written.append(f"cards/{card_slug}.json")
        self._card_hashes = hashes
        self._write("cards/index.json", json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode())
        self._write("state/card-hashes.json", json.dumps(hashes, sort_keys=True).encode())
        log.info("Card pages: %d played, %d changed", len(pages), len(written))
        return ["cards/index.json"]

    def _snapshot(self, format: str) -> Dict[str, Any]:
        return self._snapshots.setdefault(format, {"meta": {}, "events": {}, "archetypes": {}})

    def _write(self, relative: str, body: bytes) -> None:
        path = self._root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def _stamp(self) -> str:
        return _iso(self._now)


def _duplicate_event_ids(events: Iterable[Dict[str, Any]]) -> Set[str]:
    """Events MTGGoldfish imported twice: same players at the same finishes, under a second id.

    The copy's name usually ends in " (1)". MTGO also runs several Challenges a
    day under one name, so only identical standings count as a duplicate, and
    only for events big enough that a match can't be chance.
    """
    kept: Dict[tuple, Dict[str, Any]] = {}
    duplicates: Set[str] = set()
    # The original is the one without a " (n)" suffix, or else the lower id.
    for event in sorted(events, key=lambda e: (bool(re.search(r" \(\d+\)$", e["event_name"])), int(e["event_id"]) if e["event_id"].isdigit() else 0)):
        if len(event["results"]) < 8:
            continue
        standings = (event["date"][:10], tuple((r["player"], r["finish"]) for r in event["results"]))
        if standings in kept:
            duplicates.add(event["event_id"])
        else:
            kept[standings] = event
    return duplicates


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {key: _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable(inner) for inner in value]
    return value
