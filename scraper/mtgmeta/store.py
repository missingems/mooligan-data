"""Where scraped records go: Firestore in production, JSON files for a dry run."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from datetime import timezone
from typing import Iterable, List, Protocol, Set

from .models import ArchetypeHistory, ArchetypeResult, Deck, Event, Meta, to_document


class Store(Protocol):
    def save_meta(self, meta: Meta) -> None: ...
    def save_event(self, event: Event) -> None: ...
    def save_decks(self, decks: List[Deck]) -> None: ...
    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]: ...
    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]: ...
    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]: ...
    def save_archetype(self, history: ArchetypeHistory) -> None: ...


class FirestoreStore:
    def __init__(self, project: str = None) -> None:
        import firebase_admin
        from firebase_admin import firestore

        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={"projectId": project} if project else None)
        self._db = firestore.client()
        self._now = firestore.SERVER_TIMESTAMP

    def save_meta(self, meta: Meta) -> None:
        document = to_document(meta)
        document["last_updated"] = self._now
        self._db.collection("meta").document(meta.doc_id).set(document)

    def save_event(self, event: Event) -> None:
        document = to_document(event, drop=("event_id",))
        document["last_updated"] = self._now
        self._db.collection("events").document(event.event_id).set(document)

    def save_decks(self, decks: List[Deck]) -> None:
        for start in range(0, len(decks), 500):
            batch = self._db.batch()
            for deck in decks[start : start + 500]:
                document = to_document(deck, drop=("deck_id",))
                document["last_updated"] = self._now
                batch.set(self._db.collection("decks").document(deck.deck_id), document)
            batch.commit()

    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]:
        return self._existing("decks", deck_ids)

    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]:
        return self._existing("events", event_ids)

    def _existing(self, collection_name: str, doc_ids: Iterable[str]) -> Set[str]:
        ids = list(dict.fromkeys(doc_ids))
        found: Set[str] = set()
        collection = self._db.collection(collection_name)
        for start in range(0, len(ids), 100):
            refs = [collection.document(doc_id) for doc_id in ids[start : start + 100]]
            # Only ids are needed, so skip downloading each document's body.
            for snapshot in self._db.get_all(refs, field_paths=["format"]):
                if snapshot.exists:
                    found.add(snapshot.id)
        return found

    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]:
        snapshot = self._db.collection("archetypes").document(f"{format}_{archetype_id}").get()
        return _results_from_documents((snapshot.to_dict() or {}).get("results", []))

    def save_archetype(self, history: ArchetypeHistory) -> None:
        document = to_document(history)
        document["last_updated"] = self._now
        self._db.collection("archetypes").document(history.doc_id).set(document)


class JsonFileStore:
    """Writes each document as a JSON file under `root/<collection>/<id>.json`."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _write(self, collection: str, doc_id: str, document: dict) -> None:
        path = self._root / collection / f"{doc_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document["last_updated"] = datetime.now().astimezone()
        path.write_text(json.dumps(document, indent=2, default=_json_default, ensure_ascii=False))

    def save_meta(self, meta: Meta) -> None:
        self._write("meta", meta.doc_id, to_document(meta))

    def save_event(self, event: Event) -> None:
        self._write("events", event.event_id, to_document(event, drop=("event_id",)))

    def save_decks(self, decks: List[Deck]) -> None:
        for deck in decks:
            self._write("decks", deck.deck_id, to_document(deck, drop=("deck_id",)))

    def existing_deck_ids(self, deck_ids: Iterable[str]) -> Set[str]:
        return {deck_id for deck_id in deck_ids if (self._root / "decks" / f"{deck_id}.json").exists()}

    def existing_event_ids(self, event_ids: Iterable[str]) -> Set[str]:
        return {event_id for event_id in event_ids if (self._root / "events" / f"{event_id}.json").exists()}

    def load_archetype_results(self, format: str, archetype_id: str) -> List[ArchetypeResult]:
        path = self._root / "archetypes" / f"{format}_{archetype_id}.json"
        return _results_from_documents(json.loads(path.read_text())["results"]) if path.exists() else []

    def save_archetype(self, history: ArchetypeHistory) -> None:
        self._write("archetypes", history.doc_id, to_document(history))


def _results_from_documents(documents: List[dict]) -> List[ArchetypeResult]:
    results = []
    for document in documents:
        date = document["date"]
        if isinstance(date, str):
            date = datetime.fromisoformat(date)
        results.append(ArchetypeResult(**{**document, "date": date.astimezone(timezone.utc)}))
    return results


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialise {type(value).__name__}")
