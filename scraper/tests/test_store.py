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

    assert store.finish() == ["snapshots/modern.json", "explore.json", "cards/index.json"]  # pioneer has nothing, so no file

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

    # The index carries oracle ids, so a decklist name resolves to a card with one cached file.
    index = json.loads((tmp_path / "cards" / "index.json").read_text())
    assert index["cards"]["eldrazi-temple"]["oracle_id"] == "oracle-temple"

    # A card no tournament deck plays is still offered to EDHREC, and gets a page of its own.
    assert sorted(asked) == ["arcane-signet", "eldrazi-temple"]
    temple = json.loads((tmp_path / "cards" / "eldrazi-temple.json").read_text())
    assert temple["oracle_id"] == "oracle-temple" and "edh" not in temple
    signet = json.loads((tmp_path / "cards" / "arcane-signet.json").read_text())
    assert signet["oracle_id"] == "oracle-signet" and signet["formats"] == {} and signet["edh"]["decks"] == 9
    index = json.loads((tmp_path / "cards" / "index.json").read_text())
    assert index["cards"]["arcane-signet"] == {"name": "Arcane Signet", "formats": [], "edh": True, "oracle_id": "oracle-signet"}


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
    # A League is Magic Online's only when the source says so, and this one's isn't known yet.
    assert (published["kind"], published["source"]) == ("other", None)
    assert SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW).ignored_event_ids() == {"9"}


def test_finish_puts_the_kind_of_every_stored_event_right_by_the_current_rules(tmp_path):
    cyrillic_es = "\u0421"
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    for event_id, name, source, kind in (
        ("1", "Modern League 2026-09-20", "mtgo.com", "mtgo_league"),
        ("2", "Charlotte Legacy League Season 3 Week 13", "melee.gg", "mtgo_league"),  # stored when every League was Magic Online's
        ("3", f"Modern Store {cyrillic_es}hampionship", "melee.gg", "other"),  # stored when the lookalike hid "Championship"
        ("4", "Modern Challenge 32 2026-09-20", "mtgo.com", "mtgo_challenge"),
    ):
        first.save_event(Event(event_id, name, "modern", day("2026-09-20"), [EventResult("p", "Eldrazi", "5-0", "1")], "url", kind=kind, source=source))
    first.finish()

    # A second run reads them back, and publishes them under the rules as they are now.
    SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW).finish()
    published = json.loads((tmp_path / "snapshots" / "modern.json").read_text())["events"]
    assert {e["event_id"]: e["kind"] for e in published} == {"1": "mtgo_league", "2": "other", "3": "store_championship", "4": "mtgo_challenge"}


def test_a_results_colours_are_stored_only_when_the_event_page_showed_some(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    results = [
        EventResult("p1", "Eldrazi", "1st Place", "1", colors=["G"]),
        EventResult("p2", "Affinity", "2nd Place", "2"),  # no pips on the page
    ]
    store.save_event(Event("1", "Modern Challenge 32 2026-09-20", "modern", day("2026-09-20"), results, "url", kind="mtgo_challenge", source="mtgo.com"))
    store.finish()
    first, second = json.loads((tmp_path / "snapshots" / "modern.json").read_text())["events"][0]["results"]
    assert first["colors"] == ["G"]
    assert "colors" not in second  # absent, as in an event stored before they were read: unknown, not colourless


def test_decklist_entries_carry_their_oracle_id(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    catalog = {"eldrazi-temple": {"name": "Eldrazi Temple", "oracle_id": "oracle-temple"}}
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=catalog)
    store.save_decks([Deck("5", "p", "Eldrazi", [DeckCard(4, "Eldrazi Temple"), DeckCard(1, "Unknown Card")], [], "modern", "1")])
    deck = json.loads((tmp_path / "decks" / "5.json").read_text())
    assert [card["oracle_id"] for card in deck["mainboard"]] == ["oracle-temple", None]


def test_meta_key_cards_carry_their_oracle_id_and_null_when_unknown(tmp_path):
    catalog = {"ragavan-nimble-pilferer": {"name": "Ragavan, Nimble Pilferer", "oracle_id": "oracle-ragavan"}}
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=catalog)
    store.save_meta(Meta("modern", "30d", [
        Archetype("Boros Energy", 9.4, "modern-boros-energy", 648, colors=["W", "R"], key_cards=["Ragavan, Nimble Pilferer", "Made-up Card"]),
        Archetype("Bare", 1.0, "modern-bare"),
    ]))
    store.finish()
    archetypes = json.loads((tmp_path / "snapshots" / "modern.json").read_text())["meta"]["30d"]["archetypes"]
    assert archetypes[0]["colors"] == ["W", "R"]
    assert archetypes[0]["key_cards"] == [
        {"name": "Ragavan, Nimble Pilferer", "oracle_id": "oracle-ragavan"},
        {"name": "Made-up Card", "oracle_id": None},
    ]
    assert archetypes[0]["deck_count"] == 648 and "deck_id" in archetypes[0]  # the existing fields are unchanged
    assert (archetypes[1]["colors"], archetypes[1]["key_cards"]) == ([], [])


def test_explore_is_published_with_the_snapshots(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_meta(Meta("modern", "30d", [Archetype("Eldrazi", 9.4, "modern-eldrazi", 648)]))
    store.save_event(standings_event("9", "Modern Challenge 32 2026-09-22", 100))
    assert "explore.json" in store.finish()
    explore = json.loads((tmp_path / "explore.json").read_text())
    assert explore["generated_at"] == "2026-09-22T12:00:00Z"
    assert [f["format"] for f in explore["formats"]] == ["modern"]
    assert explore["formats"][0]["standings"][0]["id"] == "modern-eldrazi"
    assert explore["formats"][0]["recent_events"][0]["name"] == "Modern Challenge 32"


def test_a_run_of_one_format_keeps_the_others_in_explore(tmp_path):
    first = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW)
    first.save_meta(Meta("modern", "30d", [Archetype("Eldrazi", 9.4, "modern-eldrazi", 648)]))
    first.save_meta(Meta("pioneer", "30d", [Archetype("Rakdos", 12.0, "pioneer-rakdos", 90)]))
    first.finish()

    second = SnapshotStore(tmp_path, ["pioneer"], history_days=30, now=NOW)
    second.save_meta(Meta("pioneer", "30d", [Archetype("Rakdos Midrange", 13.0, "pioneer-rakdos", 95)]))
    second.finish()
    formats = {f["format"]: f for f in json.loads((tmp_path / "explore.json").read_text())["formats"]}
    assert set(formats) == {"modern", "pioneer"}  # standard has never been scraped, so it is left out
    assert formats["pioneer"]["standings"][0]["name"] == "Rakdos Midrange"
    assert formats["modern"]["standings"][0]["name"] == "Eldrazi"


def test_nothing_scraped_leaves_explore_unwritten(tmp_path):
    SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW).finish()
    assert not (tmp_path / "explore.json").exists()


def test_finish_writes_a_page_per_archetype_and_event_and_flags_the_decks_it_has(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    store = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW)
    store.save_meta(Meta("modern", "30d", [Archetype("Eldrazi", 9.4, "modern-eldrazi", 648, colors=["G"], key_cards=["Eldrazi Temple"])]))
    store.save_event(Event("7", "Modern Challenge 32 2026-09-21", "modern", day("2026-09-21"), [
        EventResult("p1", "Eldrazi", "1st Place", "5", "modern-eldrazi"),
        EventResult("p2", "Some Brew", "2nd Place", "6"),
    ], "https://www.mtggoldfish.com/tournament/7"))
    store.save_archetype(ArchetypeHistory("modern", "modern-eldrazi", "Eldrazi", "9", "Roy", [
        ArchetypeResult("5", day("2026-09-21"), "p1", "7", "Modern Challenge 32 2026-09-21", "1st Place"),
    ]))
    store.save_decks([Deck("5", "p1", "Eldrazi", [DeckCard(4, "Eldrazi Temple")], [], "modern", "7")])
    store.finish()

    archetype = json.loads((tmp_path / "archetypes" / "modern-eldrazi.json").read_text())
    assert (archetype["id"], archetype["format"], archetype["colors"], archetype["shares"]) == ("modern-eldrazi", "modern", ["G"], {"7d": None, "14d": None, "30d": 9.4})
    assert [(d["deck_id"], d["event_id"], d["event_name"], d["published"]) for d in archetype["decks"]] == [("5", "7", "Modern Challenge 32", True)]

    event = json.loads((tmp_path / "events" / "7.json").read_text())
    assert (event["id"], event["date"], event["format"]) == ("7", "2026-09-21", "modern")
    assert [(r["deck_id"], r["archetype_id"], r["published"], [c["name"] for c in r["key_cards"]]) for r in event["results"]] == [
        ("5", "modern-eldrazi", True, ["Eldrazi Temple"]),
        ("6", None, False, []),  # never downloaded, so a 404 on decks/6.json
    ]

    explore = json.loads((tmp_path / "explore.json").read_text())
    recent = explore["formats"][0]["recent_events"][0]
    assert (recent["id"], recent["result_count"], recent["lead"]["deck_id"]) == ("7", 2, "5")
    assert not (tmp_path / "archetypes" / "pioneer.json").exists() and not (tmp_path / "events" / "pioneer.json").exists()


def test_a_run_for_one_format_writes_no_pages_for_the_others(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_event(event("1", "2026-09-20"))
    store.finish()
    assert (tmp_path / "events" / "1.json").exists()
    assert not (tmp_path / "archetypes").exists()  # modern has no metagame yet


def _league_with_a_brew(store):
    """A League whose winner plays an archetype nobody tracks (no id), with its decklist stored."""
    from mtgmeta.models import Deck, DeckCard

    store.save_event(Event("7", "Modern League 2026-09-21", "modern", day("2026-09-21"), [
        EventResult("p1", "Gruul Aggro", "5-0", "5"),
        EventResult("p2", "Some Brew", "5-0", "6"),  # never downloaded
    ], "https://www.mtggoldfish.com/tournament/7"))
    store.save_decks([Deck("5", "p1", "Gruul Aggro", [DeckCard(4, "Mountain"), DeckCard(3, "Bonecrusher Giant"), DeckCard(4, "Kumano Faces Kakkazan")], [], "modern", "7")])


PREVIEW_CATALOG = {
    "mountain": {"name": "Mountain", "oracle_id": "oracle-mountain", "land": True},
    "bonecrusher-giant": {"name": "Bonecrusher Giant // Stomp", "oracle_id": "oracle-giant"},
    "kumano-faces-kakkazan": {"name": "Kumano Faces Kakkazan", "oracle_id": "oracle-kumano"},
}
PREVIEW = [{"name": "Kumano Faces Kakkazan", "oracle_id": "oracle-kumano"}, {"name": "Bonecrusher Giant", "oracle_id": "oracle-giant"}]


def test_an_untracked_deck_previews_its_own_cards_in_explore_and_the_event_page(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    _league_with_a_brew(store)
    store.finish()

    recent = json.loads((tmp_path / "explore.json").read_text())["formats"][0]["recent_events"][0]
    assert recent["lead"]["key_cards"] == PREVIEW  # no land, the deck's most played first
    assert [(r["deck_id"], r["key_cards"]) for r in recent["top"]] == [("5", PREVIEW), ("6", [])]  # deck 6 was never downloaded
    page = json.loads((tmp_path / "events" / "7.json").read_text())
    assert [(r["deck_id"], r["published"], r["key_cards"]) for r in page["results"]] == [("5", True, PREVIEW), ("6", False, [])]


def test_decks_published_by_earlier_runs_give_previews_too(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    _league_with_a_brew(first)
    first.finish()

    later = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    later._deck_cards["modern"] = {}  # this run never saw deck 5's cards; the bucket has them
    asked = []

    def fetch(ids):
        asked.extend(ids)
        return {"5": {"mainboard": [{"quantity": 4, "card_name": "Kumano Faces Kakkazan"}, {"quantity": 2, "card_name": "Mountain"}], "sideboard": []}}

    later.finish(fetch_decks=fetch)
    assert asked == ["5"]
    recent = json.loads((tmp_path / "explore.json").read_text())["formats"][0]["recent_events"][0]
    assert recent["lead"]["key_cards"] == [{"name": "Kumano Faces Kakkazan", "oracle_id": "oracle-kumano"}]


def test_a_run_of_one_format_keeps_the_previews_of_the_others_in_explore(tmp_path):
    first = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    _league_with_a_brew(first)
    first.finish()

    second = SnapshotStore(tmp_path, ["pioneer"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    second.save_meta(Meta("pioneer", "30d", [Archetype("Rakdos", 12.0, "pioneer-rakdos", 90)]))
    second.finish()
    formats = {f["format"]: f for f in json.loads((tmp_path / "explore.json").read_text())["formats"]}
    assert formats["modern"]["recent_events"][0]["lead"]["key_cards"] == PREVIEW  # from state/deck-cards/modern.json


def test_an_archetype_page_with_no_tile_cards_previews_its_featured_deck(tmp_path):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=PREVIEW_CATALOG)
    _league_with_a_brew(store)
    store.save_meta(Meta("modern", "30d", [Archetype("Gruul Aggro", 9.4, "modern-gruul-aggro", 648)]))  # the tile shows no key cards
    store.save_archetype(ArchetypeHistory("modern", "modern-gruul-aggro", "Gruul Aggro", "5", "Roy", [
        ArchetypeResult("5", day("2026-09-21"), "p1", "7", "Modern League 2026-09-21", "5-0"),
    ]))
    store.finish()

    page = json.loads((tmp_path / "archetypes" / "modern-gruul-aggro.json").read_text())
    assert page["key_cards"] == PREVIEW


POPULAR_CATALOG = {
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "oracle-bolt", "type_line": "Instant", "layout": "normal"},
    "mountain": {"name": "Mountain", "oracle_id": "oracle-mountain", "type_line": "Basic Land — Mountain", "layout": "normal", "land": True},
}


def _two_decks_in_a_league(store, format="modern"):
    """Two decks of a League on the 21st, which play Lightning Bolt and Mountain, and an archetype's result on the 22nd with one more."""
    from mtgmeta.models import Deck, DeckCard

    store.save_event(Event("7", "Modern League 2026-09-21", format, day("2026-09-21"), [
        EventResult("p1", "Gruul Aggro", "5-0", "5"),
        EventResult("p2", "Gruul Aggro", "5-0", "6"),
    ], "https://www.mtggoldfish.com/tournament/7"))
    store.save_archetype(ArchetypeHistory(format, "gruul-aggro", "Gruul Aggro", "5", "Roy", [
        ArchetypeResult("8", day("2026-09-22"), "p3", None, "A paper event", "1st Place"),
    ]))
    for deck_id in ("5", "6", "8"):
        store.save_decks([Deck(deck_id, "p", "Gruul Aggro", [DeckCard(4, "Lightning Bolt"), DeckCard(20, "Mountain")], [DeckCard(2, "Lightning Bolt")], format, "7")])


def test_popular_cards_are_published_for_each_format_built_from_its_stored_decks(tmp_path):
    store = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    _two_decks_in_a_league(store)
    store.save_event(Event("9", "Pioneer League 2026-09-20", "pioneer", day("2026-09-20"), [EventResult("p", "Rakdos", "5-0", "1")], "url"))  # no deck stored
    store.finish()

    modern = json.loads((tmp_path / "popular-cards" / "modern.json").read_text())
    assert (modern["schema"], modern["format"], modern["generated_at"]) == (1, "modern", "2026-09-22T12:00:00Z")
    week = modern["windows"]["7d"]
    assert week["deck_count"] == 3  # two of the league and the archetype's own result, the 22nd being today
    assert [(one["kind"], [(c["name"], c["decks"], c["copies"]) for c in one["cards"]]) for one in week["lists"]] == [
        ("all", [("Lightning Bolt", 3, 4.0)]),  # Mountain is a basic
        ("instant", [("Lightning Bolt", 3, 4.0)]),
        ("sideboard", [("Lightning Bolt", 3, 2.0)]),
    ]
    assert list(modern["windows"]) == ["7d", "14d", "30d"]
    assert json.loads((tmp_path / "popular-cards" / "pioneer.json").read_text())["windows"]["30d"] == {"deck_count": 0, "lists": []}
    breakouts = json.loads((tmp_path / "breakouts" / "modern.json").read_text())
    assert (breakouts["format"], breakouts["deck_count"], breakouts["baseline_deck_count"], breakouts["cards"]) == ("modern", 3, 0, [])


def test_a_run_of_one_format_leaves_the_popular_cards_of_the_others(tmp_path):
    first = SnapshotStore(tmp_path, ["modern", "pioneer"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    _two_decks_in_a_league(first)
    first.save_event(Event("8", "Pioneer League 2026-09-19", "pioneer", day("2026-09-19"), [EventResult("p", "Rakdos", "5-0", "2")], "url"))
    first.finish()
    before = (tmp_path / "popular-cards" / "modern.json").read_bytes()

    second = SnapshotStore(tmp_path, ["pioneer"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    second.save_event(Event("9", "Pioneer League 2026-09-20", "pioneer", day("2026-09-20"), [EventResult("p", "Rakdos", "5-0", "1")], "url"))
    second.finish()
    assert (tmp_path / "popular-cards" / "modern.json").read_bytes() == before
    assert (tmp_path / "popular-cards" / "pioneer.json").exists()


def test_popular_cards_count_the_decks_earlier_runs_stored_and_this_run_fetched(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    _two_decks_in_a_league(first)
    first.finish()

    later = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    later._deck_cards["modern"].pop("6")  # this run never saw deck 6's cards, and the bucket has them

    def fetch(ids):
        return {"6": {"mainboard": [{"quantity": 3, "card_name": "Lightning Bolt"}], "sideboard": []}}

    later.finish(fetch_decks=fetch)
    week = json.loads((tmp_path / "popular-cards" / "modern.json").read_text())["windows"]["7d"]
    assert week["lists"][0]["cards"][0]["copies"] == 3.7  # (4 + 3 + 4) / 3


def test_without_a_catalog_the_published_popular_cards_are_left_alone(tmp_path):
    first = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=POPULAR_CATALOG)
    _two_decks_in_a_league(first)
    first.finish()
    before = (tmp_path / "popular-cards" / "modern.json").read_bytes()

    later = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)  # Scryfall could not be read
    later.finish()
    assert (tmp_path / "popular-cards" / "modern.json").read_bytes() == before
    fresh = tmp_path / "other"
    SnapshotStore(fresh, ["modern"], history_days=30, now=NOW).finish()
    assert not (fresh / "popular-cards").exists()


def test_archetypes_that_play_one_deck_are_published_merged_and_stored_as_scraped(tmp_path):
    from mtgmeta.models import Deck, DeckCard

    catalog = {
        "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "oracle-bolt", "type_line": "Instant", "layout": "normal"},
        "lava-spike": {"name": "Lava Spike", "oracle_id": "oracle-spike", "type_line": "Sorcery", "layout": "normal"},
        "mountain": {"name": "Mountain", "oracle_id": "oracle-mountain", "type_line": "Basic Land — Mountain", "layout": "normal", "land": True},
    }
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=catalog)
    store.save_meta(Meta("modern", "7d", [Archetype("Burn", 6.0, "burn", 60, colors=["R"]), Archetype("Rakdos Burn", 1.5, "rakdos-burn", 15, colors=["B", "R"])]))
    store.save_event(Event("7", "Modern League 2026-09-21", "modern", day("2026-09-21"), [
        EventResult("p1", "Burn", "5-0", "1", "burn"),
        EventResult("p2", "Burn", "5-0", "2", "burn"),
        EventResult("p3", "Rakdos Burn", "5-0", "3", "rakdos-burn"),
        EventResult("p4", "RB", "5-0", "4"),
    ], "https://www.mtggoldfish.com/tournament/7"))
    for deck_id in ("1", "2", "3", "4"):
        store.save_decks([Deck(deck_id, "p", "Burn", [DeckCard(4, "Lightning Bolt"), DeckCard(4, "Lava Spike"), DeckCard(20, "Mountain")], [], "modern", "7")])
    store.finish()

    published = json.loads((tmp_path / "snapshots" / "modern.json").read_text())
    assert [(t["id"], t["percentage"], t["deck_count"], t["colors"]) for t in published["meta"]["7d"]["archetypes"]] == [("burn", 7.5, 75, ["R"])]
    assert published["merges"] == {"rakdos-burn": "burn"}
    assert [(r["archetype_id"], r["archetype"]) for r in published["events"][0]["results"]] == [("burn", "Burn")] * 4
    page = json.loads((tmp_path / "archetypes" / "burn.json").read_text())
    assert (page["cards"]["deck_count"], page["cards"]["list_count"]) == (4, 4)
    assert [(c["name"], c["share"], c["copies"]) for c in page["cards"]["main"]] == [("Mountain", 100.0, 20.0), ("Lava Spike", 100.0, 4.0), ("Lightning Bolt", 100.0, 4.0)]
    assert [c["name"] for c in page["hand"]] == ["Lava Spike", "Lightning Bolt"]
    assert json.loads((tmp_path / "archetypes" / "rakdos-burn.json").read_text())["merged_into"] == "burn"
    explore = json.loads((tmp_path / "explore.json").read_text())
    assert [row["id"] for row in explore["formats"][0]["standings_by_window"]["7d"]] == ["burn"]

    scraped = json.loads((tmp_path / "state" / "snapshots" / "modern.json").read_text())
    assert "merges" not in scraped and [t["id"] for t in scraped["meta"]["7d"]["archetypes"]] == ["burn", "rakdos-burn"]
    again = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW, catalog=catalog)
    again.finish()
    assert json.loads((tmp_path / "snapshots" / "modern.json").read_text())["meta"] == published["meta"]
    assert [r["archetype_id"] for r in json.loads((tmp_path / "state" / "snapshots" / "modern.json").read_text())["events"][0]["results"]] == ["burn", "burn", "rakdos-burn", None]
