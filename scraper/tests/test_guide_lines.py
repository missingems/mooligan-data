import json
from pathlib import Path

import pytest

from mtgmeta import guide_lines
from mtgmeta.guide_lines import deck_lines, outlet_kinds, resource_of, shown, style_lines, win_of

# Real oracle text, read from Scryfall's catalog on 21 October 2026.
CARDS = json.loads((Path(__file__).parent / "fixtures" / "outlet_cards.json").read_text())


@pytest.mark.parametrize("name, kinds", [
    ("Walking Ballista", {"mana": "Infinite damage"}),
    ("Crypt Rats", {"mana": "Infinite damage"}),
    ("Fireball", {"mana": "Infinite damage"}),
    ("Exsanguinate", {"mana": "Infinite lifeloss"}),
    ("Torment of Hailfire", {"mana": "Infinite lifeloss"}),
    ("Impact Tremors", {"creatures": "Infinite damage"}),
    ("Purphoros, God of the Forge", {"creatures": "Infinite damage"}),
    ("Mirkwood Bats", {"creatures": "Infinite lifeloss"}),
    ("Blood Artist", {"deaths": "Infinite lifeloss"}),
    ("Zulaport Cutthroat", {"deaths": "Infinite lifeloss"}),
    ("Goblin Bombardment", {"creatures": "Infinite damage", "deaths": "Infinite damage"}),
    ("Sanguine Bond", {"lifegain": "Infinite lifeloss"}),
    ("Aetherflux Reservoir", {"lifegain": "Infinite damage"}),
    ("Psychosis Crawler", {"draw": "Infinite lifeloss"}),
    ("Niv-Mizzet, Parun", {"draw": "Infinite damage"}),
    ("Thassa's Oracle", {"draw": "Win the game", "library": "Win the game"}),
    ("Laboratory Maniac", {"draw": "Win the game", "library": "Win the game"}),
    ("Guttersnipe", {"casts": "Infinite damage"}),
    ("Grapeshot", {"casts": "Infinite damage"}),
    # No outlets: a tap ability, a one-shot burn spell, mana, an enabler, a trigger on opponents' spells.
    ("Bolas's Citadel", {}),
    ("Lightning Bolt", {}),
    ("Sol Ring", {}),
    ("Hullbreaker Horror", {}),
    ("Exquisite Blood", {}),
    ("Kaervek the Merciless", {}),
    ("Rhystic Study", {}),
])
def test_each_outlet_is_read_from_its_rules_text(name, kinds):
    assert outlet_kinds(CARDS[name]) == kinds


def test_results_read_as_a_win_or_as_what_they_make():
    assert win_of(["Infinite colorless mana"]) is None and resource_of(["Infinite colorless mana"]) == "mana"
    assert win_of(["Infinite self-mill", "Near-infinite mill"]) is None and resource_of(["Infinite self-mill"]) == "library"
    assert win_of(["Infinite lifegain triggers", "Infinite lifeloss"]) == "Infinite lifeloss"
    assert win_of(["Target opponent loses the game"]) == "Win the game"
    assert win_of(["Exile all permanents opponents control"]) == "Exile every opponent's permanents"
    assert resource_of(["Infinite creature tokens"]) == "creatures" and resource_of(["Infinite looting"]) == "draw"


def combo(id, names, results, tag="P"):
    return {"id": id, "cards": [{"name": name, "oracle_id": name.lower()} for name in names], "results": results, "bracket_tag": tag}


HULL = combo("hull", ["Hullbreaker Horror", "Sol Ring"], ["Infinite colorless mana"], tag="E")
ORACLE = combo("oracle", ["Thassa's Oracle", "Demonic Consultation"], ["Win the game"], tag="R")
BOND = combo("bond", ["Sanguine Bond", "Exquisite Blood"], ["Infinite lifegain triggers", "Infinite lifeloss"], tag="S")
MILL = combo("mill", ["Hermit Druid", "Dread Return"], ["Infinite self-mill"])
CHAIN = combo("chain", ["Hermit Druid", "Dread Return", "Thassa's Oracle"], ["Win the game"])
LOOKUP = {**CARDS, "Demonic Consultation": {"mana_value": 1.0}, "Hermit Druid": {"mana_value": 2.0}, "Dread Return": {"mana_value": 4.0}}.get


def test_an_enabler_wins_through_a_chained_combo_or_an_outlet_in_the_deck_and_is_dropped_without_one():
    pool = [HULL, ORACLE, MILL, CHAIN, BOND]
    deck = {"Hullbreaker Horror", "Sol Ring", "Walking Ballista", "Hermit Druid", "Dread Return", "Thassa's Oracle", "Sanguine Bond", "Exquisite Blood"}
    lines = deck_lines([HULL, MILL, CHAIN, BOND], pool, deck, {"Jace"}, LOOKUP)
    by_id = {line.combo["id"]: line for line in lines}

    assert (by_id["bond"].outlet, by_id["bond"].win, by_id["bond"].tier) == ([], "Infinite lifeloss", 0)
    assert (by_id["mill"].outlet, by_id["mill"].outlet_combo, by_id["mill"].win) == (["Thassa's Oracle"], "chain", "Win the game")
    assert (by_id["hull"].outlet, by_id["hull"].win, by_id["hull"].speed) == (["Walking Ballista"], "Infinite damage", "slow")
    # Outright wins first, then chained lines, then card outlets.
    assert [line.combo["id"] for line in lines] == ["bond", "chain", "mill", "hull"]
    without = deck_lines([HULL], pool, deck - {"Walking Ballista"}, {"Jace"}, LOOKUP)
    assert without == []


def test_a_two_card_cheap_line_is_fast_and_a_ruthless_one_always_is():
    lines = deck_lines([ORACLE, BOND], [ORACLE, BOND], {"Thassa's Oracle", "Demonic Consultation", "Sanguine Bond", "Exquisite Blood"}, set(), LOOKUP)
    assert {line.combo["id"]: line.speed for line in lines} == {"oracle": "fast", "bond": "slow"}


def test_brackets_one_and_two_show_no_lines_three_slow_ones_and_four_fast_ones_first():
    lines = deck_lines([ORACLE, BOND], [ORACLE, BOND], {"Thassa's Oracle", "Demonic Consultation", "Sanguine Bond", "Exquisite Blood"}, set(), LOOKUP)
    assert shown(1, lines, set()) == [] and shown(2, lines, set()) == []
    assert [line.combo["id"] for line in shown(3, lines, set())] == ["bond"]
    assert [line.combo["id"] for line in shown(4, lines, set())] == ["oracle", "bond"]


def test_a_combo_shown_lower_down_repeats_only_when_nothing_else_fits():
    deck = {"Thassa's Oracle", "Demonic Consultation", "Sanguine Bond", "Exquisite Blood"}
    combos = {3: [BOND], 4: [BOND, ORACLE], 5: [BOND]}
    lines = style_lines([3, 4, 5], combos, {3: deck, 4: deck, 5: deck}, [ORACLE, BOND], set(), LOOKUP)
    assert [line["combo"] for line in lines[3]] == ["bond"]
    assert [line["combo"] for line in lines[4]] == ["oracle"]
    assert [line["combo"] for line in lines[5]] == ["bond"]
    assert lines[4][0] == {
        "combo": "oracle", "pieces": [{"name": "Thassa's Oracle", "oracle_id": "thassa's oracle"}, {"name": "Demonic Consultation", "oracle_id": "demonic consultation"}],
        "result": "Win the game", "outlet": [], "outlet_combo": None, "win": "Win the game", "speed": "fast",
    }


def test_the_commander_is_no_card_of_a_lines_count_or_mana_value():
    line = deck_lines([combo("solo", ["Jace", "Sol Ring"], ["Infinite colorless mana"])], [], {"Sol Ring", "Walking Ballista"}, {"Jace"}, LOOKUP)[0]
    assert (line.cards, line.mana_value) == (2, CARDS["Sol Ring"]["mana_value"] + CARDS["Walking Ballista"]["mana_value"])
    assert guide_lines.line_json(line, LOOKUP)["outlet"] == [{"name": "Walking Ballista", "oracle_id": CARDS["Walking Ballista"]["oracle_id"]}]


def test_a_line_reads_as_pieces_result_outlet_and_win():
    from mtgmeta.guide_text import line_text

    bond = {"pieces": [{"name": "Sanguine Bond"}, {"name": "Exquisite Blood"}], "result": "Infinite lifegain triggers", "outlet": [], "win": "Infinite lifeloss"}
    assert line_text(bond) == "Sanguine Bond and Exquisite Blood (Infinite lifegain triggers) for infinite lifeloss"
    hull = {"pieces": [{"name": "Hullbreaker Horror"}, {"name": "Sol Ring"}], "result": "Infinite colorless mana", "outlet": [{"name": "Walking Ballista"}], "win": "Infinite damage"}
    assert line_text(hull) == "Hullbreaker Horror and Sol Ring (Infinite colorless mana), cashed in by Walking Ballista for infinite damage"
    oracle = {"pieces": [{"name": "Thassa's Oracle"}, {"name": "Demonic Consultation"}], "result": "Win the game", "outlet": [], "win": "Win the game"}
    assert line_text(oracle) == "Thassa's Oracle and Demonic Consultation (Win the game)"
