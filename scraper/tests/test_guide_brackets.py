from mtgmeta.guide_brackets import Pool, Rules, counts, deck_bracket, find_pool, read_estimate

ORACLE = {"id": "o-c", "bracket": 4, "cards": [{"name": "Thassa's Oracle"}, {"name": "Demonic Consultation"}]}
POOL = Pool(
    game_changers={"Rhystic Study", "Smothering Tithe", "Demonic Tutor", "Vampiric Tutor"},
    mass_land_denial={"Armageddon"},
    extra_turns={"Time Warp", "Temporal Manipulation", "Walk the Aeons"},
    combos=[ORACLE, {"id": "late", "bracket": 3, "cards": [{"name": "Atraxa"}, {"name": "Doubling Season"}]}],
)


def allowed(level, names):
    rules, deck = Rules(level, POOL, {"Atraxa"}), set()
    for name in names:
        if rules.allows(name, deck):
            rules.add(name)
            deck.add(name)
    return deck


def test_game_changers_none_at_one_and_two_and_three_at_three():
    changers = sorted(POOL.game_changers)
    assert allowed(2, changers) == set()
    assert len(allowed(3, changers)) == 3
    assert allowed(4, changers) == set(changers)


def test_mass_land_denial_only_from_four_and_extra_turns_a_few_from_two():
    assert "Armageddon" not in allowed(3, ["Armageddon"]) and "Armageddon" in allowed(4, ["Armageddon"])
    turns = ["Time Warp", "Temporal Manipulation", "Walk the Aeons"]
    assert allowed(1, turns) == set() and len(allowed(2, turns)) == 2 and len(allowed(4, turns)) == 3


def test_a_card_that_completes_a_combo_above_the_bracket_is_refused():
    assert allowed(3, ["Thassa's Oracle", "Demonic Consultation"]) == {"Thassa's Oracle"}
    assert allowed(4, ["Thassa's Oracle", "Demonic Consultation"]) == {"Thassa's Oracle", "Demonic Consultation"}
    # The commander is a piece too.
    assert allowed(2, ["Doubling Season"]) == set() and allowed(3, ["Doubling Season"]) == {"Doubling Season"}


def test_a_deck_is_at_the_lowest_bracket_whose_rules_it_keeps():
    assert deck_bracket({"Sol Ring"}, POOL, {"Atraxa"}) == 1
    assert deck_bracket({"Time Warp"}, POOL, {"Atraxa"}) == 2
    assert deck_bracket({"Rhystic Study", "Doubling Season"}, POOL, {"Atraxa"}) == 3
    assert deck_bracket(set(POOL.game_changers), POOL, {"Atraxa"}) == 4
    assert deck_bracket({"Armageddon"}, POOL, {"Atraxa"}) == 4
    assert deck_bracket({"Thassa's Oracle", "Demonic Consultation"}, POOL, {"Atraxa"}) == 4
    assert counts({"Armageddon", "Rhystic Study", "Time Warp"}, POOL) == {"game_changers": 1, "mass_land_denial": 1, "extra_turns": 1}


def test_spellbooks_estimate_flags_each_card():
    body = {"cards": [
        {"card": {"name": "Armageddon"}, "massLandDenial": True},
        {"card": {"name": "Time Warp"}, "extraTurn": True},
        {"card": {"name": "Mana Crypt"}, "gameChanger": True, "banned": True},
    ], "combos": []}
    pool = read_estimate(body)
    assert (pool.mass_land_denial, pool.extra_turns, pool.game_changers, pool.banned) == ({"Armageddon"}, {"Time Warp"}, {"Mana Crypt"}, {"Mana Crypt"})


def test_the_estimate_sends_the_commanders_apart_from_the_main_deck():
    sent = []
    find_pool(["Kraum", "Tymna"], ["Kraum", "Sol Ring"], lambda url, deck: sent.append((url, deck)) or {"cards": [], "combos": []})
    assert sent == [("https://backend.commanderspellbook.com/estimate-bracket",
                     {"commanders": [{"card": "Kraum"}, {"card": "Tymna"}], "main": [{"card": "Sol Ring"}]})]


def test_spellbook_failing_is_no_pool():
    def down(url, deck):
        raise OSError("down")

    assert find_pool(["Atraxa"], ["Sol Ring"], down) is None
