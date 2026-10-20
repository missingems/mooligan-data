from mtgmeta import guide_builder
from mtgmeta.guide_builder import Candidate, fill, land_target, role, split_basics


def card(type_line, text=""):
    return {"type_line": type_line, "oracle_text": text}


def test_roles_follow_the_app_builders_order():
    assert role(card("Land", "{T}: Add {G}.")) == "land"
    assert role(card("Artifact Land", "{T}: Add {U}.")) == "land"
    assert role(card("Sorcery", "Destroy all creatures. They can't be regenerated.")) == "wipe"
    assert role(card("Sorcery", "Return all nonland permanents to their owners' hands.")) == "wipe"
    assert role(card("Instant", "Counter target spell.")) == "counter"
    assert role(card("Instant", "Exile target nonland permanent.")) == "removal"
    assert role(card("Instant", "Lightning Bolt deals 3 damage to any target.")) == "removal"
    # A target the builder does not know ("target player") is no removal.
    assert role(card("Sorcery", "Exile target player's graveyard.")) == "utility"
    assert role(card("Sorcery", "Search your library for a basic land card, put it onto the battlefield tapped.")) == "ramp"
    assert role(card("Artifact", "{T}: Add one mana of any color.")) == "ramp"
    assert role(card("Sorcery", "Search your library for a card, put it into your hand.")) == "tutor"
    assert role(card("Instant", "Draw three cards.")) == "draw"
    assert role(card("Instant", "Creatures you control gain indestructible until end of turn.")) == "protection"
    assert role(card("Enchantment", "Whenever a creature you control dies, each opponent loses 1 life.")) == "engine"
    assert role(card("Legendary Creature — Angel", "Flying")) == "payoff"
    assert role(card("Enchantment — Aura", "Enchanted creature gets +2/+2.")) == "utility"
    # A double-faced spell with a land on the back plays as its front.
    assert role(card("Sorcery // Land", "Return target creature card from your graveyard to your hand.")) == "utility"


def test_the_land_target_moves_with_ramp_and_the_curve():
    assert land_target(10, 3.0) == 36
    assert land_target(12, 3.0) == 35
    assert land_target(10, 3.6) == 37


def test_basics_follow_the_spells_pips_largest_remainder_first():
    spells = [Candidate("A", "a", "payoff", 1, mana_cost="{W}{W}"), Candidate("B", "b", "payoff", 1, mana_cost="{1}{U}"),
              Candidate("C", "c", "payoff", 1, mana_cost="{W/U}")]
    # W has 3 pips, U 2 of 5: 10 basics split 6 and 4.
    assert split_basics(10, spells, ["W", "U"]) == {"W": 6, "U": 4}
    assert split_basics(5, [], ["W", "U", "B"]) == {"W": 2, "U": 2, "B": 1}
    assert split_basics(5, spells, []) == {}


def pool(role_, count, score=0.5, mana_value=2.0):
    return [Candidate(f"{role_} {number}", f"{role_}-{number}", role_, score - number / 1000, mana_value=mana_value, mana_cost="{G}") for number in range(count)]


def test_a_fill_takes_each_aim_then_payoffs_then_lands_and_basics():
    candidates = pool("ramp", 15) + pool("draw", 15) + pool("removal", 6) + pool("counter", 6, 0.4) + pool("wipe", 5) + pool("protection", 5) \
        + pool("payoff", 60, 0.3) + pool("land", 20, 0.4, 0.0)
    deck = fill(candidates, slots=99, identity=["G"], nonbasic_lands=12)

    roles = {}
    for each in deck.cards:
        roles[each.role] = roles.get(each.role, 0) + 1
    assert (roles["ramp"], roles["draw"], roles["removal"] + roles["counter"], roles["wipe"], roles["protection"]) == (10, 10, 10, 3, 3)
    assert roles["land"] == 12 and deck.basics == {"G": 24} and deck.land_target == 36 and deck.size == 99


def test_a_fill_skips_what_the_rules_refuse_and_tops_up_a_short_pool():
    candidates = pool("ramp", 3) + pool("payoff", 30)
    seen = []
    deck = fill(candidates, slots=99, identity=["G"], allows=lambda name, deck: name != "payoff 0", on_add=seen.append)

    assert "payoff 0" not in {each.name for each in deck.cards} and len(seen) == len(deck.cards)
    assert deck.size == 99


def test_a_colourless_commander_plays_no_basics():
    deck = fill(pool("payoff", 70) + pool("land", 40, 0.4, 0.0), slots=99, identity=[])
    assert deck.basics == {} and len(deck.cards) == 99


def test_main_types_drop_supertypes():
    assert guide_builder.main_types("Legendary Snow Creature — Elf // Land") == {"Creature", "Land"}
