from datetime import datetime, timezone
from pathlib import Path

import pytest

from mtgmeta.parsing import (
    ParseError,
    parse_archetype,
    parse_decklist,
    parse_meta,
    parse_tournament,
    parse_tournament_list,
    selected_period,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_meta_reads_each_archetype_tile():
    meta = parse_meta(fixture("metagame_modern.html"), "modern", "30d")
    assert meta.doc_id == "modern_30d"
    assert len(meta.archetypes) == 6
    first = meta.archetypes[0]
    assert (first.name, first.id, first.percentage, first.deck_count) == ("Izzet Prowess", "modern-izzet-prowess", 9.8, 675)
    assert all(0 < archetype.percentage < 100 for archetype in meta.archetypes)


def test_meta_page_reports_its_window():
    assert selected_period(fixture("metagame_modern.html")) == "30"


def test_meta_without_tiles_is_an_error():
    with pytest.raises(ParseError):
        parse_meta("<html><title>Just a moment...</title></html>", "modern", "30d")


def test_tournament_list_reads_ids_names_and_dates():
    events = parse_tournament_list(fixture("tournaments_modern.html"))
    assert [event.event_id for event in events] == ["66764", "66753", "66742"]
    assert events[1].event_name == "Modern Challenge 32 2026-09-21"
    assert events[1].date == datetime(2026, 9, 21, tzinfo=timezone.utc)


def test_tournament_reads_every_placing():
    event = parse_tournament(fixture("tournament_66753.html"), "66753", "modern")
    assert event.event_name == "Modern Challenge 32 2026-09-21"
    assert event.date == datetime(2026, 9, 21, tzinfo=timezone.utc)
    assert len(event.results) == 32
    first = event.results[0]
    assert (first.player, first.archetype, first.finish, first.deck_id) == ("ashame", "Eldrazi Ramp", "1st Place", "7966104")
    assert len({result.deck_id for result in event.results}) == 32


def test_league_records_are_kept_as_records():
    html = """
    <h2>Modern League 2026-09-22</h2><p>Date: 2026-09-22</p>
    <table class="table-tournament">
      <tr><td>5 - 0</td><td><a href="/deck/1">UR</a></td><td><a href="/player/x">Isael</a></td></tr>
    </table>"""
    event = parse_tournament(html, "1", "modern")
    assert event.results[0].finish == "5-0"


def test_decklist_splits_main_and_sideboard():
    mainboard, sideboard = parse_decklist(fixture("deck_7967072.txt"))
    assert sum(card.quantity for card in mainboard) == 60
    assert sum(card.quantity for card in sideboard) == 15
    assert (mainboard[0].quantity, mainboard[0].card_name) == (1, "Arid Mesa")
    assert (sideboard[0].quantity, sideboard[0].card_name) == (4, "Consign to Memory")


def test_decklist_accepts_a_sideboard_heading_and_no_sideboard():
    mainboard, sideboard = parse_decklist("4 Island\r\nSideboard\r\n2 Negate\r\n")
    assert [c.card_name for c in mainboard] == ["Island"] and [c.card_name for c in sideboard] == ["Negate"]
    assert parse_decklist("60 Island\n") == (parse_decklist("60 Island")[0], [])


def test_decklist_rejects_a_challenge_page():
    with pytest.raises(ParseError):
        parse_decklist("<!DOCTYPE html><html><head><title>Just a moment...</title>")


def test_archetype_page_names_its_featured_deck():
    deck = parse_archetype(fixture("archetype_modern_izzet_prowess.html"), "modern-izzet-prowess")
    assert (deck.deck_id, deck.player) == ("7945486", "Roy Varney")


def test_archetype_page_without_a_deck_is_an_error():
    with pytest.raises(ParseError):
        parse_archetype("<h1 class='title'>Izzet Prowess</h1>", "modern-izzet-prowess")


def test_search_results_list_events_with_their_decklist_counts():
    from mtgmeta.parsing import parse_tournament_search

    events, has_next = parse_tournament_search(fixture("tournament_search_modern_p2.html"))
    assert has_next and len(events) == 6
    assert events[0].decklists is not None and events[0].date is not None
    assert all(event.event_id.isdigit() for event in events)


def test_event_kinds_come_from_the_name():
    from mtgmeta.parsing import event_kind

    assert event_kind("Pro Tour Marvel Super Heroes") == "pro_tour"
    assert event_kind("Regional Championship - SCG CON Baltimore - Saturday") == "regional_championship"
    assert event_kind("Modern RC Qualifier 2026-09-19") == "rcq"
    assert event_kind("$uper $unday RCQ - Modern - SCG CON Baltimore") == "rcq"
    assert event_kind("ACUP Clasificatorio Arcanis 2026") == "rcq"
    assert event_kind("Modern Store Championship") == "store_championship"
    assert event_kind("Modern Challenge 32 2026-09-21") == "mtgo_challenge"
    assert event_kind("Pauper RC Super Qualifier 2026-09-20") == "rcq"
    assert event_kind("Modern League 2026-09-22") == "mtgo_league"
    assert event_kind("3ª Etapa CLM Modern") == "other"


def test_the_tournament_page_gives_its_kind_and_source():
    event = parse_tournament(fixture("tournament_66753.html"), "66753", "modern")
    assert (event.kind, event.source) == ("mtgo_challenge", "mtgo.com")
