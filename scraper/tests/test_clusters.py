import pytest

from mtgmeta.clusters import Archetype, assign, deck_vector, merge, profile, similarity, window

LANDS = {"forest", "mountain", "misty-rainforest"}

RAMP = [[4, "Ugin's Labyrinth"], [4, "Devourer of Destiny"], [4, "Ancient Stirrings"], [4, "Kozilek's Command"], [4, "Thought-Knot Seer"]]
BROODSCALE = [[4, "Basking Broodscale"], [4, "Blade of the Bloodchief"], [4, "Ancient Stirrings"], [4, "Kozilek's Command"], [4, "Thought-Knot Seer"]]
BURN = [[4, "Lightning Bolt"], [4, "Lava Spike"], [4, "Rift Bolt"], [4, "Goblin Guide"], [4, "Monastery Swiftspear"]]


def vectors(*boards):
    return [deck_vector(board, LANDS) for board in boards]


def test_a_deck_vector_drops_lands_and_caps_copies():
    board = [[2, "Lightning Bolt"], [3, "Lightning Bolt"], [12, "Mountain"], [1, "Misty Rainforest"], [7, "Relentless Rats"]]
    assert deck_vector(board, LANDS) == {"lightning-bolt": 4, "relentless-rats": 4}


def test_a_profile_is_share_of_decks_times_average_copies():
    assert profile([{"bolt": 4, "spike": 2}, {"bolt": 2}]) == {"bolt": 3, "spike": 1}


def test_similarity_is_one_for_the_same_list_and_zero_for_no_shared_card():
    assert similarity({"a": 4, "b": 2}, {"a": 4, "b": 2}) == pytest.approx(1)
    assert similarity({"a": 4}, {"b": 4}) == 0
    assert similarity({}, {"a": 4}) == 0


def test_close_archetypes_merge_under_the_one_with_most_decks_and_a_distant_one_stays_alone():
    ramp = Archetype("modern-eldrazi-ramp", "Eldrazi Ramp", 40, vectors(RAMP, RAMP))
    broodscale = Archetype("modern-eldrazi-broodscale", "Eldrazi Broodscale", 12, vectors(BROODSCALE))
    burn = Archetype("modern-burn", "Burn", 30, vectors(BURN, BURN))

    groups = merge([broodscale, burn, ramp], threshold=0.5)

    assert [(group.archetype_id, group.name, [m.archetype_id for m in group.members], group.decks) for group in groups] == [
        ("modern-eldrazi-ramp", "Eldrazi Ramp", ["modern-eldrazi-ramp", "modern-eldrazi-broodscale"], 52),
        ("modern-burn", "Burn", ["modern-burn"], 30),
    ]
    assert len(merge([broodscale, burn, ramp], threshold=0.7)) == 3


def test_a_result_with_no_archetype_joins_the_closest_group_above_the_threshold():
    groups = merge(
        [Archetype("modern-eldrazi-ramp", "Eldrazi Ramp", 40, vectors(RAMP)), Archetype("modern-burn", "Burn", 30, vectors(BURN))],
        threshold=0.6,
    )
    pilot = deck_vector([[3, "Lightning Bolt"], [4, "Lava Spike"], [4, "Rift Bolt"], [4, "Goblin Guide"], [4, "Eidolon of the Great Revel"]], LANDS)
    rogue = deck_vector([[4, "Thoughtseize"], [4, "Lightning Bolt"]], LANDS)

    assigned = assign({"1": pilot, "2": rogue}, groups, threshold=0.6)

    assert {deck_id: group.name for deck_id, (group, _) in assigned.items()} == {"1": "Burn"}


def test_a_window_counts_an_archetypes_decks_and_keeps_results_with_no_archetype_apart():
    document = {
        "generated_at": "2026-10-16T12:00:00Z",
        "archetypes": {
            "modern-burn": {
                "archetype_id": "modern-burn",
                "name": "Burn",
                "results": [
                    {"deck_id": "1", "date": "2026-10-15T00:00:00Z"},
                    {"deck_id": "2", "date": "2026-10-14T00:00:00Z"},
                    {"deck_id": "old", "date": "2026-09-01T00:00:00Z"},
                ],
            }
        },
        "events": [
            {
                "date": "2026-10-15T00:00:00Z",
                "results": [
                    {"deck_id": "1", "archetype": "Burn", "archetype_id": "modern-burn"},
                    {"deck_id": "3", "archetype": "Rakdos Burn", "archetype_id": None},
                ],
            }
        ],
    }
    deck_cards = {"1": {"m": BURN}, "3": {"m": BURN}, "old": {"m": RAMP}}

    found = window(document, deck_cards, LANDS, 7)

    assert (found.decks, found.lists) == (3, 2)
    assert [(a.archetype_id, a.decks, a.lists) for a in found.archetypes] == [("modern-burn", 2, 1)]
    assert {deck_id: title for deck_id, (title, _) in found.unassigned.items()} == {"3": "Rakdos Burn"}
