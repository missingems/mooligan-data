from pathlib import Path

import pytest

from mtgmeta.parsing import ParseError, event_kind, latin_lookalikes, parse_decklist, place

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_decklist_splits_main_and_sideboard():
    mainboard, sideboard = parse_decklist(fixture("mtgtop8_deck_909613.txt"))
    assert sum(card.quantity for card in mainboard) == 60
    assert sum(card.quantity for card in sideboard) == 15
    assert (mainboard[0].quantity, mainboard[0].card_name) == (1, "Spell Snare")
    assert (sideboard[0].quantity, sideboard[0].card_name) == (1, "Wrath of the Skies")


def test_decklist_accepts_a_sideboard_heading_and_no_sideboard():
    mainboard, sideboard = parse_decklist("4 Island\r\nSideboard\r\n2 Negate\r\n")
    assert [c.card_name for c in mainboard] == ["Island"] and [c.card_name for c in sideboard] == ["Negate"]
    assert parse_decklist("60 Island\n") == (parse_decklist("60 Island")[0], [])


def test_decklist_rejects_a_challenge_page():
    with pytest.raises(ParseError):
        parse_decklist("<!DOCTYPE html><html><head><title>Just a moment...</title>")


def test_event_kinds_come_from_the_name():
    assert event_kind("Pro Tour Marvel Super Heroes") == "pro_tour"
    assert event_kind("Regional Championship - SCG CON Baltimore - Saturday") == "regional_championship"
    assert event_kind("Modern RC Qualifier 2026-09-19") == "rcq"
    assert event_kind("$uper $unday RCQ - Modern - SCG CON Baltimore") == "rcq"
    assert event_kind("ACUP Clasificatorio Arcanis 2026") == "rcq"
    assert event_kind("Modern Store Championship") == "store_championship"
    assert event_kind("Modern Challenge 32 2026-09-21") == "mtgo_challenge"
    assert event_kind("Pauper RC Super Qualifier 2026-09-20") == "rcq"
    assert event_kind("Modern League 2026-09-22", "mtgo.com") == "mtgo_league"
    assert event_kind("3ª Etapa CLM Modern") == "other"


def test_a_league_is_a_magic_online_league_only_when_the_results_came_from_mtgo_com():
    assert event_kind("Modern League 2026-09-22", "mtgo.com") == "mtgo_league"
    # Paper leagues imported from melee.gg are local events, and a league with no known source can't be told.
    assert event_kind("Charlotte Legacy League Season 3 Week 13", "melee.gg") == "other"
    assert event_kind("1° TAPPA TIGULLIO LEGACY LEAGUE 2026/27", "melee.gg") == "other"
    assert event_kind("Modern League 2026-09-22") == "other"
    # The source decides only the League tier: the others still come from the name.
    assert event_kind("Modern Challenge 32 2026-09-21", "melee.gg") == "mtgo_challenge"
    assert event_kind("Legacy League Qualifier", "melee.gg") == "rcq"
    assert event_kind("Modern Store Championship", "melee.gg") == "store_championship"


def test_lookalike_cyrillic_letters_do_not_change_an_events_kind():
    cyrillic_es = "\u0421"
    assert cyrillic_es != "C"
    assert event_kind(f"Modern Store {cyrillic_es}hampionship") == "store_championship"
    assert event_kind(f"Legacy {cyrillic_es}hallenge 32 2026-09-21") == "mtgo_challenge"
    assert event_kind("\u0420r\u043e Tour Seattle") == "pro_tour"  # Cyrillic er and o inside "Pro"
    assert event_kind("\uff33tore Championship") == "store_championship"  # a full-width S
    assert latin_lookalikes(f"Store {cyrillic_es}hampionship") == "Store Championship"
    assert latin_lookalikes("Étape 3 Бдзж") == "Étape 3 Бдзж"  # letters with no Latin twin are left alone


def test_a_place_is_the_lowest_place_a_finish_can_stand_for():
    assert [place(finish) for finish in ("1st Place", "2nd Place", "3rd Place", "11th Place", "32nd Place")] == [1, 2, 3, 11, 32]
    assert [place(finish) for finish in ("Top 4", "Top 8", "Top 16", "Top 32")] == [3, 5, 9, 17]


def test_a_record_or_an_unknown_finish_has_no_place():
    assert [place(finish) for finish in ("5-0", "4-1", "", "Winner", "Top", "Top 8 Place")] == [None] * 6
