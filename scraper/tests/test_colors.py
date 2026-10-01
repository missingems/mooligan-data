import pytest

from mtgmeta.colors import color_weights, deck_colors, mana_symbols

# What card_catalog keeps: "land" for a land, and the mana cost of a card that has one.
CATALOG = {
    "lightning-bolt": {"name": "Lightning Bolt", "mana_cost": "{R}"},
    "path-to-exile": {"name": "Path to Exile", "mana_cost": "{W}"},
    "counterspell": {"name": "Counterspell", "mana_cost": "{U}{U}"},
    "dismember": {"name": "Dismember", "mana_cost": "{1}{B/P}{B/P}"},
    "burning-tree-emissary": {"name": "Burning-Tree Emissary", "mana_cost": "{R/G}{R/G}"},
    "boros-reckoner": {"name": "Boros Reckoner", "mana_cost": "{2}{R/W}{R/W}{R/W}"},
    "kitchen-finks": {"name": "Kitchen Finks", "mana_cost": "{1}{G/W}{G/W}"},
    "spectral-procession": {"name": "Spectral Procession", "mana_cost": "{2/W}{2/W}{2/W}"},
    "thought-knot-seer": {"name": "Thought-Knot Seer", "mana_cost": "{3}{C}"},
    "walking-ballista": {"name": "Walking Ballista", "mana_cost": "{X}{X}"},
    "sol-ring": {"name": "Sol Ring", "mana_cost": "{1}"},
    "ornithopter": {"name": "Ornithopter", "mana_cost": "{0}"},
    "wear": {"name": "Wear // Tear", "mana_cost": "{1}{R} // {W}"},
    "bonecrusher-giant": {"name": "Bonecrusher Giant // Stomp", "mana_cost": "{2}{R} // {1}{R}"},
    "delver-of-secrets": {"name": "Delver of Secrets // Insectile Aberration", "mana_cost": "{U}"},
    "frost-titan": {"name": "Frost Titan", "mana_cost": "{4}{U}{U}"},
    "mountain": {"name": "Mountain", "land": True},
    "arid-mesa": {"name": "Arid Mesa", "land": True},
    # A land has no cost, and a spell with a land on its back has one.
    "shatterskull-smashing": {"name": "Shatterskull Smashing // Shatterskull, the Hammer Pass", "mana_cost": "{X}{R}{R}"},
}


def test_each_symbol_gives_the_colours_it_can_be_paid_with():
    assert mana_symbols("{1}{R}{R}") == [["R"], ["R"]]
    assert mana_symbols("{W/U}{B}") == [["W", "U"], ["B"]]  # hybrid: either colour
    assert mana_symbols("{2/W}{2/W}") == [["W"], ["W"]]  # two generic or one white: the colour it names
    assert mana_symbols("{C}{G}") == [["C"], ["G"]]  # colourless is a symbol of its own
    assert mana_symbols("{R/G/P}") == []


def test_phyrexian_generic_x_and_snow_symbols_are_skipped():
    assert mana_symbols("{1}{B/P}{B/P}") == []
    assert mana_symbols("{G/W/P}{R/P}") == []  # hybrid Phyrexian too
    assert mana_symbols("{X}{X}{3}{0}{S}{10}") == []
    assert mana_symbols("{2}{U/P}{U}") == [["U"]]  # only the plain one counts
    assert mana_symbols("") == [] and mana_symbols(None) == []


def test_a_split_or_adventure_cost_counts_both_halves():
    assert mana_symbols("{1}{R} // {W}") == [["R"], ["W"]]
    assert mana_symbols("{2}{R} // {1}{R}") == [["R"], ["R"]]


def test_a_deck_is_the_colours_of_its_one_colour_symbols_in_wubrg_order():
    deck = [[4, "Lightning Bolt"], [4, "Counterspell"], [4, "Path to Exile"], [20, "Mountain"]]
    assert deck_colors(deck, CATALOG) == ["W", "U", "R"]
    assert deck_colors([[4, "Lightning Bolt"]], CATALOG) == ["R"]


def test_the_sideboard_counts_towards_the_decks_colours_and_lands_never_do():
    mainboard_and_sideboard = [[4, "Lightning Bolt"], [2, "Path to Exile"], [4, "Arid Mesa"]]
    assert deck_colors(mainboard_and_sideboard, CATALOG) == ["W", "R"]
    assert deck_colors([[4, "Lightning Bolt"], [4, "Arid Mesa"]], CATALOG) == ["R"]
    # A modal double-faced spell is a spell: its front face's cost counts.
    assert deck_colors([[4, "Shatterskull Smashing"]], CATALOG) == ["R"]


def test_a_deck_of_only_hybrid_symbols_takes_the_colours_of_those_symbols():
    assert deck_colors([[4, "Burning-Tree Emissary"]], CATALOG) == ["R", "G"]
    assert deck_colors([[4, "Burning-Tree Emissary"], [2, "Kitchen Finks"]], CATALOG) == ["W", "R", "G"]
    # ...but any one-colour symbol makes the hybrids stand down.
    assert deck_colors([[4, "Burning-Tree Emissary"], [4, "Lightning Bolt"]], CATALOG) == ["R"]


def test_a_two_halves_card_has_the_colours_of_both_halves():
    assert deck_colors([[4, "Wear/Tear"]], CATALOG) == ["W", "R"]  # MTGGoldfish writes the split with a single slash
    assert deck_colors([[4, "Bonecrusher Giant"]], CATALOG) == ["R"]
    assert deck_colors([[1, "Delver of Secrets"]], CATALOG) == ["U"]


def test_a_colourless_deck_has_no_colours_and_an_unknown_one_is_none():
    colourless = [[4, "Sol Ring"], [4, "Walking Ballista"], [2, "Thought-Knot Seer"], [4, "Ornithopter"], [4, "Mountain"]]
    assert deck_colors(colourless, CATALOG) == []  # {C} is not a colour of the deck
    assert deck_colors([[4, "Dismember"]], CATALOG) == []  # nothing but a Phyrexian cost
    assert deck_colors([], CATALOG) is None
    assert deck_colors([[4, "Made-up Card"], [4, "Mountain"]], CATALOG) is None  # no known spell, so nothing to say
    assert deck_colors([[4, "Lightning Bolt"]], {}) is None
    assert deck_colors([[4, "Made-up Card"], [4, "Lightning Bolt"]], CATALOG) == ["R"]  # an unknown card is skipped


def test_weights_count_each_symbol_once_per_copy_and_sum_to_one():
    mainboard = [[4, "Lightning Bolt"], [2, "Counterspell"], [4, "Mountain"]]
    weights = color_weights(mainboard, CATALOG)
    # Four {R} against two copies of {U}{U}.
    assert weights == pytest.approx({"R": 4 / 8, "U": 4 / 8})
    assert sum(weights.values()) == pytest.approx(1.0)
    # Quantity is what repeats a symbol: one copy of a card with two symbols is two.
    assert color_weights([[1, "Counterspell"], [2, "Lightning Bolt"]], CATALOG) == pytest.approx({"U": 0.5, "R": 0.5})
    assert color_weights([[4, "Frost Titan"]], CATALOG) == {"U": 1.0}


def test_a_hybrid_symbol_is_split_among_the_colours_the_deck_plays():
    # Red and white are played, green is not: the {R/W} symbols are split between red and white.
    split = color_weights([[2, "Boros Reckoner"], [2, "Lightning Bolt"], [2, "Path to Exile"]], CATALOG)
    assert split == pytest.approx({"R": 0.5, "W": 0.5})
    assert split["R"] + split["W"] == pytest.approx(1.0)
    # {G/W} in a deck that plays white but not green all goes to white.
    assert color_weights([[4, "Kitchen Finks"], [4, "Lightning Bolt"], [4, "Path to Exile"]], CATALOG) == pytest.approx(
        {"W": 12 / 16, "R": 4 / 16}  # eight {G/W} and four {W} against four {R}
    )
    # A deck made of hybrid symbols alone plays both of its colours, so each symbol is split between them.
    assert color_weights([[4, "Burning-Tree Emissary"]], CATALOG) == pytest.approx({"R": 0.5, "G": 0.5})


def test_phyrexian_and_generic_symbols_count_nothing_and_a_deck_with_no_symbol_is_colourless():
    # Dismember's {B/P} can be paid with life: only the Bolt's {R} counts.
    assert color_weights([[4, "Dismember"], [4, "Lightning Bolt"]], CATALOG) == {"R": 1.0}
    assert color_weights([[4, "Dismember"], [4, "Sol Ring"], [4, "Walking Ballista"], [20, "Mountain"]], CATALOG) == {"C": 1.0}
    assert color_weights([[4, "Ornithopter"]], CATALOG) == {"C": 1.0}


def test_a_colourless_symbol_weighs_with_the_colours_and_a_colour_hybrid_with_two_halves_is_counted_per_half():
    assert color_weights([[2, "Thought-Knot Seer"], [2, "Lightning Bolt"]], CATALOG) == pytest.approx({"C": 0.5, "R": 0.5})
    assert color_weights([[1, "Wear/Tear"]], CATALOG) == pytest.approx({"R": 0.5, "W": 0.5})
    assert color_weights([[1, "Bonecrusher Giant"], [1, "Path to Exile"]], CATALOG) == pytest.approx({"R": 2 / 3, "W": 1 / 3})


def test_weights_are_none_when_no_spell_is_known_and_use_only_the_mainboard_given():
    assert color_weights([], CATALOG) is None
    assert color_weights([[4, "Made-up Card"], [4, "Mountain"]], CATALOG) is None  # a land says nothing of the colours
    assert color_weights([[4, "Lightning Bolt"]], {}) is None
    assert color_weights([[4, "Made-up Card"], [4, "Lightning Bolt"]], CATALOG) == {"R": 1.0}
