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


def test_meta_reads_each_tiles_colours_and_key_cards():
    meta = parse_meta(fixture("metagame_modern.html"), "modern", "30d")
    by_id = {archetype.id: archetype for archetype in meta.archetypes}
    prowess = by_id["modern-izzet-prowess"]
    assert prowess.colors == ["U", "R"]  # "colors: blue red"
    assert prowess.key_cards == ["Cori-Steel Cutter", "Mishra's Bauble", "Dragon's Rage Channeler"]
    assert by_id["modern-eldrazi"].colors == ["G"]
    assert by_id["modern-eldrazi"].key_cards[1] == "Emrakul, the Promised End"  # commas stay in a name
    assert all(archetype.colors == sorted(archetype.colors, key="WUBRG".index) for archetype in meta.archetypes)


def _tile(pips: str, key_cards: str) -> str:
    return f"""
    <div class="archetype-tile">
      <div class="archetype-tile-title"><a href="/archetype/modern-x#paper">X</a></div>
      {pips}
      {key_cards}
      <div class="metagame-percentage"><div class="archetype-tile-statistic-value">1.5% <span>(12)</span></div></div>
    </div>"""


def test_colours_come_in_wubrg_order_whatever_the_label_order():
    pips = '<div class="manacost-container"><span class="manacost" aria-label="colors: green black white red blue"></span></div>'
    assert parse_meta(_tile(pips, ""), "modern", "30d").archetypes[0].colors == ["W", "U", "B", "R", "G"]


def test_colours_fall_back_to_the_pip_icons_and_colourless_is_empty():
    icons = '<div class="manacost-container"><span class="manacost"><i class="ms ms-g ms-cost"></i><i class="ms ms-w ms-cost"></i></span></div>'
    assert parse_meta(_tile(icons, ""), "modern", "30d").archetypes[0].colors == ["W", "G"]
    colourless = '<div class="manacost-container"><span class="manacost" aria-label="colors: colorless"><i class="ms ms-c ms-cost"></i></span></div>'
    assert parse_meta(_tile(colourless, ""), "modern", "30d").archetypes[0].colors == []


def test_a_tile_without_pips_or_key_cards_still_parses():
    archetype = parse_meta(_tile("", ""), "modern", "30d").archetypes[0]
    assert (archetype.id, archetype.percentage, archetype.colors, archetype.key_cards) == ("modern-x", 1.5, [], [])


def test_key_cards_stop_at_three():
    cards = "<div class='archetype-tile-description'><ul>" + "".join(f"<li>Card {n}</li>" for n in range(5)) + "</ul></div>"
    assert parse_meta(_tile("", cards), "modern", "30d").archetypes[0].key_cards == ["Card 0", "Card 1", "Card 2"]


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
    assert event_kind("Modern League 2026-09-22", "mtgo.com") == "mtgo_league"
    assert event_kind("3ª Etapa CLM Modern") == "other"


def test_a_league_is_a_magic_online_league_only_when_the_results_came_from_mtgo_com():
    from mtgmeta.parsing import event_kind

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
    from mtgmeta.parsing import event_kind, latin_lookalikes

    cyrillic_es = "\u0421"
    assert cyrillic_es != "C"
    assert event_kind(f"Modern Store {cyrillic_es}hampionship") == "store_championship"
    assert event_kind(f"Legacy {cyrillic_es}hallenge 32 2026-09-21") == "mtgo_challenge"
    assert event_kind("\u0420r\u043e Tour Seattle") == "pro_tour"  # Cyrillic er and o inside "Pro"
    assert event_kind("\uff33tore Championship") == "store_championship"  # a full-width S
    assert latin_lookalikes(f"Store {cyrillic_es}hampionship") == "Store Championship"
    assert latin_lookalikes("Étape 3 Бдзж") == "Étape 3 Бдзж"  # letters with no Latin twin are left alone


def test_the_tournament_page_gives_its_kind_and_source():
    event = parse_tournament(fixture("tournament_66753.html"), "66753", "modern")
    assert (event.kind, event.source) == ("mtgo_challenge", "mtgo.com")


def test_the_tournament_page_gives_each_results_colours_from_its_mana_cost_pips():
    event = parse_tournament(fixture("tournament_66753.html"), "66753", "modern")
    by_finish = {result.finish: result for result in event.results}
    assert by_finish["1st Place"].colors == ["G"]  # aria-label="mana cost: green"
    assert by_finish["3rd Place"].colors == ["W", "B", "G"]  # "white black green", in WUBRG order
    assert all(result.colors is None or result.colors == sorted(result.colors, key="WUBRG".index) for result in event.results)
    assert sum(1 for result in event.results if result.colors) >= 30


def _event_page(row_pips: str) -> str:
    return f"""
    <h2>Modern Challenge 32 2026-09-29</h2>
    <table class="table-tournament">
      <tr><td class="text-end">1st</td><td><a href="/deck/1">Affinity</a>{row_pips}</td><td><a href="/player/p">p</a></td></tr>
    </table>"""


def test_a_result_with_no_pips_has_no_colours_rather_than_an_empty_list():
    assert parse_tournament(_event_page(""), "1", "modern").results[0].colors is None
    empty = '<span aria-label="mana cost: " class="manacost"></span>'
    assert parse_tournament(_event_page(empty), "1", "modern").results[0].colors is None
    icons = '<span class="manacost"><i class="ms ms-r ms-cost"></i><i class="ms ms-u ms-cost"></i></span>'
    assert parse_tournament(_event_page(icons), "1", "modern").results[0].colors == ["U", "R"]  # the icons stand in for a missing label
