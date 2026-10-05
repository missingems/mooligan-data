import json
from copy import deepcopy
from datetime import datetime, timezone

from mtgmeta.today import build_today, read_published, rising_commander, write_today

NOW = datetime(2026, 10, 3, 14, 41, 7, tzinfo=timezone.utc)
MOVER_FIELDS = ["name", "slug", "oracle_id", "scryfall_id", "set", "price", "previous", "change", "percent", "history"]
CARD_FIELDS = [
    "format", "formats", "name", "oracle_id", "scryfall_id", "type", "decks", "share", "previous_share", "new", "first_seen", "top8", "wins", "price",
    "archetypes",
]
BEFORE = "2026-09-30T10:17:45Z"
AFTER = "2026-10-04T18:05:07Z"


def row(name, new=True, decks=10, top8=0, share=5.0, **extra):
    return {
        "name": name, "oracle_id": "o-" + name.lower().replace(" ", "-"), "type": "creature",
        "decks": decks, "share": share, "previous_share": 0.0 if new else 1.0, "new": new, "first_seen": "2026-09-28",
        "mainboard": decks, "top8": top8, "wins": 1, "best_prestige": 3, "results": [{"deck_id": "1"}], **extra,
    }


def breakouts(format, *cards):
    return {"schema": 1, "format": format, "generated_at": "2026-10-03T02:41:07Z", "deck_count": 700, "baseline_deck_count": 2400, "cards": list(cards)}


def mover(name, price=10.0, previous=5.0, **extra):
    return {
        "name": name, "slug": name.lower().replace(" ", "-"), "oracle_id": "o-" + name.lower(), "scryfall_id": "s-" + name.lower(),
        "set": "mh3", "price": price, "previous": previous, "change": round(price - previous, 2),
        "percent": round((price - previous) * 100 / previous, 1), "history": [previous, price], **extra,
    }


def movers(gainers=(), losers=(), week=None):
    windows = {"1d": {"gainers": list(gainers), "losers": list(losers)}, "7d": {"gainers": [], "losers": []}, "30d": {"gainers": [], "losers": []}}
    windows.update(week or {})
    return {"schema": 1, "format": "all", "generated_at": "2026-10-03T02:41:07Z", "price_day": "2026-10-02", "windows": windows}


def cards_of(*files):
    return build_today({document["format"]: document for document in files}, None, NOW)["breakouts"]


def names(*files):
    return [card["name"] for card in cards_of(*files)]


def pick(*files):
    return cards_of(*files)[0]


# ---- Breakouts


def test_up_to_three_cards_are_published_and_fewer_when_fewer_exist():
    four = breakouts("modern", row("A", decks=40), row("B", decks=30), row("C", decks=20), row("D", decks=10))
    assert names(four) == ["A", "B", "C"]
    assert names(breakouts("modern", row("A"), row("B"))) == ["A", "B"]


def test_the_best_card_of_each_of_three_formats_is_taken_before_a_second_card_of_one_format():
    files = (
        breakouts("modern", row("A", decks=50), row("B", decks=40)),
        breakouts("legacy", row("C", decks=30)),
        breakouts("pauper", row("D", decks=20)),
    )
    assert names(*files) == ["A", "C", "D"]


def test_a_released_card_of_a_third_format_beats_a_second_new_card_of_a_format_already_listed():
    files = (
        breakouts("modern", row("A", decks=50), row("B", decks=40)),
        breakouts("legacy", row("C", decks=30)),
        breakouts("pauper", row("D", new=False, decks=90)),
    )
    assert names(*files) == ["A", "C", "D"]
    assert [card["new"] for card in cards_of(*files)] == [True, True, False]


def test_a_card_counts_for_its_busiest_format_when_the_formats_are_counted():
    files = (
        breakouts("modern", row("X", decks=10), row("Y", decks=8)),
        breakouts("legacy", row("X", decks=30), row("Z", decks=6)),
        breakouts("pauper", row("W", decks=7)),
    )
    # X is a legacy card, so Y is modern's best and W pauper's; Z would be a second legacy card.
    assert names(*files) == ["X", "Y", "W"]
    assert pick(*files)["format"] == "legacy"


def test_a_format_is_repeated_only_when_fewer_than_three_formats_have_a_breakout():
    two = (
        breakouts("modern", row("A", decks=50), row("B", decks=40), row("C", decks=30)),
        breakouts("legacy", row("D", decks=20)),
    )
    assert names(*two) == ["A", "B", "D"]
    assert [card["format"] for card in cards_of(*two)] == ["modern", "modern", "legacy"]
    one = breakouts("modern", row("A", decks=50), row("B", decks=40), row("C", decks=30), row("D", decks=20))
    assert names(one) == ["A", "B", "C"]


def test_the_cards_keep_their_ranked_order_when_a_later_format_adds_its_card():
    files = (
        breakouts("modern", row("A", decks=50), row("B", decks=40)),
        breakouts("legacy", row("C", decks=30)),
    )
    assert names(*files) == ["A", "B", "C"]
    # New cards rank before released ones and the chosen cards stay in that order: Old C (legacy) is a third format, Old A is not.
    mixed = (
        breakouts("modern", row("Old A", new=False, decks=90), row("New B", decks=5)),
        breakouts("legacy", row("Old C", new=False, decks=80)),
        breakouts("pauper", row("New D", decks=4)),
    )
    assert names(*mixed) == ["New B", "New D", "Old C"]


def test_new_cards_come_before_released_cards_even_when_a_released_card_has_more_decks():
    today = build_today({"modern": breakouts("modern", row("Old Staple", new=False, decks=90), row("Fresh Face", new=True, decks=6))}, None, NOW)
    assert [card["name"] for card in today["breakouts"]] == ["Fresh Face", "Old Staple"]
    assert [card["new"] for card in today["breakouts"]] == [True, False]


def test_released_cards_fill_the_places_the_new_cards_leave():
    files = (
        breakouts("modern", row("New A", decks=5), row("Old A", new=False, decks=50), row("Old B", new=False, decks=40)),
        breakouts("legacy", row("New B", decks=6), row("Old C", new=False, decks=60)),
    )
    assert names(*files) == ["New B", "New A", "Old C"]


def test_cards_of_every_format_compete_and_the_decks_decide_when_each_is_in_one_format():
    files = (
        breakouts("modern", row("A", decks=20), row("B", decks=30)),
        breakouts("legacy", row("C", decks=25)),
    )
    assert names(*files) == ["B", "C", "A"]
    assert pick(*files)["format"] == "modern"


def test_a_card_new_in_two_formats_beats_a_card_new_in_one_format_with_more_decks():
    chosen = pick(
        breakouts("vintage", row("Fetchland", decks=47, top8=8)),
        breakouts("pioneer", row("Release", decks=5)),
        breakouts("standard", row("Release", decks=6)),
    )
    assert chosen["name"] == "Release"
    assert chosen["new"] is True


def test_more_formats_win_first_then_summed_decks_then_summed_top8_then_name():
    assert names(
        breakouts("modern", row("Three", decks=1), row("Two", decks=90)),
        breakouts("legacy", row("Three", decks=1), row("Two", decks=90)),
        breakouts("pauper", row("Three", decks=1)),
    ) == ["Three", "Two"]
    # Equal formats: the decks over both decide, so 9 + 9 beats 12 + 5.
    assert names(
        breakouts("modern", row("Even", decks=9), row("Lopsided", decks=12)),
        breakouts("legacy", row("Even", decks=9), row("Lopsided", decks=5)),
    ) == ["Even", "Lopsided"]
    # Equal formats and decks: the top 8s over both decide.
    assert names(
        breakouts("modern", row("Few", decks=9, top8=1), row("Many", decks=9, top8=3)),
        breakouts("legacy", row("Few", decks=9, top8=1), row("Many", decks=9, top8=2)),
    ) == ["Many", "Few"]
    # All equal: the name decides.
    assert names(breakouts("modern", row("Zed"), row("Abe"))) == ["Abe", "Zed"]


def test_the_row_and_format_are_those_of_the_cards_busiest_format():
    chosen = pick(
        breakouts("pioneer", row("Pompous", decks=9, top8=1)),
        breakouts("standard", row("Pompous", decks=11, top8=2)),
        breakouts("modern", row("Pompous", decks=14, top8=3, share=7.7)),
    )
    assert (chosen["format"], chosen["decks"], chosen["top8"], chosen["share"]) == ("modern", 14, 3, 7.7)


def test_a_cards_busiest_formats_tie_by_the_published_format_order_then_alphabetically():
    def home(*formats):
        return pick(*(breakouts(format, row("A", decks=7)) for format in formats))["format"]

    assert home("legacy", "pioneer", "modern") == "modern"
    assert home("legacy", "pioneer") == "pioneer"
    assert home("zeta", "alpha") == "alpha"
    assert home("zeta", "duel_commander") == "duel_commander"


def test_the_formats_list_every_format_that_has_the_card_with_the_busiest_first():
    chosen = pick(
        breakouts("modern", row("Pompous", decks=9)),
        breakouts("zeta", row("Pompous", decks=8)),
        breakouts("pioneer", row("Pompous", decks=14)),
        breakouts("legacy", row("Pompous", decks=11)),
        breakouts("alpha", row("Pompous", decks=7)),
    )
    assert chosen["format"] == "pioneer"
    assert chosen["formats"] == ["pioneer", "modern", "legacy", "alpha", "zeta"]
    assert pick(breakouts("modern", row("Alone")))["formats"] == ["modern"]


def test_a_card_is_the_same_card_by_oracle_id_or_by_name_when_it_has_none():
    fetchland = breakouts("vintage", row("Fetchland", decks=47))
    assert pick(breakouts("modern", row("Release", decks=5)), breakouts("legacy", row("Release", decks=6)), fetchland)["name"] == "Release"
    nameless = [{key: value for key, value in row("Release", decks=5).items() if key != "oracle_id"} for _ in range(2)]
    assert pick(breakouts("modern", nameless[0]), breakouts("legacy", nameless[1]), fetchland)["name"] == "Release"
    # The same oracle id under another face name is still one card.
    faces = breakouts("legacy", row("Release // Other Face", decks=6, oracle_id="o-release"))
    assert pick(breakouts("modern", row("Release", decks=5, oracle_id="o-release")), faces, fetchland)["oracle_id"] == "o-release"


def test_a_card_in_two_formats_is_listed_once():
    listed = cards_of(breakouts("modern", row("Release", decks=5)), breakouts("legacy", row("Release", decks=6)))
    assert [card["name"] for card in listed] == ["Release"]


def test_a_card_listed_among_the_new_cards_is_not_listed_again_among_the_released_ones():
    listed = cards_of(
        breakouts("modern", row("Release", decks=5)),
        breakouts("legacy", row("Release", new=False, decks=50), row("Other Old", new=False, decks=10)),
    )
    assert [card["name"] for card in listed] == ["Release", "Other Old"]
    # It shows the numbers of the format where it is new, and still lists the format where it is not.
    assert (listed[0]["format"], listed[0]["decks"], listed[0]["new"], listed[0]["formats"]) == ("modern", 5, True, ["modern", "legacy"])


def test_the_released_card_step_ranks_the_same_way():
    chosen = pick(
        breakouts("vintage", row("Staple", new=False, decks=47)),
        breakouts("modern", row("Spread", new=False, decks=5)),
        breakouts("legacy", row("Spread", new=False, decks=5)),
    )
    assert (chosen["new"], chosen["name"], chosen["format"]) == (False, "Spread", "modern")


def test_released_cards_are_shown_even_when_no_format_has_a_new_card():
    files = (
        breakouts("modern", row("Old A", new=False, decks=12), row("Old B", new=False, decks=15)),
        breakouts("pauper", row("Old C", new=False, decks=9)),
    )
    assert names(*files) == ["Old B", "Old A", "Old C"]
    assert pick(*files)["format"] == "modern"


def test_with_no_breakouts_the_section_is_still_in_the_file_and_is_empty():
    for files in ({}, {"modern": breakouts("modern")}):
        today = build_today(files, None, NOW)
        assert today["breakouts"] == []


def test_a_card_keeps_the_listed_fields_in_order_and_drops_the_rest():
    card = pick(breakouts("modern", row("Psychic Frog", decks=61, top8=19, share=8.2, price=18.5, scryfall_id="s-frog")))
    assert list(card) == CARD_FIELDS
    assert (card["price"], card["scryfall_id"], card["format"], card["formats"]) == (18.5, "s-frog", "modern", ["modern"])
    assert {"results", "mainboard", "best_prestige", "kind"}.isdisjoint(card)


def test_the_price_and_the_scryfall_id_are_left_out_when_the_row_has_none():
    card = pick(breakouts("modern", row("Psychic Frog")))
    assert "price" not in card and "scryfall_id" not in card
    assert list(card) == [field for field in CARD_FIELDS if field not in ("price", "scryfall_id")]


def result(archetype, archetype_id=None):
    return {"deck_id": "d", "archetype": archetype, "archetype_id": archetype_id}


def archetypes(*results, pages=None):
    document = build_today({"modern": breakouts("modern", row("A", results=list(results)))}, None, NOW, archetype_pages=pages)
    return document["breakouts"][0]["archetypes"]


def test_archetypes_count_the_decks_of_the_results_most_decks_first_then_name():
    assert archetypes(
        result("Zoo", "zoo"), result("Burn", "burn"), result("Burn", "burn"), result("Amulet", "amulet"), result("Zoo", "zoo")
    ) == [
        {"name": "Burn", "id": "burn", "decks": 2},
        {"name": "Zoo", "id": "zoo", "decks": 2},
        {"name": "Amulet", "id": "amulet", "decks": 1},
    ]


def test_at_most_three_archetypes_are_kept():
    found = archetypes(*(result(name, name.lower()) for name in ("D", "C", "B", "A")))
    assert [archetype["name"] for archetype in found] == ["A", "B", "C"]


def test_a_deck_with_no_archetype_id_is_left_out_even_when_a_tracked_archetype_has_its_name():
    found = archetypes(result("Izzet Prowess", "modern-izzet-prowess"), result("izzet prowess"), result("IZZET PROWESS"), result("Izzet Prowess"))
    assert found == [{"name": "Izzet Prowess", "id": "modern-izzet-prowess", "decks": 1}]


def test_decks_named_only_by_their_pilot_are_not_listed_whatever_their_number():
    found = archetypes(result("UR"), result("UR"), result("UR"), result("Izzet Prowess", "modern-izzet-prowess"))
    assert found == [{"name": "Izzet Prowess", "id": "modern-izzet-prowess", "decks": 1}]
    assert archetypes(result("UR"), result("UR", None), result("UR", "")) == []


def test_results_without_an_archetype_are_skipped_and_none_leaves_an_empty_list():
    assert archetypes(result("Burn", "burn"), result(None), result(""), {"deck_id": "x"}) == [{"name": "Burn", "id": "burn", "decks": 1}]
    assert archetypes(result(None), result("")) == []
    assert archetypes() == []
    assert pick(breakouts("modern", {key: value for key, value in row("A").items() if key != "results"}))["archetypes"] == []


def colored(archetype_id, colors, archetype=None):
    return {"deck_id": "d", "archetype": archetype or (archetype_id or "None").title(), "archetype_id": archetype_id, "colors": colors}


def test_an_archetype_has_the_colours_of_its_page():
    found = archetypes(result("Burn", "burn"), colored("zoo", ["R"]), pages={"burn": {"colors": ["R"]}, "zoo": {"colors": ["R", "G", "W"]}})
    assert found == [{"name": "Burn", "id": "burn", "decks": 1, "colors": ["R"]}, {"name": "Zoo", "id": "zoo", "decks": 1, "colors": ["W", "R", "G"]}]


def test_the_colours_of_a_page_come_before_those_of_the_results():
    assert archetypes(colored("burn", ["U"]), colored("burn", ["U"]), pages={"burn": {"colors": ["R"]}})[0]["colors"] == ["R"]


def test_the_colours_of_a_page_are_put_in_wubrg_order_once_each():
    page = {"colors": ["G", "U", "R", "U", "W", "G", "X", 5]}
    assert archetypes(result("Zoo", "zoo"), pages={"zoo": page})[0]["colors"] == ["W", "U", "R", "G"]


def test_no_colours_on_a_page_is_colourless_and_not_a_reason_to_look_further():
    found = archetypes(colored("eldrazi", ["R"]), colored("eldrazi", ["R"]), pages={"eldrazi": {"colors": []}})
    assert found == [{"name": "Eldrazi", "id": "eldrazi", "decks": 2, "colors": []}]


def test_without_a_page_the_most_common_colours_of_the_results_are_taken():
    found = archetypes(colored("zoo", ["R"]), colored("zoo", ["G", "R", "W"]), colored("zoo", ["R"]), colored("zoo", ["W", "G", "R"]), colored("zoo", ["R"]))
    assert found[0]["colors"] == ["R"]
    found = archetypes(colored("zoo", ["R", "W"]), colored("zoo", ["W", "R"]), colored("zoo", ["R"]))
    assert found[0]["colors"] == ["W", "R"]
    assert archetypes(colored("zoo", []), colored("zoo", []), colored("zoo", ["R"]))[0]["colors"] == []


def test_a_page_without_a_colours_list_or_that_cannot_be_read_falls_back_to_the_results():
    for page in ({}, {"name": "Zoo"}, {"colors": None}, {"colors": "RG"}, {"colors": {"R": 1}}, None):
        assert archetypes(colored("zoo", ["R", "G"]), pages={"zoo": page})[0]["colors"] == ["R", "G"]
    assert archetypes(colored("zoo", ["R", "G"]), pages={})[0]["colors"] == ["R", "G"]


def test_a_tie_goes_to_the_colours_listed_first_in_the_results():
    assert archetypes(colored("zoo", ["G"]), colored("zoo", ["R"]))[0]["colors"] == ["G"]
    assert archetypes(colored("zoo", ["R"]), colored("zoo", ["G"]), colored("zoo", ["G"]), colored("zoo", ["R"]))[0]["colors"] == ["R"]
    assert archetypes(colored("zoo", []), colored("zoo", ["R"]))[0]["colors"] == []


def test_the_results_of_other_archetypes_and_of_no_colours_are_not_counted():
    found = archetypes(
        colored("zoo", ["R"]), colored("burn", ["U"]), colored("burn", ["U"]), colored("zoo", None), colored("zoo", None),
        {"deck_id": "d", "archetype": "Zoo", "archetype_id": "zoo"}, colored("zoo", "R"), colored(None, ["W"]), colored("", ["W"]),
    )
    assert [(archetype["id"], archetype["colors"]) for archetype in found] == [("zoo", ["R"]), ("burn", ["U"])]


def test_colours_are_left_out_when_nothing_is_known_of_them():
    assert archetypes(result("Zoo", "zoo"), colored("burn", None), pages={"zoo": {}}) == [
        {"name": "Burn", "id": "burn", "decks": 1},
        {"name": "Zoo", "id": "zoo", "decks": 1},
    ]


def test_write_today_reads_the_archetype_pages_from_the_archetypes_folder(tmp_path):
    (tmp_path / "breakouts").mkdir()
    (tmp_path / "archetypes").mkdir()
    (tmp_path / "breakouts" / "modern.json").write_text(json.dumps(breakouts("modern", row(
        "A", results=[result("Burn", "burn"), result("Zoo", "zoo"), colored("amulet", ["G"]), colored("amulet", ["G"])]
    ))))
    (tmp_path / "archetypes" / "burn.json").write_text(json.dumps({"colors": ["R"]}))
    (tmp_path / "archetypes" / "zoo.json").write_text("{not json")
    (tmp_path / "archetypes" / "amulet.json").write_text(json.dumps({"colors": ["U", "G"]}))
    write_today(tmp_path, NOW)
    found = read_today(tmp_path)["breakouts"][0]["archetypes"]
    assert [(archetype["id"], archetype.get("colors")) for archetype in found] == [("amulet", ["U", "G"]), ("burn", ["R"]), ("zoo", None)]


# ---- Movers


def test_the_biggest_mover_and_loser_are_the_first_of_the_last_day_as_published():
    file = movers(
        gainers=[mover("Rises Most", 20.0, 10.0), mover("Rises Less", 9.0, 8.0)],
        losers=[mover("Falls Most", 1.0, 5.0), mover("Falls Less", 4.0, 5.0)],
    )
    snapshot = deepcopy(file)
    today = build_today({}, file, NOW)
    assert today["movers"]["price_day"] == "2026-10-02"
    assert list(today["movers"]) == ["price_day", "mover", "loser"]
    assert today["movers"]["mover"] == {key: snapshot["windows"]["1d"]["gainers"][0][key] for key in MOVER_FIELDS}
    assert today["movers"]["loser"] == {key: snapshot["windows"]["1d"]["losers"][0][key] for key in MOVER_FIELDS}
    assert list(today["movers"]["mover"]) == MOVER_FIELDS
    assert file == snapshot


def test_the_price_history_is_copied_with_the_mover():
    history = [0.47, None, 0.5, 1.22]
    today = build_today({}, movers(gainers=[mover("Up", history=history)], losers=[mover("Down", 1.0, 2.0)]), NOW)
    assert today["movers"]["mover"]["history"] == history
    assert today["movers"]["loser"]["history"] == [2.0, 1.0]
    # A card the file has no history for just has none.
    bare = {key: value for key, value in mover("Up").items() if key != "history"}
    assert "history" not in build_today({}, movers(gainers=[bare]), NOW)["movers"]["mover"]


def test_values_are_copied_not_recomputed():
    odd = mover("Odd Math", 10.0, 5.0, change=99.0, percent=1.5)
    assert build_today({}, movers(gainers=[odd]), NOW)["movers"]["mover"]["change"] == 99.0
    assert build_today({}, movers(gainers=[odd]), NOW)["movers"]["mover"]["percent"] == 1.5


def test_the_week_and_the_month_never_change_the_pair():
    week = {
        "7d": {"gainers": [mover("Week Gainer", 90.0, 10.0)], "losers": [mover("Week Loser", 1.0, 50.0)]},
        "30d": {"gainers": [mover("Month Gainer", 90.0, 10.0)], "losers": [mover("Month Loser", 1.0, 50.0)]},
    }
    plain = build_today({}, movers(gainers=[mover("Day Gainer")], losers=[mover("Day Loser", 1.0, 2.0)]), NOW)
    with_longer = build_today({}, movers(gainers=[mover("Day Gainer")], losers=[mover("Day Loser", 1.0, 2.0)], week=week), NOW)
    assert with_longer == plain
    assert (plain["movers"]["mover"]["name"], plain["movers"]["loser"]["name"]) == ("Day Gainer", "Day Loser")
    # A week with moves but a day with none is nulls, not the week's pair.
    only_week = build_today({}, movers(week=week), NOW)
    assert (only_week["movers"]["mover"], only_week["movers"]["loser"]) == (None, None)


def test_a_missing_movers_file_is_a_movers_section_of_nulls():
    assert build_today({}, None, NOW)["movers"] == {"price_day": None, "mover": None, "loser": None}


def test_empty_day_lists_are_nulls_and_one_side_can_be_empty():
    assert build_today({}, movers(), NOW)["movers"] == {"price_day": "2026-10-02", "mover": None, "loser": None}
    half = build_today({}, movers(gainers=[mover("Up")]), NOW)["movers"]
    assert half["mover"]["name"] == "Up" and half["loser"] is None
    assert build_today({}, {"price_day": "2026-10-02", "windows": {}}, NOW)["movers"]["mover"] is None


# ---- The rising commander


def state(decks, checked_at=AFTER):
    return {"decks": decks, "checked_at": checked_at}


def section(tag, *cards):
    return {"tag": tag, "header": tag, "cards": [{"name": name, "decks": decks, "of_decks": of_decks, "synergy": synergy} for name, decks, of_decks, synergy in cards]}


def rise(previous, decks, **pages):
    """The rising commander for one commander (`c`) that had `previous` decks when last checked and has `decks` now."""
    return rising_commander({"c": state(decks)}, {"c": state(previous, BEFORE)}, pages)


def commander_page(*sections, decks=1000):
    return {"name": "Commander", "slug": "c", "decks": decks, "sections": list(sections)}


def test_there_is_no_commander_without_a_snapshot_to_compare_with():
    assert rising_commander({"c": state(500)}, None, {}) is None
    assert rising_commander({"c": state(500)}, {}, {}) is None


def test_a_rise_must_clear_the_floor_of_decks_rise_and_percent():
    # At least 50 decks now.
    assert rise(40, 50) is not None
    assert rise(39, 49) is None
    # At least 10 decks more (both are over 10 percent and 50 decks).
    assert rise(50, 60) is not None
    assert rise(51, 60) is None
    # At least 10 percent (both are over 10 decks and 50 decks).
    assert rise(1000, 1100) is not None
    assert rise(1000, 1099) is None
    # A fall is no rise.
    assert rise(60, 50) is None


def test_only_a_commander_checked_again_since_the_snapshot_can_rise():
    snapshot = {"c": state(100, BEFORE)}
    assert rising_commander({"c": state(200, BEFORE)}, snapshot, {}) is None
    assert rising_commander({"c": state(200, AFTER)}, snapshot, {})["slug"] == "c"


def test_a_commander_missing_from_the_snapshot_has_no_rise():
    assert rising_commander({"new": state(500)}, {"other": state(100, BEFORE)}, {}) is None
    assert rising_commander({"new": state(500), "old": state(120)}, {"old": state(100, BEFORE)}, {})["slug"] == "old"


def test_a_commander_without_counts_to_compare_is_skipped():
    assert rising_commander({"c": {"decks": None, "checked_at": AFTER}}, {"c": state(100, BEFORE)}, {}) is None
    assert rising_commander({"c": state(100)}, {"c": {"decks": 0, "checked_at": BEFORE}}, {}) is None
    assert rising_commander({"c": state(100)}, {"c": {"checked_at": BEFORE}}, {}) is None


def test_commanders_rank_by_percent_then_rise_then_slug_over_the_same_days():
    snapshot = {slug: state(before, BEFORE) for slug, before in {"a": 100, "b": 100, "big": 1000, "small": 100, "c": 100}.items()}
    checked = {"a": state(130), "b": state(160), "big": state(1500), "small": state(150), "c": state(120)}
    # 60% (b), then 50% twice (big with the larger rise, then small), then 30% (a), then 20% (c).
    assert rising_commander(checked, snapshot, {})["slug"] == "b"
    del checked["b"]
    assert rising_commander(checked, snapshot, {})["slug"] == "big"
    del checked["big"]
    assert rising_commander(checked, snapshot, {})["slug"] == "small"
    # The same percent and the same rise: the slug decides.
    tied = rising_commander({"zed": state(150), "abe": state(150)}, {"zed": state(100, BEFORE), "abe": state(100, BEFORE)}, {})
    assert tied["slug"] == "abe"


def between(slug_states):
    """The rising commander for `{slug: (previous decks, check time, decks now, check time)}`."""
    checked = {slug: state(decks, after) for slug, (_, _, decks, after) in slug_states.items()}
    snapshot = {slug: state(previous, before) for slug, (previous, before, _, _) in slug_states.items()}
    return rising_commander(checked, snapshot, {})


def days_between(before, after):
    return between({"c": (100, before, 200, after)})["days"]


def test_the_days_are_those_between_the_dates_of_the_two_checks_at_least_one():
    assert days_between("2026-09-30T10:17:45Z", "2026-10-04T18:05:07Z") == 4
    assert days_between("2026-10-04T10:00:00Z", "2026-10-05T10:00:00Z") == 1
    # Dates, not hours: a few minutes across midnight is a day, and nearly three days of hours is three days.
    assert days_between("2026-10-04T23:59:00Z", "2026-10-05T00:01:00Z") == 1
    assert days_between("2026-10-01T23:00:00Z", "2026-10-04T01:00:00Z") == 3
    # The same day, however many hours apart, is one day.
    assert days_between("2026-10-04T01:00:00Z", "2026-10-04T23:00:00Z") == 1
    # Missing or unparseable check times are one day, and so is a check dated before the snapshot's.
    assert days_between(None, AFTER) == 1
    assert days_between("", AFTER) == 1
    assert days_between("sometime", AFTER) == 1
    assert days_between(BEFORE, "garbage") == 1
    assert days_between("2026-10-06T00:00:00Z", "2026-10-04T00:00:00Z") == 1


def test_a_smaller_percent_over_fewer_days_beats_a_larger_percent_over_many_days():
    first = between({
        "slow": (100, "2026-09-24T10:00:00Z", 160, AFTER),  # 60 percent over 10 days: 6 a day
        "quick": (100, "2026-10-03T10:00:00Z", 130, AFTER),  # 30 percent over 1 day: 30 a day
    })
    assert first["slug"] == "quick"
    assert (first["rise_percent"], first["days"], first["rise_percent_per_day"]) == (30.0, 1, 30.0)


def test_commanders_with_the_same_percent_a_day_go_to_the_larger_rise_a_day_then_the_larger_rise_then_the_slug():
    day = "2026-10-03T10:00:00Z"
    # 50 percent a day each; 500 decks a day beats 50.
    assert between({"small": (100, day, 150, AFTER), "big": (1000, day, 1500, AFTER)})["slug"] == "big"
    # 50 percent and 50 decks a day each; the rise of 100 over two days beats the rise of 50 over one.
    two_days = "2026-10-02T10:00:00Z"
    assert between({"one": (100, day, 150, AFTER), "two": (100, two_days, 200, AFTER)})["slug"] == "two"
    # Everything the same: the slug decides.
    assert between({"zed": (100, day, 150, AFTER), "abe": (100, day, 150, AFTER)})["slug"] == "abe"


def test_the_floors_apply_to_the_whole_rise_not_to_the_rise_a_day():
    day = "2026-10-03T10:00:00Z"
    # Under 10 percent in all (9 percent in one day), though the best a day.
    assert between({"c": (1000, day, 1090, AFTER)}) is None
    # Under 10 decks in all (9 decks and 16 percent in one day).
    assert between({"c": (55, day, 64, AFTER)}) is None
    # Over both floors in all, though the rise a day is small.
    slow = between({"c": (100, "2026-09-24T10:00:00Z", 112, AFTER)})
    assert (slow["slug"], slow["rise"], slow["days"], slow["rise_percent_per_day"]) == ("c", 12, 10, 1.2)
    # The excluded commander never wins, however good its rise a day.
    both = between({"excluded": (1000, day, 1090, AFTER), "slow": (100, "2026-09-24T10:00:00Z", 112, AFTER)})
    assert both["slug"] == "slow"


def test_the_rise_a_day_is_rounded_to_one_decimal_and_the_percent_a_day_to_two():
    commander = between({"c": (100, "2026-10-01T10:00:00Z", 135, AFTER)})
    assert (commander["days"], commander["rise"], commander["rise_percent"]) == (3, 35, 35.0)
    assert (commander["rise_per_day"], commander["rise_percent_per_day"]) == (11.7, 11.67)


def test_the_commander_has_its_fields_in_order():
    page = {
        "name": "Avacyn, Angel of Horror", "slug": "c", "decks": 1722, "url": "https://edhrec.com/commanders/avacyn-angel-of-horror",
        "scryfall_id": "ff65", "color_identity": ["B"], "sections": [],
    }
    commander = rise(1147, 1722, c=page)
    assert list(commander) == [
        "slug", "name", "scryfall_id", "color_identity", "decks", "previous_decks", "rise", "rise_percent", "since", "days",
        "rise_per_day", "rise_percent_per_day", "url", "top_cards", "synergy_cards", "attribution",
    ]
    assert commander["slug"] == "c" and commander["name"] == "Avacyn, Angel of Horror"
    assert (commander["scryfall_id"], commander["color_identity"]) == ("ff65", ["B"])
    assert (commander["decks"], commander["previous_decks"], commander["rise"], commander["rise_percent"]) == (1722, 1147, 575, 50.1)
    assert commander["since"] == "2026-09-30"
    assert (commander["days"], commander["rise_per_day"], commander["rise_percent_per_day"]) == (4, 143.8, 12.53)
    assert commander["url"] == "https://edhrec.com/commanders/avacyn-angel-of-horror"
    assert commander["attribution"] == {"name": "EDHREC", "url": "https://edhrec.com"}


def test_the_percent_is_rounded_to_one_decimal():
    assert rise(330, 414)["rise_percent"] == 25.5
    assert rise(2184, 2893)["rise_percent"] == 32.5


def test_a_commander_without_a_page_has_its_url_from_the_slug_and_no_id_or_colours():
    commander = rise(100, 200)
    assert commander["url"] == "https://edhrec.com/commanders/c"
    assert commander["scryfall_id"] is None and commander["color_identity"] is None
    assert commander["name"] == "c"
    assert (commander["top_cards"], commander["synergy_cards"]) == ([], [])
    # An older page has neither field; colourless is an empty list, which is kept.
    assert rise(100, 200, c={"name": "Old", "sections": []})["color_identity"] is None
    assert rise(100, 200, c={"name": "Colourless", "color_identity": []})["color_identity"] == []


def test_the_top_cards_are_the_first_three_of_the_top_cards_section_with_their_share():
    page = commander_page(
        section("newcards", ("New", 5, 1722, 0.1)),
        section("topcards", ("Dark Ritual", 1459, 1722, 0.17), ("Gray Merchant", 1445, 1722, 0.34), ("Jet Medallion", 1315, 1722, 0.14), ("Fourth", 1000, 1722, 0.1)),
    )
    assert rise(1147, 1722, c=page)["top_cards"] == [
        {"name": "Dark Ritual", "decks": 1459, "share": 84.7, "synergy": 0.17},
        {"name": "Gray Merchant", "decks": 1445, "share": 83.9, "synergy": 0.34},
        {"name": "Jet Medallion", "decks": 1315, "share": 76.4, "synergy": 0.14},
    ]


def test_a_card_without_a_synergy_score_has_a_null_one_and_its_share_falls_back_to_the_pages_decks():
    page = commander_page(section("topcards", ("Plain", 250, None, None)), decks=1000)
    assert rise(100, 200, c=page)["top_cards"] == [{"name": "Plain", "decks": 250, "share": 25.0, "synergy": None}]


def test_the_synergy_cards_prefer_high_synergy_over_high_lift_and_accept_either():
    both = commander_page(
        section("highliftcards", ("Lift", 10, 100, 0.5)),
        section("highsynergycards", ("Synergy", 20, 100, 0.6)),
    )
    assert [card["name"] for card in rise(100, 200, c=both)["synergy_cards"]] == ["Synergy"]
    lift = commander_page(section("highliftcards", ("Lift", 10, 100, 0.5)))
    assert rise(100, 200, c=lift)["synergy_cards"] == [{"name": "Lift", "decks": 10, "share": 10.0, "synergy": 0.5}]
    assert rise(100, 200, c=lift)["top_cards"] == []


def test_the_card_lists_are_empty_when_the_page_has_no_such_section():
    commander = rise(100, 200, c=commander_page(section("creatures", ("Bear", 10, 100, 0.0))))
    assert (commander["top_cards"], commander["synergy_cards"]) == ([], [])


# ---- The whole file


def test_without_new_printings_the_preview_is_present_and_has_no_card():
    assert build_today({}, None, NOW)["preview"] == {"card": None}
    assert build_today({"modern": breakouts("modern", row("A"))}, movers(gainers=[mover("Up")]), NOW)["preview"] == {"card": None}
    assert build_today({}, None, NOW, [])["preview"] == {"card": None}


def test_a_new_printing_fills_the_preview_and_leaves_the_rest_of_the_file_as_it_was():
    files, file = {"modern": breakouts("modern", row("Psychic Frog"))}, movers(gainers=[mover("Up")], losers=[mover("Down", 1.0, 2.0)])
    new = [{
        "id": "p-1", "name": "Fresh Face", "oracle_id": "o-fresh", "set": "trk", "set_name": "Track Set",
        "collector_number": "1", "released_at": "2026-11-20", "reprint": False,
    }]
    without, today = build_today(files, file, NOW), build_today(files, file, NOW, new)
    assert today["preview"]["card"]["name"] == "Fresh Face"
    assert today["preview"]["card"]["scryfall_id"] == "p-1"
    assert today["breakouts"] == without["breakouts"] and today["movers"] == without["movers"]
    assert list(today) == list(without) == ["schema", "generated_at", "breakouts", "movers", "commander", "preview"]
    assert json.loads(json.dumps(today, ensure_ascii=False)) == today


def test_the_file_has_its_schema_and_time_and_exactly_its_five_sections_and_round_trips_as_json():
    commander = rise(100, 200)
    today = build_today(
        {"modern": breakouts("modern", row("Psychic Frog", price=18.5))}, movers(gainers=[mover("Up")], losers=[mover("Down", 1.0, 2.0)]), NOW,
        commander=commander,
    )
    assert today["schema"] == 2
    assert today["generated_at"] == "2026-10-03T14:41:07Z"
    assert list(today) == ["schema", "generated_at", "breakouts", "movers", "commander", "preview"]
    assert today["commander"] == commander
    assert "interesting_card" not in today
    assert json.loads(json.dumps(today, ensure_ascii=False)) == today
    assert build_today({}, None, NOW)["commander"] is None


def test_read_published_reads_breakouts_and_movers_from_a_work_directory(tmp_path):
    assert read_published(tmp_path) == ({}, None)
    (tmp_path / "breakouts").mkdir()
    (tmp_path / "movers").mkdir()
    (tmp_path / "breakouts" / "modern.json").write_text(json.dumps(breakouts("modern", row("A"))))
    (tmp_path / "breakouts" / "legacy.json").write_text(json.dumps(breakouts("legacy")))
    (tmp_path / "movers" / "modern.json").write_text(json.dumps(movers(gainers=[mover("Not All")])))
    found, all_movers = read_published(tmp_path)
    assert set(found) == {"modern", "legacy"} and all_movers is None
    (tmp_path / "movers" / "all.json").write_text(json.dumps(movers(gainers=[mover("Up")])))
    assert read_published(tmp_path)[1]["windows"]["1d"]["gainers"][0]["name"] == "Up"


def test_write_today_writes_compact_json_and_names_the_file(tmp_path):
    (tmp_path / "breakouts").mkdir()
    (tmp_path / "movers").mkdir()
    (tmp_path / "breakouts" / "modern.json").write_text(json.dumps(breakouts("modern", row("Élan Vital"))), encoding="utf-8")
    (tmp_path / "movers" / "all.json").write_text(json.dumps(movers(gainers=[mover("Up")], losers=[mover("Down", 1.0, 2.0)])))
    assert write_today(tmp_path, NOW) == ["today.json"]
    text = (tmp_path / "today.json").read_text(encoding="utf-8")
    assert ": " not in text and ", " not in text and "Élan Vital" in text
    assert json.loads(text) == build_today(*read_published(tmp_path), NOW)


# ---- The commander snapshot


def write_state(directory, checked=None, snapshot=None):
    (directory / "state").mkdir(exist_ok=True)
    if checked is not None:
        (directory / "state" / "edhrec-commanders.json").write_text(json.dumps(checked))
    if snapshot is not None:
        text = snapshot if isinstance(snapshot, str) else json.dumps({"schema": 1, "commanders": snapshot})
        (directory / "state" / "today-commanders.json").write_text(text)


def read_today(directory):
    return json.loads((directory / "today.json").read_text())


def read_snapshot(directory):
    return json.loads((directory / "state" / "today-commanders.json").read_text())


def test_write_today_adds_the_rising_commander_and_keeps_this_runs_counts_for_the_next(tmp_path):
    write_state(
        tmp_path,
        checked={"avacyn": state(1722), "steady": state(500), "unseen": state(300)},
        snapshot={"avacyn": state(1147, BEFORE), "steady": state(500, BEFORE)},
    )
    (tmp_path / "edh" / "commanders").mkdir(parents=True)
    (tmp_path / "edh" / "commanders" / "avacyn.json").write_text(json.dumps({
        "name": "Avacyn, Angel of Horror", "slug": "avacyn", "decks": 1722, "url": "https://edhrec.com/commanders/avacyn",
        "color_identity": ["B"], "scryfall_id": "ff65",
        "sections": [section("topcards", ("Dark Ritual", 1459, 1722, 0.17))],
    }))
    write_today(tmp_path, NOW)
    commander = read_today(tmp_path)["commander"]
    assert (commander["slug"], commander["name"], commander["rise"], commander["since"]) == ("avacyn", "Avacyn, Angel of Horror", 575, "2026-09-30")
    assert commander["top_cards"][0]["name"] == "Dark Ritual"
    # Every commander with a count is kept, none of them as an old count.
    assert read_snapshot(tmp_path) == {"schema": 1, "commanders": {"avacyn": state(1722), "steady": state(500), "unseen": state(300)}}


def test_write_today_keeps_the_snapshot_even_when_no_commander_qualifies(tmp_path):
    write_state(tmp_path, checked={"a": state(101), "b": state(30)}, snapshot={"a": state(100, BEFORE), "b": state(29, BEFORE)})
    write_today(tmp_path, NOW)
    assert read_today(tmp_path)["commander"] is None
    assert read_snapshot(tmp_path) == {"schema": 1, "commanders": {"a": state(101), "b": state(30)}}


def test_the_first_run_has_no_commander_and_leaves_a_snapshot_for_the_next(tmp_path):
    write_state(tmp_path, checked={"avacyn": state(1722), "bad": {"decks": None, "checked_at": AFTER}})
    write_today(tmp_path, NOW)
    assert read_today(tmp_path)["commander"] is None
    assert read_snapshot(tmp_path) == {"schema": 1, "commanders": {"avacyn": state(1722)}}


def test_an_unreadable_snapshot_is_no_commander_and_is_replaced(tmp_path):
    write_state(tmp_path, checked={"avacyn": state(1722)}, snapshot="{not json")
    write_today(tmp_path, NOW)
    assert read_today(tmp_path)["commander"] is None
    assert read_snapshot(tmp_path)["commanders"] == {"avacyn": state(1722)}


def test_a_snapshot_of_another_shape_is_no_commander_and_is_replaced(tmp_path):
    for text in ("[]", '{"commanders": []}', '{"commanders": {"avacyn": 1147}}'):
        write_state(tmp_path, checked={"avacyn": state(1722)}, snapshot=text)
        write_today(tmp_path, NOW)
        assert read_today(tmp_path)["commander"] is None
        assert read_snapshot(tmp_path)["commanders"] == {"avacyn": state(1722)}


def test_without_the_edhrec_state_there_is_no_commander_and_the_snapshot_is_left_alone(tmp_path):
    write_state(tmp_path, snapshot={"avacyn": state(1147, BEFORE)})
    before = (tmp_path / "state" / "today-commanders.json").read_text()
    write_today(tmp_path, NOW)
    assert read_today(tmp_path)["commander"] is None
    assert (tmp_path / "state" / "today-commanders.json").read_text() == before
    # With no state directory at all, none is made.
    empty = tmp_path / "empty"
    empty.mkdir()
    write_today(empty, NOW)
    assert not (empty / "state").exists()


def test_colour_letters_that_are_not_strings_are_ignored():
    from mtgmeta.today import _wubrg
    assert _wubrg(["R", ["U"], None, 3, "W", "R"]) == ["W", "R"]
