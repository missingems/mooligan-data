import hashlib
import json
from datetime import datetime, timezone

from mtgmeta.models import ArchetypeHistory, ArchetypeResult, Event, EventResult, Meta, Archetype
from mtgmeta.store import SnapshotStore

NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)


def day(date):
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def event(event_id, date):
    return Event(event_id, f"Modern League {date}", "modern", day(date), [EventResult("p", "Eldrazi", "5-0", "1")], "url")


def test_finish_publishes_snapshot_index_and_deck_ids(tmp_path):
    store = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW)
    store.save_meta(Meta("modern", "30d", [Archetype("Eldrazi", 9.4, "modern-eldrazi", 648)]))
    store.save_event(event("2", "2026-09-21"))
    store.save_event(event("1", "2026-09-20"))

    assert store.finish() == ["snapshots/modern.json"]  # pioneer has nothing, so no file

    body = (tmp_path / "snapshots" / "modern.json").read_bytes()
    snapshot = json.loads(body)
    assert snapshot["schema"] == 1 and snapshot["format"] == "modern"
    assert snapshot["generated_at"] == "2026-09-22T12:00:00Z"
    assert snapshot["meta"]["30d"]["archetypes"][0]["id"] == "modern-eldrazi"
    assert [e["event_id"] for e in snapshot["events"]] == ["2", "1"]
    assert snapshot["events"][0]["date"] == "2026-09-21T00:00:00Z"

    index = json.loads((tmp_path / "index.json").read_text())
    assert index["formats"]["modern"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert index["formats"]["modern"]["events"] == 2
    assert "pioneer" not in index["formats"]


def test_a_new_run_loads_what_the_last_one_published(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    first.save_event(event("1", "2026-09-20"))
    first.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", "9", "Roy", [
        ArchetypeResult("5", day("2026-09-20"), "p", "1", "Modern League", "5-0"),
    ]))
    from mtgmeta.models import Deck, DeckCard
    first.save_decks([Deck("5", "p", "Eldrazi", [DeckCard(4, "Eldrazi Temple")], [], "modern", "1")])
    first.finish()

    second = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    assert second.existing_deck_ids(["5", "6"]) == {"5"}
    assert second.existing_event_ids(["1", "2"]) == {"1"}
    results = second.load_archetype_results("modern", "modern-eldrazi")
    assert results[0].date == day("2026-09-20") and results[0].event_id == "1"


def test_events_and_archetypes_past_the_window_drop_out(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_event(event("old", "2026-08-01"))
    store.save_event(event("new", "2026-09-20"))
    store.save_archetype(ArchetypeHistory("modern", "gone", "Gone", None, None, [
        ArchetypeResult("7", day("2026-08-01"), "p", "old", "Old", "5-0"),
    ]))
    store.finish()
    snapshot = json.loads((tmp_path / "snapshots" / "modern.json").read_text())
    assert [e["event_id"] for e in snapshot["events"]] == ["new"]
    assert snapshot["archetypes"] == {}
