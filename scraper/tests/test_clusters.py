import pytest

from mtgmeta.clusters import Archetype, Merging, apply, assign, deck_vector, merge, plan, profile, similarity, window

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


def cards(letters):
    return {letter: 4 for letter in letters}


def test_every_member_is_close_to_its_leader_so_no_chain_of_look_alikes_forms():
    big = Archetype("big", "Big", 50, [cards("abcdefghij")])
    near = Archetype("near", "Near", 20, [cards("abcdefghik")])  # 0.9 to Big
    drift = Archetype("drift", "Drift", 10, [cards("cdefghiklm")])  # 0.8 to Near, only 0.7 to Big
    assert similarity(near.profile, big.profile) == pytest.approx(0.9)
    assert similarity(drift.profile, near.profile) == pytest.approx(0.8)

    groups = merge([drift, near, big], threshold=0.8)

    assert [[m.archetype_id for m in group.members] for group in groups] == [["big", "near"], ["drift"]]


def test_a_member_joins_the_leader_it_scores_highest_against():
    first = Archetype("first", "First", 50, [cards("abcdefghij")])
    second = Archetype("second", "Second", 40, [cards("abcdefgklm")])  # 0.7 to First, so it leads its own group
    member = Archetype("member", "Member", 5, [cards("abcdefghkl")])  # 0.8 to First, 0.9 to Second

    groups = merge([first, second, member], threshold=0.75)

    assert {group.archetype_id: [m.archetype_id for m in group.members] for group in groups} == {"first": ["first"], "second": ["second", "member"]}


def board(letters):
    return [[4, letter] for letter in letters]


def snapshot(archetypes, events, generated_at="2026-10-16T12:00:00Z"):
    return {
        "generated_at": generated_at,
        "meta": {},
        "archetypes": {
            key: {"archetype_id": key, "name": key.title(), "deck_id": None, "results": [{"deck_id": deck_id, "date": date} for deck_id, date in results]}
            for key, results in archetypes.items()
        },
        "events": events,
    }


def test_one_set_of_groups_holds_in_every_window_led_by_the_most_decks_this_week():
    # "old" has more decks over the month, "new" more this week; they play one deck only lately.
    archetypes = {
        "old": [("o1", "2026-10-15T00:00:00Z")] + [(f"o{n}", "2026-09-20T00:00:00Z") for n in range(2, 8)],
        "new": [("n1", "2026-10-15T00:00:00Z"), ("n2", "2026-10-14T00:00:00Z")],
        "other": [("x1", "2026-10-15T00:00:00Z")],
    }
    decks = {"o1": {"m": board("abcdefghij")}, "n1": {"m": board("abcdefghik")}, "n2": {"m": board("abcdefghik")}, "x1": {"m": board("klmnopqrst")}}
    decks.update({f"o{n}": {"m": board("abcdeuvwxy")} for n in range(2, 8)})  # a month ago it was another list
    events = [
        {
            "event_id": "1",
            "event_name": "Modern Challenge 32 2026-10-15",
            "date": "2026-10-15T00:00:00Z",
            "results": [
                {"deck_id": "o1", "archetype": "Old", "archetype_id": "old"},
                {"deck_id": "brew", "archetype": "UR", "archetype_id": None},
                {"deck_id": "rogue", "archetype": "BG", "archetype_id": None},
            ],
        }
    ]
    decks["brew"] = {"m": board("abcdefghik")}
    decks["rogue"] = {"m": board("uvwxyz")}

    merging = plan(snapshot(archetypes, events), decks, set(), threshold=0.8)

    assert {member: (leader, days) for member, (leader, _, days) in merging.leaders.items()} == {"old": ("new", 7)}
    assert {deck_id: leader for deck_id, (leader, _) in merging.assigned.items()} == {"brew": "new"}


def tile(key, percentage, deck_count, colors):
    return {"name": key.title(), "id": key, "percentage": percentage, "deck_count": deck_count, "deck_id": f"{key}-featured", "colors": colors, "key_cards": [{"name": f"{key} card", "oracle_id": key}]}


def test_the_published_snapshot_has_one_archetype_per_group_under_its_leader():
    document = {
        "generated_at": "2026-10-16T12:00:00Z",
        "meta": {
            "7d": {"timeframe": "7d", "archetypes": [tile("burn", 6.0, 60, ["R"]), tile("ramp", 5.0, 50, ["G"]), tile("brood", 1.6, None, ["R", "G"])]},
            "30d": {"timeframe": "30d", "archetypes": [tile("brood", 3.0, 30, ["R", "G"]), tile("burn", 2.0, 20, ["R"])]},
        },
        "archetypes": {
            "ramp": {"archetype_id": "ramp", "name": "Ramp", "deck_id": "ramp-featured", "results": [{"deck_id": "1", "date": "2026-10-14T00:00:00Z"}]},
            "brood": {"archetype_id": "brood", "name": "Brood", "deck_id": "brood-featured", "results": [{"deck_id": "2", "date": "2026-10-15T00:00:00Z"}]},
        },
        "events": [
            {
                "event_id": "9",
                "event_name": "Modern Challenge 32 2026-10-15",
                "date": "2026-10-15T00:00:00Z",
                "results": [
                    {"finish": "1st Place", "player": "a", "deck_id": "2", "archetype": "Brood", "archetype_id": "brood"},
                    {"finish": "2nd Place", "player": "b", "deck_id": "3", "archetype": "RG", "archetype_id": None},
                    {"finish": "3rd Place", "player": "c", "deck_id": "4", "archetype": "Burn", "archetype_id": "burn"},
                ],
            }
        ],
    }
    merging = Merging({"brood": ("ramp", 0.9, 7)}, {"3": ("ramp", 0.85)}, {"ramp": "Ramp", "brood": "Brood", "burn": "Burn"})

    published = apply(document, merging)

    week = published["meta"]["7d"]["archetypes"]
    assert [(t["id"], t["name"], t["percentage"], t["deck_count"], t["colors"], t["deck_id"]) for t in week] == [
        ("ramp", "Ramp", 6.6, None, ["G"], "ramp-featured"),  # a member's unknown deck count makes the sum unknown
        ("burn", "Burn", 6.0, 60, ["R"], "burn-featured"),
    ]
    # The leader isn't in the 30-day list: its group takes the leader's tile from the week, under its name.
    assert [(t["id"], t["percentage"], t["deck_count"], t["colors"]) for t in published["meta"]["30d"]["archetypes"]] == [("ramp", 3.0, 30, ["G"]), ("burn", 2.0, 20, ["R"])]
    assert list(published["archetypes"]) == ["ramp"]
    assert [r["deck_id"] for r in published["archetypes"]["ramp"]["results"]] == ["2", "3", "1"]
    assert published["archetypes"]["ramp"]["deck_id"] == "ramp-featured"
    assert [(r["archetype_id"], r["archetype"]) for r in published["events"][0]["results"]] == [("ramp", "Ramp"), ("ramp", "Ramp"), ("burn", "Burn")]
    assert published["merges"] == {"brood": "ramp"}
    assert document["events"][0]["results"][0]["archetype_id"] == "brood"  # the scraped snapshot is left as it was
