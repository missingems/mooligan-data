from datetime import datetime, timedelta, timezone

import pytest

from mtgmeta.cards import slug
from mtgmeta.popular import build_popular_cards, card_kind, deck_dates, is_basic, trend

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def card(name, type_line, layout="normal"):
    return {"name": name, "oracle_id": "o-" + slug(name), "type_line": type_line, "layout": layout}


CATALOG = {
    slug(entry["name"]): entry
    for entry in [
        card("Lightning Bolt", "Instant"),
        card("Surgical Extraction", "Instant"),
        card("Tarmogoyf", "Creature — Lhurgoyf"),
        card("Ragavan, Nimble Pilferer", "Legendary Creature — Monkey Pirate"),
        card("Jace, the Mind Sculptor", "Legendary Planeswalker — Jace"),
        card("Cultivate", "Sorcery"),
        card("Sol Ring", "Artifact"),
        card("Oblivion Ring", "Enchantment"),
        card("Invasion of Ikoria", "Battle — Siege"),
        card("Arid Mesa", "Land"),
        card("Forest", "Basic Land — Forest"),
        card("Snow-Covered Island", "Basic Snow Land — Island"),
        card("Wastes", "Basic Land"),
        card("Fire // Ice", "Instant", layout="split"),
        card("Bonecrusher Giant // Stomp", "Creature — Giant Rogue", layout="adventure"),
        card("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Enchantment — Saga", layout="transform"),
        card("Shatterskull Smashing // Shatterskull, the Hammer Pass", "Sorcery", layout="modal_dfc"),
    ]
}


def days_ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")


def world(decks, archetype_decks=(), featured=None):
    """A snapshot and its stored decklists. Each deck is `(days ago, mainboard, sideboard)`, the sideboard optional.

    The days are a number, or a full date to place a deck exactly. `decks` are results of one event a day,
    `archetype_decks` results of an archetype that no event lists, and `featured` the mainboard of the archetype's own deck.
    """
    deck_cards = {}

    def store(main, side=()):
        deck_id = str(len(deck_cards) + 1)
        deck_cards[deck_id] = {"m": [list(entry) for entry in main], "s": [list(entry) for entry in side]}
        return deck_id

    def when(age):
        return age if isinstance(age, str) else days_ago(age)

    events = {}
    for age, main, *side in decks:
        events.setdefault(when(age), []).append({"deck_id": store(main, *side)})
    results = [{"deck_id": store(main, *side), "date": when(age)} for age, main, *side in archetype_decks]
    document = {
        "format": "modern",
        "events": [{"event_id": date, "date": date, "results": decks} for date, decks in events.items()],
        "archetypes": {"a": {"deck_id": store(featured) if featured else None, "results": results}},
    }
    return document, deck_cards


def popular(decks, catalog=CATALOG, **kwargs):
    document, deck_cards = world(decks, **kwargs)
    return build_popular_cards(document, deck_cards, catalog, NOW)


def cards(file, window, kind):
    """The names of a window's list of one kind, in order; None when the window has no such list."""
    lists = {one["kind"]: one["cards"] for one in file["windows"][window]["lists"]}
    return [row["name"] for row in lists[kind]] if kind in lists else None


def test_the_file_has_every_window_of_the_format():
    file = popular([(1, [(4, "Lightning Bolt")])])
    assert (file["schema"], file["format"], file["generated_at"]) == (1, "modern", "2026-09-30T12:00:00Z")
    assert list(file["windows"]) == ["7d", "14d", "30d"]


@pytest.mark.parametrize(
    "type_line, kind",
    [
        ("Creature — Human Wizard", "creature"),
        ("Legendary Creature — Elf Druid", "creature"),
        ("Artifact Creature — Golem", "creature"),
        ("Enchantment Creature — Satyr", "creature"),
        ("Land Creature — Forest Dryad", "creature"),
        ("Legendary Planeswalker — Jace", "planeswalker"),
        ("Battle — Siege", "battle"),
        ("Land", "land"),
        ("Land — Desert", "land"),
        ("Legendary Land", "land"),
        ("Snow Land", "land"),
        ("Artifact Land", "land"),
        ("Enchantment Land", "land"),
        ("Instant", "instant"),
        ("Instant — Adventure", "instant"),
        ("Sorcery", "sorcery"),
        ("Kindred Instant — Lesson", "instant"),
        ("Tribal Sorcery — Goblin", "sorcery"),
        ("Artifact", "artifact"),
        ("Legendary Artifact — Equipment", "artifact"),
        ("Enchantment", "enchantment"),
        ("Enchantment — Saga", "enchantment"),
        ("Enchantment — Aura", "enchantment"),
        # The front face decides: a spell with a land on the back is a spell, a split card is its first half.
        ("Sorcery // Land", "sorcery"),
        ("Land // Land", "land"),
        ("Instant // Instant", "instant"),
        ("Creature — Giant Rogue // Instant — Adventure", "creature"),
        ("Legendary Creature — Human Wizard // Legendary Planeswalker — Jace", "creature"),
        # Only the types before the dash count, and whole words.
        ("Artifact — Creature Land", "artifact"),
        ("Artifact — Landmark", "artifact"),
        ("Dungeon", None),
        ("Card", None),
        ("", None),
    ],
)
def test_a_card_is_the_first_of_the_kinds_its_front_face_is(type_line, kind):
    assert card_kind(type_line) == kind


@pytest.mark.parametrize(
    "type_line, basic",
    [
        ("Basic Land — Forest", True),
        ("Basic Snow Land — Island", True),
        ("Basic Land", True),  # Wastes
        ("Basic Snow Land", True),  # Snow-Covered Wastes
        ("Land", False),
        ("Snow Land", False),
        ("Legendary Land", False),
        ("Land — Island Swamp", False),
        ("Land Creature — Forest Dryad", False),
        ("Creature — Basic Landwalker", False),
        ("", False),
    ],
)
def test_a_basic_is_a_card_with_the_basic_supertype(type_line, basic):
    assert is_basic(type_line) == basic


def test_basics_snow_basics_and_wastes_are_left_out_of_every_list_and_other_lands_stay():
    decks = [(1, [(4, "Arid Mesa"), (8, "Forest"), (4, "Snow-Covered Island"), (2, "Wastes"), (4, "Lightning Bolt")], [(1, "Forest")])] * 3
    file = popular(decks)
    assert cards(file, "7d", "all") == ["Arid Mesa", "Lightning Bolt"]
    assert cards(file, "7d", "land") == ["Arid Mesa"]
    assert "sideboard" not in [one["kind"] for one in file["windows"]["7d"]["lists"]]  # a basic was the only sideboard card
    assert file["windows"]["7d"]["deck_count"] == 3


def test_a_deck_is_dated_by_its_event_or_else_an_archetype_result_and_a_featured_deck_has_no_date():
    document = {
        "events": [{"date": "2026-09-29T00:00:00Z", "results": [{"deck_id": "1"}, {"deck_id": "2"}]}],
        "archetypes": {
            "a": {
                "deck_id": "9",
                "results": [{"deck_id": "2", "date": "2026-09-20T00:00:00Z"}, {"deck_id": "3", "date": "2026-09-28T00:00:00Z"}],
            },
            "b": {"deck_id": "8", "results": []},
        },
    }
    assert deck_dates(document) == {
        "1": datetime(2026, 9, 29, tzinfo=timezone.utc),
        "2": datetime(2026, 9, 29, tzinfo=timezone.utc),  # the event's date, not the result's
        "3": datetime(2026, 9, 28, tzinfo=timezone.utc),  # only an archetype lists it, as big paper events are
    }


def test_each_window_counts_the_decks_dated_inside_it_once_each():
    bolt = [(4, "Lightning Bolt")]
    file = popular(
        [
            (0, bolt),  # today
            (6, bolt),
            (8, bolt),  # out of the 7 days, in the 14
            (20, bolt),  # in the 30 only
            (40, bolt),  # in none
            (-2, bolt),  # dated ahead, which MTGGoldfish does for an event still to be played
        ],
        featured=bolt,  # an archetype's own deck has no date
    )
    assert {window: file["windows"][window]["deck_count"] for window in file["windows"]} == {"7d": 2, "14d": 3, "30d": 4}
    played = {window: file["windows"][window]["lists"][0]["cards"][0]["decks"] for window in file["windows"]}
    assert played == {"7d": 2, "14d": 3, "30d": 4}


def test_a_deck_dated_exactly_a_window_back_is_in_it_and_one_dated_earlier_is_not():
    bolt = [(4, "Lightning Bolt")]
    file = popular([("2026-09-23T12:00:00Z", bolt), ("2026-09-23T11:59:59Z", bolt), ("2026-09-30T23:59:59Z", bolt), ("2026-10-01T00:00:00Z", bolt)])
    # Now is the 30th at noon: the rest of the 30th is today, and the 1st is not.
    assert file["windows"]["7d"]["deck_count"] == 2


def test_decks_only_an_archetype_lists_count_like_the_events_decks():
    file = popular(
        [(1, [(4, "Lightning Bolt")])],
        archetype_decks=[(2, [(4, "Lightning Bolt")]), (3, [(2, "Lightning Bolt")]), (10, [(1, "Lightning Bolt")])],
    )
    assert file["windows"]["7d"]["deck_count"] == 3
    bolt = file["windows"]["7d"]["lists"][0]["cards"][0]
    assert (bolt["decks"], bolt["copies"]) == (3, 3.3)  # (4 + 4 + 2) / 3
    assert file["windows"]["14d"]["deck_count"] == 4


def test_a_deck_that_is_not_stored_is_not_counted():
    document, deck_cards = world([(1, [(4, "Lightning Bolt")]), (1, [(4, "Lightning Bolt")])])
    del deck_cards["2"]
    file = build_popular_cards(document, deck_cards, CATALOG, NOW)
    assert file["windows"]["7d"]["deck_count"] == 1


def test_a_list_ranks_one_board_and_averages_the_copies_of_the_decks_that_play_it():
    file = popular(
        [
            (1, [(4, "Lightning Bolt"), (1, "Tarmogoyf")], [(1, "Lightning Bolt"), (3, "Surgical Extraction")]),
            (1, [(3, "Lightning Bolt"), (1, "Tarmogoyf")], [(2, "Surgical Extraction")]),
            (1, [(1, "Tarmogoyf")], [(2, "Surgical Extraction")]),
            # A card the list names twice is one deck with the copies added up.
            (1, [(2, "Tarmogoyf"), (1, "Tarmogoyf")], [(2, "Lightning Bolt")]),
        ]
    )
    window = file["windows"]["7d"]
    assert window["deck_count"] == 4
    lists = {one["kind"]: one["cards"] for one in window["lists"]}
    assert [one["kind"] for one in window["lists"]] == ["all", "creature", "instant", "sideboard"]
    # The mainboard: Surgical Extraction is only ever in the sideboard, so it is not in `all` or `instant`.
    assert lists["all"] == [
        {"name": "Tarmogoyf", "oracle_id": "o-tarmogoyf", "type": "creature", "decks": 4, "share": 100.0, "copies": 1.5, "trend": None},
        {"name": "Lightning Bolt", "oracle_id": "o-lightning-bolt", "type": "instant", "decks": 2, "share": 50.0, "copies": 3.5, "trend": None},
    ]
    assert lists["creature"] == lists["all"][:1] and lists["instant"] == lists["all"][1:]
    # The sideboard has its own decks and copies: Lightning Bolt is in two of them, one copy and two.
    assert lists["sideboard"] == [
        {"name": "Surgical Extraction", "oracle_id": "o-surgical-extraction", "type": "instant", "decks": 3, "share": 75.0, "copies": 2.3, "trend": None},
        {"name": "Lightning Bolt", "oracle_id": "o-lightning-bolt", "type": "instant", "decks": 2, "share": 50.0, "copies": 1.5, "trend": None},
    ]


def test_a_card_needs_two_decks_and_one_percent_of_the_windows_decks():
    # Two decks in a window of two is 100%, and one deck is below the floor of two however large its share.
    file = popular([(1, [(4, "Lightning Bolt"), (4, "Tarmogoyf")]), (1, [(4, "Lightning Bolt")])])
    assert cards(file, "7d", "all") == ["Lightning Bolt"]

    # In a window of 300 decks, 3 is exactly 1% and 2 is under it.
    decks = [(1, [(4, "Tarmogoyf")])] * 295
    decks += [(1, [(4, "Lightning Bolt")])] * 3 + [(1, [(4, "Surgical Extraction")])] * 2
    file = popular(decks)
    assert file["windows"]["7d"]["deck_count"] == 300
    assert cards(file, "7d", "all") == ["Tarmogoyf", "Lightning Bolt"]
    # The sideboard has the same floor.
    file = popular([(1, [(4, "Tarmogoyf")], [(2, "Lightning Bolt")])] * 3 + [(1, [(4, "Tarmogoyf")])] * 297)
    assert cards(file, "7d", "sideboard") == ["Lightning Bolt"]
    file = popular([(1, [(4, "Tarmogoyf")], [(2, "Lightning Bolt")])] * 2 + [(1, [(4, "Tarmogoyf")])] * 298)
    assert cards(file, "7d", "sideboard") is None


def test_the_lists_are_capped_and_cards_that_tie_come_in_name_order():
    creatures = [f"Creature {n:02d}" for n in range(60)]
    instants = [f"Instant {n:02d}" for n in range(30)]
    catalog = {slug(name): card(name, "Creature — Test") for name in creatures}
    catalog.update({slug(name): card(name, "Instant") for name in instants})
    main = [(1, name) for name in creatures + instants]
    file = popular([(1, main)] * 4, catalog=catalog)
    # Every card is in the same four decks with one copy, so they rank by name: 50 in `all`, 25 in each list.
    assert cards(file, "7d", "all") == creatures[:50]
    assert cards(file, "7d", "creature") == creatures[:25]
    assert cards(file, "7d", "instant") == instants[:25]
    assert [one["kind"] for one in file["windows"]["7d"]["lists"]] == ["all", "creature", "instant"]


def test_a_sideboard_list_is_capped_at_twenty_five_too():
    names = [f"Instant {n:02d}" for n in range(30)]
    catalog = {slug(name): card(name, "Instant") for name in names}
    file = popular([(1, [], [(1, name) for name in names])] * 3, catalog=catalog)
    assert cards(file, "7d", "sideboard") == names[:25]
    assert cards(file, "7d", "all") is None  # nothing in the mainboard


def test_cards_rank_by_decks_then_copies_then_name():
    def deck(*main):
        return (1, list(main))

    file = popular(
        [
            # Cultivate in 4 decks of one copy; Sol Ring and Oblivion Ring in 3 decks of two; Tarmogoyf in 3 of four.
            deck((1, "Cultivate"), (2, "Sol Ring"), (2, "Oblivion Ring"), (4, "Tarmogoyf")),
            deck((1, "Cultivate"), (2, "Sol Ring"), (2, "Oblivion Ring"), (4, "Tarmogoyf")),
            deck((1, "Cultivate"), (2, "Sol Ring"), (2, "Oblivion Ring"), (4, "Tarmogoyf")),
            deck((1, "Cultivate")),
        ]
    )
    assert cards(file, "7d", "all") == ["Cultivate", "Tarmogoyf", "Oblivion Ring", "Sol Ring"]


def test_every_kind_of_card_has_its_list_in_the_order_the_app_shows_them_and_an_empty_one_is_left_out():
    everything = [
        (4, "Tarmogoyf"), (4, "Jace, the Mind Sculptor"), (4, "Lightning Bolt"), (4, "Cultivate"), (4, "Sol Ring"),
        (4, "Oblivion Ring"), (4, "Invasion of Ikoria"), (4, "Arid Mesa"),
    ]
    file = popular([(1, everything, [(2, "Surgical Extraction")])] * 2 + [(10, [(4, "Tarmogoyf")])] * 2)
    kinds = ["all", "creature", "planeswalker", "instant", "sorcery", "artifact", "enchantment", "battle", "land", "sideboard"]
    assert [one["kind"] for one in file["windows"]["7d"]["lists"]] == kinds
    assert cards(file, "7d", "planeswalker") == ["Jace, the Mind Sculptor"]
    assert cards(file, "7d", "battle") == ["Invasion of Ikoria"]
    # A window with nothing but creatures has the creature list: the other lists are left out, not published empty.
    only_creatures = popular([(1, [(4, "Tarmogoyf")])] * 2)
    assert [one["kind"] for one in only_creatures["windows"]["7d"]["lists"]] == ["all", "creature"]


def test_a_window_with_no_decks_is_published_without_lists():
    file = popular([(40, [(4, "Lightning Bolt")])] * 3)
    assert file["windows"]["7d"] == {"deck_count": 0, "lists": []}
    assert file["windows"]["30d"] == {"deck_count": 0, "lists": []}
    assert build_popular_cards({"format": "modern", "events": [], "archetypes": {}}, {}, CATALOG, NOW)["windows"]["30d"]["lists"] == []


def test_a_name_the_catalog_does_not_know_is_skipped_but_its_decks_still_count():
    mystery = [(4, "Lightning Bolt"), (4, "Mystery Card"), (2, "Tarmogoyf")]
    file = popular([(1, mystery, [(3, "Another Mystery")])] * 3)
    assert file["windows"]["7d"]["deck_count"] == 3
    assert cards(file, "7d", "all") == ["Lightning Bolt", "Tarmogoyf"]
    assert cards(file, "7d", "sideboard") is None
    # A catalog with nothing in it, as when Scryfall could not be read, has nothing to list.
    empty = popular([(1, mystery)] * 3, catalog={})
    assert empty["windows"]["7d"] == {"deck_count": 3, "lists": []}


def test_a_card_with_no_known_kind_is_skipped_as_well():
    catalog = {**CATALOG, "the-harvester": card("The Harvester", "Hero"), "old-card": {"name": "Old Card", "oracle_id": "o"}}
    file = popular([(1, [(4, "The Harvester"), (4, "Old Card"), (4, "Lightning Bolt")])] * 2, catalog=catalog)
    assert cards(file, "7d", "all") == ["Lightning Bolt"]


def test_a_split_card_keeps_both_halves_and_any_other_two_faced_card_is_its_front_face():
    decks = [
        (
            1,
            [(4, "Fire/Ice"), (4, "Bonecrusher Giant"), (1, "Fable of the Mirror-Breaker"), (1, "Shatterskull Smashing")],
            [(1, "Fire // Ice")],
        )
    ] * 2
    file = popular(decks)
    names = {row["name"]: row["type"] for row in file["windows"]["7d"]["lists"][0]["cards"]}
    assert names == {
        "Fire // Ice": "instant",
        "Bonecrusher Giant": "creature",
        "Fable of the Mirror-Breaker": "enchantment",
        "Shatterskull Smashing": "sorcery",
    }
    assert cards(file, "7d", "sideboard") == ["Fire // Ice"]
    row = next(row for row in file["windows"]["7d"]["lists"][0]["cards"] if row["name"] == "Fable of the Mirror-Breaker")
    assert row["oracle_id"] == "o-fable-of-the-mirror-breaker"


@pytest.mark.parametrize(
    "recent, recent_total, baseline, baseline_total, expected",
    [
        (60, 100, 20, 100, "up"),
        (20, 100, 60, 100, "down"),
        # A move of 5 points or fewer is no trend, however sure: exactly 5 is not more than 5.
        (5000, 10000, 4950, 10000, None),
        (5500, 10000, 5000, 10000, None),
        (5600, 10000, 5000, 10000, "up"),
        (5000, 10000, 5600, 10000, "down"),
        # A big move over few decks is chance: its z-score is under 3.
        (4, 10, 1, 10, None),
        (556, 1000, 500, 1000, None),
        # Without decks in both periods, or with a card in all of them or none, there is nothing to compare.
        (5, 10, 0, 0, None),
        (0, 0, 5, 10, None),
        (0, 100, 0, 100, None),
        (100, 100, 100, 100, None),
    ],
)
def test_a_trend_needs_a_move_of_over_five_points_and_a_z_score_over_three(recent, recent_total, baseline, baseline_total, expected):
    assert trend(recent, recent_total, baseline, baseline_total) == expected


def trending_world():
    """Three cards over three periods of 100 decks each: Tarmogoyf rising, Lightning Bolt falling, Cultivate flat."""

    def decks(age, goyf, bolt, side):
        return [
            (
                age,
                [(4, "Tarmogoyf")] * (n < goyf) + [(4, "Lightning Bolt")] * (n < bolt) + [(4, "Cultivate")] * (n < 40),
                [(2, "Cultivate")] * (n < side),
            )
            for n in range(100)
        ]

    return decks(2, 60, 10, 80) + decks(10, 20, 50, 20) + decks(20, 20, 50, 20)


def trends(file, window, kind):
    lists = {one["kind"]: one["cards"] for one in file["windows"][window]["lists"]}
    return {row["name"]: row["trend"] for row in lists[kind]}


def test_trends_set_each_window_against_the_period_before_it():
    file = popular(trending_world())
    assert [file["windows"][window]["deck_count"] for window in ("7d", "14d", "30d")] == [100, 200, 300]
    flat = {"Cultivate": None}
    # 7 days against days 8 to 14, 14 days against days 15 to 28, and for 30 days the last week against the 23 days before.
    assert trends(file, "7d", "all") == {"Tarmogoyf": "up", "Lightning Bolt": "down", **flat}
    assert trends(file, "14d", "all") == {"Tarmogoyf": "up", "Lightning Bolt": "down", **flat}
    assert trends(file, "30d", "all") == {"Tarmogoyf": "up", "Lightning Bolt": "down", **flat}


def test_a_trend_follows_the_board_its_list_ranks():
    file = popular(trending_world())
    # Cultivate is in 40 of 100 mainboards in every period but in 80 sideboards this week against 20 before.
    assert trends(file, "7d", "all")["Cultivate"] is None
    assert trends(file, "7d", "sideboard") == {"Cultivate": "up"}
    assert trends(file, "7d", "creature") == {"Tarmogoyf": "up"}


def test_a_window_with_nothing_before_it_has_no_trends():
    file = popular([(2, [(4, "Tarmogoyf")] * (n < 60) + [(4, "Cultivate")] * (n < 30)) for n in range(100)])
    assert trends(file, "7d", "all") == {"Tarmogoyf": None, "Cultivate": None}
    assert trends(file, "30d", "all") == {"Tarmogoyf": None, "Cultivate": None}


def test_the_period_before_a_window_begins_exactly_that_far_back():
    recent = [(2, [(4, "Tarmogoyf")])] * 100
    # The week before the last one starts 14 days before now, to the second.
    assert trends(popular(recent + [("2026-09-16T12:00:00Z", [(4, "Cultivate")])] * 100), "7d", "all") == {"Tarmogoyf": "up"}
    assert trends(popular(recent + [("2026-09-16T11:59:59Z", [(4, "Cultivate")])] * 100), "7d", "all") == {"Tarmogoyf": None}
