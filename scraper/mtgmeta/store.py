"""The published data set: one snapshot per format, one file per deck, and an index.

The directory mirrors the R2 bucket. The workflow downloads the previous
snapshots and deck id list into it, the scrape updates it, and `finish()`
writes the files the workflow uploads (see docs/data-format.md).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Set

from .models import ArchetypeHistory, ArchetypeResult, Deck, Event, Meta, to_document

SCHEMA = 1


class Store(Protocol):
    def save_meta(self, meta: Meta) -> None: ...
    def save_event(self, event: Event) -> None: ...
    def save_decks(self, decks: List[Deck]) -> None: ...
    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]: ...
    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]: ...
    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]: ...
    def save_archetype(self, history: ArchetypeHistory) -> None: ...


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

    def save_archetype(self, history: ArchetypeHistory) -> None:
        document = _jsonable(to_document(history, drop=("format",)))
        document["last_updated"] = self._stamp()
        self._snapshot(history.format)["archetypes"][history.archetype_id] = document

    # ---- Publishing

    def finish(self) -> List[str]:
        """Writes the snapshots, deck id list and index, and returns the snapshot paths written."""
        written = []
        formats = {}
        for format, snapshot in self._snapshots.items():
            events = sorted(
                (event for event in snapshot["events"].values() if _parse(event["date"]) >= self._cutoff),
                key=lambda event: (event["date"], event["event_id"]),
                reverse=True,
            )
            # Archetypes no longer in the metagame drop out once their results age past the window.
            archetypes = {
                archetype_id: archetype
                for archetype_id, archetype in sorted(snapshot["archetypes"].items())
                if any(_parse(result["date"]) >= self._cutoff for result in archetype["results"])
            }
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
        self._write("state/deck-ids.json", json.dumps(sorted(self._deck_ids)).encode())
        # Written last: the workflow uploads it last, so it never points at a snapshot not yet uploaded.
        index = {"schema": SCHEMA, "generated_at": self._stamp(), "formats": formats}
        self._write("index.json", json.dumps(index, indent=2).encode())
        return written

    def _snapshot(self, format: str) -> Dict[str, Any]:
        return self._snapshots.setdefault(format, {"meta": {}, "events": {}, "archetypes": {}})

    def _write(self, relative: str, body: bytes) -> None:
        path = self._root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def _stamp(self) -> str:
        return _iso(self._now)


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
