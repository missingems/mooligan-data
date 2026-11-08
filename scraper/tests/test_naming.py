import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mtgmeta.models import Deck, DeckCard, Event, EventResult
from mtgmeta.mtgo import EventRef, parse_event
from mtgmeta.mtgtop8 import Top8Deck, Top8Event, parse_event as parse_top8
from mtgmeta.naming import COLORLESS, NamingStats, name_by_colors, name_by_lists, name_event, name_from_top8

FIXTURES = Path(__file__).parent / "fixtures"
CHALLENGE_SLUG = "modern-challenge-32-2026-11-0712857687"

CATALOG = {
    "lightning-bolt": {"name": "Lightning Bolt", "mana_cost": "{R}"},
    "goblin-guide": {"name": "Goblin Guide", "mana_cost": "{R}"},
    "lava-spike": {"name": "Lava Spike", "mana_cost": "{R}"},
    "counterspell": {"name": "Counterspell", "mana_cost": "{U}{U}"},
    "brazen-borrower": {"name": "Brazen Borrower", "mana_cost": "{1}{U}{U}"},
    "memnite": {"name": "Memnite", "mana_cost": "{0}"},
    "mountain": {"name": "Mountain", "land": True},
    "island": {"name": "Island", "land": True},
}

BURN = [(4, "Lightning Bolt"), (4, "Goblin Guide"), (4, "Lava Spike"), (20, "Mountain")]
CONTROL = [(4, "Counterspell"), (4, "Brazen Borrower"), (20, "Island")]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def deck(deck_id, board, player="Someone", archetype="", archetype_id=None, sideboard=()):
    return Deck(
        deck_id,
        player,
        archetype,
        [DeckCard(quantity, name) for quantity, name in board],
        [DeckCard(quantity, name) for quantity, name in sideboard],
        "modern",
        "mtgo-1",
        archetype_id,
    )


def result_of(item: Deck) -> EventResult:
    return EventResult(item.player, "", "5-0", item.deck_id)


def event_of(*decks: Deck) -> Event:
    return Event("mtgo-1", "Modern League", "modern", datetime(2026, 11, 7, tzinfo=timezone.utc), [result_of(item) for item in decks], "", "mtgo_league", "mtgo.com")


def real_event():
    ref = EventRef("12857687", CHALLENGE_SLUG, "modern", "Modern Challenge 32", datetime(2026, 11, 7, tzinfo=timezone.utc), "mtgo_challenge")
    event, decks = parse_event(fixture("mtgo_modern_challenge_32_12857687.html"), ref)
    return event, decks, parse_top8(fixture("mtgtop8_event_93409.html"), "93409")


def top8_of(*pairs) -> Top8Event:
    decks = [Top8Deck(str(index), str(index + 1), name, "1", player) for index, (player, name) in enumerate(pairs)]
    return Top8Event("1", "MTGO League", datetime(2026, 11, 7).date(), None, "mtgo.com", decks)


def top8_of_mtgo_players(decks, count=16) -> Top8Event:
    return top8_of(*[(item.player, f"Deck {index}") for index, item in enumerate(decks[:count])])


def test_top8_names_the_two_players_the_fixtures_share():
    event, decks, top8 = real_event()
    assert len(decks) == 32 and len(top8.decks) == 16
    assert name_from_top8(event, decks, top8, "modern") == 2
    peter = next(item for item in decks if item.player == "peter780108")
    assert (peter.archetype, peter.archetype_id) == ("Scepter Chant", "modern-scepter-chant")
    result = next(item for item in event.results if item.deck_id == peter.deck_id)
    assert (result.archetype, result.archetype_id) == ("Scepter Chant", "modern-scepter-chant")
    assert sorted(item.player for item in decks if item.archetype) == ["komattaman", "peter780108"]
    assert sorted(item.player for item in event.results if item.archetype) == ["komattaman", "peter780108"]


def test_top8_names_sixteen_of_thirty_two_decks_of_a_real_event():
    event, decks, _ = real_event()
    top8 = top8_of_mtgo_players(decks)
    assert name_from_top8(event, decks, top8, "modern") == 16
    named = [item for item in decks if item.archetype]
    assert len(named) == 16 and sum(1 for item in event.results if item.archetype) == 16
    assert all(item.archetype_id == f"modern-deck-{index}" for index, item in enumerate(named))
    assert all(not item.archetype and item.archetype_id is None for item in decks[16:])


def test_a_player_repeated_on_either_site_is_not_named():
    pilot, twin, other = deck("mtgo-1", BURN, "Bamn20"), deck("mtgo-2", BURN, "bamn_20"), deck("mtgo-3", BURN, "Zed")
    event = event_of(pilot, twin, other)
    top8 = top8_of(("bamn20", "Burn"), ("Zed", "Burn"))
    assert name_from_top8(event, [pilot, twin, other], top8, "modern") == 1
    assert (pilot.archetype, twin.archetype, other.archetype) == ("", "", "Burn")

    event = event_of(pilot, other)
    top8 = top8_of(("Bamn20", "Burn"), ("bamn_20", "Control"), ("Zed", "Burn"))
    assert name_from_top8(event, [pilot, other], top8, "modern") == 1
    assert pilot.archetype == ""


def test_an_unnamed_deck_takes_the_archetype_whose_list_it_matches():
    reference = [deck("a", BURN, archetype="Burn", archetype_id="modern-burn"), deck("b", CONTROL, archetype="Control", archetype_id="modern-control")]
    twin = deck("c", BURN)
    other = deck("d", CONTROL + [(4, "Memnite")])
    results = [result_of(twin), result_of(other)]
    assert name_by_lists([twin, other], reference, CATALOG, results=results) == 2
    assert (twin.archetype, twin.archetype_id) == ("Burn", "modern-burn")
    assert (other.archetype, other.archetype_id) == ("Control", "modern-control")
    assert (results[0].archetype, results[0].archetype_id) == ("Burn", "modern-burn")


def test_lands_do_not_count_toward_a_match():
    reference = [deck("a", BURN, archetype="Burn", archetype_id="modern-burn")]
    lands_only = deck("b", [(24, "Mountain")])
    assert name_by_lists([lands_only], reference, CATALOG) == 0
    assert lands_only.archetype == ""


def test_the_list_must_score_at_least_the_threshold():
    reference = [deck("a", [(4, "Lightning Bolt"), (3, "Goblin Guide")], archetype="Burn", archetype_id="modern-burn")]
    near = deck("b", [(4, "Lightning Bolt")])
    assert name_by_lists([near], reference, CATALOG, threshold=0.81) == 0
    assert near.archetype == ""
    assert name_by_lists([near], reference, CATALOG, threshold=0.8) == 1
    assert near.archetype_id == "modern-burn"


def test_the_archetype_scored_highest_wins():
    reference = [
        deck("a", [(4, "Lightning Bolt"), (4, "Goblin Guide")], archetype="Burn", archetype_id="modern-burn"),
        deck("b", [(4, "Lightning Bolt"), (4, "Goblin Guide"), (4, "Lava Spike"), (4, "Counterspell")], archetype="Prowess", archetype_id="modern-prowess"),
    ]
    target = deck("c", [(4, "Lightning Bolt"), (4, "Goblin Guide"), (4, "Lava Spike")])
    assert name_by_lists([target], reference, CATALOG, threshold=0.5) == 1
    assert target.archetype_id == "modern-prowess"


def test_reference_decks_without_an_id_name_nothing():
    target = deck("c", BURN)
    assert name_by_lists([target], [deck("a", BURN, archetype="UR")], CATALOG) == 0


def test_colours_come_in_wubrg_order_and_colourless_is_called_so():
    red_blue = deck("a", [(4, "Counterspell"), (4, "Lightning Bolt")])
    sideboard_only_red = deck("b", [(4, "Memnite")], sideboard=[(2, "Lightning Bolt")])
    colourless = deck("c", [(4, "Memnite"), (20, "Mountain")])
    results = [result_of(red_blue)]
    assert name_by_colors([red_blue, sideboard_only_red, colourless], CATALOG, results) == 3
    assert (red_blue.archetype, red_blue.archetype_id) == ("UR", None)
    assert sideboard_only_red.archetype == "R"
    assert colourless.archetype == COLORLESS
    assert results[0].archetype == "UR"


def test_a_deck_of_unknown_cards_is_other_and_not_counted():
    unknown = deck("a", [(4, "Not A Card")])
    assert name_by_colors([unknown], CATALOG) == 0
    assert (unknown.archetype, unknown.archetype_id) == ("Other", None)


def test_an_event_is_named_by_top8_then_lists_then_colours():
    named = deck("mtgo-1", BURN, "Zed")
    by_list = deck("mtgo-2", BURN, "Amy")
    by_colors = deck("mtgo-3", CONTROL, "Bo")
    event = event_of(named, by_list, by_colors)
    top8 = top8_of(("Zed", "Burn"))
    stats = name_event("modern", event, [named, by_list, by_colors], top8, [], CATALOG)
    assert stats == NamingStats(top8=1, lists=1, colors=1)
    assert [(item.archetype, item.archetype_id) for item in (named, by_list, by_colors)] == [
        ("Burn", "modern-burn"),
        ("Burn", "modern-burn"),
        ("U", None),
    ]
    assert [(item.archetype, item.archetype_id) for item in event.results] == [("Burn", "modern-burn"), ("Burn", "modern-burn"), ("U", None)]


def test_an_event_with_no_top8_copy_uses_the_reference_decks():
    reference = [deck("old", CONTROL, archetype="Control", archetype_id="modern-control")]
    mine = deck("mtgo-1", CONTROL)
    event = event_of(mine)
    stats = name_event("modern", event, [mine], None, reference, CATALOG)
    assert stats == NamingStats(top8=0, lists=1, colors=0)
    assert event.results[0].archetype_id == "modern-control"


def test_a_real_event_is_named_in_full():
    event, decks, _ = real_event()
    top8 = top8_of_mtgo_players(decks)
    stats = name_event("modern", event, decks, top8, [], CATALOG)
    assert stats.top8 == 16
    assert all(item.archetype for item in decks)
    results = {result.deck_id: result for result in event.results}
    assert all(results[item.deck_id].archetype == item.archetype for item in decks)
    assert all(results[item.deck_id].archetype_id == item.archetype_id for item in decks)
