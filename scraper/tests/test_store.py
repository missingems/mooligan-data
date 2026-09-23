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

    assert store.finish() == ["snapshots/modern.json", "cards/index.json"]  # pioneer has nothing, so no file

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


def standings_event(event_id, name, deck_offset, players=None):
    players = players or [f"player{i}" for i in range(32)]
    results = [EventResult(p, "Eldrazi", f"{i + 1}th Place", str(deck_offset + i)) for i, p in enumerate(players)]
    return Event(event_id, name, "modern", day("2026-09-22"), results, "url")


def test_events_imported_twice_are_published_once(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_event(standings_event("66776", "Modern Challenge 32 2026-09-22 (1)", 2000))
    store.save_event(standings_event("66774", "Modern Challenge 32 2026-09-22", 1000))
    # A different Challenge the same day, under the same name pattern, stays.
    store.save_event(standings_event("66780", "Modern Challenge 32 2026-09-22 (2)", 3000, [f"other{i}" for i in range(32)]))
    store.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", None, None, [
        ArchetypeResult("2000", day("2026-09-22"), "player0", "66776", "Modern Challenge 32 2026-09-22 (1)", "1th Place"),
        ArchetypeResult("1000", day("2026-09-22"), "player0", "66774", "Modern Challenge 32 2026-09-22", "1th Place"),
    ]))
    store.finish()
    snapshot = json.loads((tmp_path / "snapshots" / "modern.json").read_text())
    assert sorted(e["event_id"] for e in snapshot["events"]) == ["66774", "66780"]
    assert [r["event_id"] for r in snapshot["archetypes"]["modern-eldrazi"]["results"]] == ["66774"]


def test_duplicates_are_remembered_for_later_runs(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    first.save_event(standings_event("66776", "Modern Challenge 32 2026-09-22 (1)", 2000))
    first.save_event(standings_event("66774", "Modern Challenge 32 2026-09-22", 1000))
    first.finish()
    assert SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW).ignored_event_ids() == {"66776"}


def test_published_decks_fill_in_the_card_pages(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    first.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", None, None, [
        ArchetypeResult("5", day("2026-09-20"), "p", "1", "Modern League", "5-0"),
    ]))
    first.save_decks([Deck("5", "p", "Eldrazi", [DeckCard(4, "Eldrazi Temple")], [], "modern", "1")])
    first.finish()

    # A later run knows deck 5 is stored but never saw its cards; the bucket has them.
    later = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    later._deck_cards["modern"] = {}
    asked = []

    def fetch(ids):
        asked.extend(ids)
        return {"5": {"mainboard": [{"quantity": 4, "card_name": "Eldrazi Temple"}], "sideboard": []}}

    later.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", None, None, [
        ArchetypeResult("5", day("2026-09-20"), "p", "1", "Modern League", "5-0"),
    ]))
    later.finish(fetch_decks=fetch)

    assert asked == ["5"]
    page = json.loads((tmp_path / "cards" / "eldrazi-temple.json").read_text())
    assert page["formats"]["modern"]["of_decks"] == 1


def test_the_catalog_gives_pages_their_oracle_id_and_widens_the_commander_rotation(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", None, None, [
        ArchetypeResult("5", day("2026-09-20"), "p", "1", "Modern League", "5-0"),
    ]))
    store.save_decks([Deck("5", "p", "Eldrazi", [DeckCard(4, "Eldrazi Temple")], [], "modern", "1")])
    catalog = {
        "eldrazi-temple": {"name": "Eldrazi Temple", "oracle_id": "oracle-temple"},
        "arcane-signet": {"name": "Arcane Signet", "oracle_id": "oracle-signet"},
    }
    asked = []

    def fetch_edh(slugs):
        asked.extend(slugs)
        return {"arcane-signet": {"decks": 9, "of_decks": 10, "salt": None, "url": "u", "commanders": []}}

    store.finish(fetch_edh=fetch_edh, edh_limit=5, catalog=catalog)

    # A card no tournament deck plays is still offered to EDHREC, and gets a page of its own.
    assert sorted(asked) == ["arcane-signet", "eldrazi-temple"]
    temple = json.loads((tmp_path / "cards" / "eldrazi-temple.json").read_text())
    assert temple["oracle_id"] == "oracle-temple" and "edh" not in temple
    signet = json.loads((tmp_path / "cards" / "arcane-signet.json").read_text())
    assert signet["oracle_id"] == "oracle-signet" and signet["formats"] == {} and signet["edh"]["decks"] == 9
    index = json.loads((tmp_path / "cards" / "index.json").read_text())
    assert index["cards"]["arcane-signet"] == {"name": "Arcane Signet", "formats": [], "edh": True}


def test_commander_pages_are_published_for_the_commanders_cards_name(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", None, None, [
        ArchetypeResult("5", day("2026-09-20"), "p", "1", "Modern League", "5-0"),
    ]))
    store.save_decks([Deck("5", "p", "Eldrazi", [DeckCard(4, "Sol Ring")], [], "modern", "1")])

    def fetch_edh(slugs):
        return {"sol-ring": {"decks": 8, "of_decks": 10, "salt": 1.5, "url": "u", "commanders": [
            {"name": "Vivi Ornitier", "slug": "vivi-ornitier", "decks": 5, "of_decks": 7},
        ]}}

    def fetch_commanders(slugs):
        assert slugs == ["vivi-ornitier"]
        return {"vivi-ornitier": {
            "name": "Vivi Ornitier", "slug": "vivi-ornitier", "decks": 40779, "salt": 2.81, "url": "u",
            "sections": [{"tag": "topcards", "header": "Top Cards", "cards": [
                {"name": "Brainstorm", "decks": 28385, "of_decks": 40779, "synergy": 0.28}]}],
            "average_deck": [{"header": "Lands", "cards": ["Island"]}],
        }}

    store.finish(fetch_edh=fetch_edh, edh_limit=5, fetch_commanders=fetch_commanders, commander_limit=5)

    page = json.loads((tmp_path / "edh" / "commanders" / "vivi-ornitier.json").read_text())
    assert page["decks"] == 40779 and page["sections"][0]["cards"][0]["name"] == "Brainstorm"
    assert page["average_deck"] == [{"header": "Lands", "cards": ["Island"]}]
    index = json.loads((tmp_path / "edh" / "commanders" / "index.json").read_text())
    assert index["commanders"]["vivi-ornitier"] == {"name": "Vivi Ornitier", "decks": 40779}


def test_stored_events_get_their_tier_at_publish_and_report_a_missing_source(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    first.save_event(event("1", "2026-09-20"))
    first.finish()
    # Strip what an older run would not have stored.
    path = tmp_path / "snapshots" / "modern.json"
    stored = json.loads(path.read_text())
    for e in stored["events"]:
        e.pop("kind"); e.pop("source")
    path.write_text(json.dumps(stored))

    second = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    assert second.events_missing_source("modern") == ["1"]
    second.mark_empty_events(["9"])
    second.finish()
    published = json.loads(path.read_text())["events"][0]
    assert (published["kind"], published["source"]) == ("mtgo_league", None)
    assert SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW).ignored_event_ids() == {"9"}
