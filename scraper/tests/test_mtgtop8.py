from datetime import date
from pathlib import Path

import pytest

from mtgmeta.mtgtop8 import (
    Top8Deck,
    Top8Event,
    archetype_id,
    deck_path,
    event_path,
    finish,
    format_path,
    match_event,
    names_by_player,
    parse_event,
    parse_format_events,
    player_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="latin-1")


def test_paths():
    assert format_path("modern", 1) == "/format?f=MO&meta=51"
    assert format_path("duel_commander", 3) == "/format?f=EDH&meta=51&cp=3"
    assert event_path("93409", "modern") == "/event?e=93409&f=MO"
    assert deck_path("909613") == "/mtgo?d=909613"


def test_format_page_lists_the_twenty_dated_events_newest_first():
    listings, has_next = parse_format_events(fixture("mtgtop8_format_modern.html"))
    assert has_next
    assert len(listings) == 20
    assert (listings[0].event_id, listings[0].name, listings[0].date) == ("93409", "MTGO Challenge 32", date(2026, 11, 7))
    assert (listings[-1].event_id, listings[-1].date) == ("93118", date(2026, 11, 2))
    assert len({listing.event_id for listing in listings}) == 20
    assert [listing.date for listing in listings] == sorted((listing.date for listing in listings), reverse=True)


def test_format_page_skips_the_major_events_box_and_reads_paper_rows_once():
    modern, _ = parse_format_events(fixture("mtgtop8_format_modern.html"))
    assert "92597" not in {listing.event_id for listing in modern}
    listings, _ = parse_format_events(fixture("mtgtop8_format_pioneer.html"))
    assert len(listings) == len({listing.event_id for listing in listings}) == 16
    assert (listings[0].event_id, listings[0].name) == ("93312", "Mega Event - November")


def test_a_format_page_without_paging_links_has_no_next():
    listings, has_next = parse_format_events(fixture("mtgtop8_format_pioneer.html"))
    assert not has_next
    assert listings


def test_an_older_page_reads_its_events_list():
    listings, has_next = parse_format_events(fixture("mtgtop8_format_modern_p7.html"))
    assert has_next
    assert len(listings) == 20
    assert listings[-1].date == date(2026, 10, 12)


def test_duel_commander_page_reads():
    listings, _ = parse_format_events(fixture("mtgtop8_format_duel_commander.html"))
    assert len(listings) == 20
    assert listings[0].event_id == "93435"


def test_challenge_event_reads_its_decks():
    event = parse_event(fixture("mtgtop8_event_93409.html"), "93409")
    assert (event.name, event.date, event.players, event.source) == ("MTGO Challenge 32", date(2026, 11, 7), 47, "mtgo.com")
    assert len(event.decks) == 16
    assert event.decks[0] == Top8Deck("909613", "1", "Scepter Chant", "209", "peter780108")
    assert event.decks[-1].place == "16"


def test_league_event_has_no_player_count():
    event = parse_event(fixture("mtgtop8_event_93304.html"), "93304")
    assert (event.name, event.date, event.players, event.source) == ("MTGO League", date(2026, 11, 6), None, "mtgo.com")
    assert len(event.decks) == 8
    assert event.decks[0] == Top8Deck("908947", "1", "Amulet Titan", "348", "bamn20")


def test_paper_event_keeps_its_name_without_the_venue_and_its_place_ranges():
    event = parse_event(fixture("mtgtop8_event_93105.html"), "93105")
    assert (event.name, event.date, event.players, event.source) == ("Regional Championship - MIT Championship", date(2026, 11, 1), 83, "melee.gg")
    assert len(event.decks) == 16
    assert event.decks[0] == Top8Deck("907298", "1", "Rakdos Delirium", "918", "Wei_hao_huang")
    assert [deck.place for deck in event.decks[:6]] == ["1", "2", "3-4", "3-4", "5-8", "5-8"]
    assert event.decks[1].player == "Cheng Yu Chang"
    assert event.decks[-1].place == "9-16"


@pytest.mark.parametrize(
    "place, expected",
    [
        ("1", "1st Place"),
        ("2", "2nd Place"),
        ("3-4", "Top 4"),
        ("3", "Top 4"),
        ("4", "Top 4"),
        ("5-8", "Top 8"),
        ("5", "Top 8"),
        ("8", "Top 8"),
        ("9-16", "Top 16"),
        ("9", "Top 16"),
        ("16", "Top 16"),
        ("17-32", "Top 32"),
    ],
)
def test_finish_maps_places(place, expected):
    assert finish(place, False) == expected


def test_league_finish_is_five_oh_whatever_the_place():
    assert finish("3-4", True) == "5-0"
    assert finish("1", True) == "5-0"


def test_player_key_folds_case_accents_and_punctuation():
    assert player_key("Wei_hao_huang") == player_key("Wei_Hao_Huang") == "weihaohuang"
    assert player_key("Se?k-un Khó?") == player_key("Se̍k-un Khó͘") == "sekunkho"
    assert player_key("Cheng Yu Chang") == "chengyuchang"


def _event(event_id: str, day: date, players: list) -> Top8Event:
    decks = [Top8Deck(str(index), str(index + 1), "Scepter Chant", "209", player) for index, player in enumerate(players)]
    return Top8Event(event_id, "MTGO Challenge 32", day, len(players), "mtgo.com", decks)


def test_match_picks_the_event_sharing_the_players():
    real = parse_event(fixture("mtgtop8_event_93409.html"), "93409")
    other = _event("93441", date(2026, 11, 6), ["alpha", "bravo", "charlie", "delta"])
    names = [deck.player.upper() for deck in real.decks[:12]]
    assert match_event(names, date(2026, 11, 7), [other, real]) is real
    assert match_event(names, date(2026, 11, 7), [real, other]) is real


def test_match_needs_the_date_within_a_day_and_half_the_players():
    real = parse_event(fixture("mtgtop8_event_93409.html"), "93409")
    names = [deck.player for deck in real.decks]
    assert match_event(names, date(2026, 11, 8), [real]) is real
    assert match_event(names, date(2026, 11, 9), [real]) is None
    assert match_event(names[:7], date(2026, 11, 7), [real]) is None
    assert match_event(names[:8], date(2026, 11, 7), [real]) is real
    assert match_event(["nobody"], date(2026, 11, 7), [real]) is None


def test_names_by_player_drops_a_player_who_appears_twice():
    event = Top8Event(
        "1",
        "MTGO League",
        date(2026, 11, 6),
        None,
        "mtgo.com",
        [
            Top8Deck("1", "1", "Amulet Titan", "348", "Bamn20"),
            Top8Deck("2", "2", "Scepter Chant", "209", "Zed"),
            Top8Deck("3", "3", "Rakdos Delirium", "918", "bamn_20"),
        ],
    )
    assert names_by_player(event) == {"zed": "Scepter Chant"}


def test_names_by_player_reads_a_real_event():
    names = names_by_player(parse_event(fixture("mtgtop8_event_93409.html"), "93409"))
    assert names["peter780108"] == "Scepter Chant"


def test_archetype_id_slugs_the_name():
    assert archetype_id("modern", "Scepter Chant") == "modern-scepter-chant"
    assert archetype_id("modern", "UR Murktide") == "modern-ur-murktide"
    assert archetype_id("pioneer", "Rakdos  Café / Midrange!") == "pioneer-rakdos-cafe-midrange"
