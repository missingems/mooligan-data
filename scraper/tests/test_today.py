import json
from copy import deepcopy
from datetime import datetime, timezone

from mtgmeta.today import build_today, read_published, write_today

NOW = datetime(2026, 10, 3, 14, 41, 7, tzinfo=timezone.utc)
MOVER_FIELDS = ["name", "slug", "oracle_id", "scryfall_id", "set", "price", "previous", "change", "percent"]


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


def card_of(file):
    return file["interesting_card"]["card"]


def test_a_new_card_wins_over_a_released_card_even_when_the_released_card_has_more_decks():
    today = build_today({"modern": breakouts("modern", row("Old Staple", new=False, decks=90), row("Fresh Face", new=True, decks=6))}, None, NOW)
    assert card_of(today)["name"] == "Fresh Face"
    assert card_of(today)["kind"] == "new_card"


def test_exactly_one_card_is_published_when_several_new_cards_exist_across_formats():
    files = {
        "modern": breakouts("modern", row("A", decks=20), row("B", decks=30)),
        "legacy": breakouts("legacy", row("C", decks=25)),
    }
    today = build_today(files, None, NOW)
    assert isinstance(today["interesting_card"], dict)
    assert list(today["interesting_card"]) == ["card"]
    assert card_of(today)["name"] == "B"
    assert card_of(today)["format"] == "modern"


def pick(*files):
    return card_of(build_today({document["format"]: document for document in files}, None, NOW))


def test_a_card_new_in_two_formats_beats_a_card_new_in_one_format_with_more_decks():
    chosen = pick(
        breakouts("vintage", row("Fetchland", decks=47, top8=8)),
        breakouts("pioneer", row("Release", decks=5)),
        breakouts("standard", row("Release", decks=6)),
    )
    assert chosen["name"] == "Release"
    assert chosen["kind"] == "new_card"


def test_more_formats_win_first_then_summed_decks_then_summed_top8_then_name():
    assert pick(
        breakouts("modern", row("Three", decks=1), row("Two", decks=90)),
        breakouts("legacy", row("Three", decks=1), row("Two", decks=90)),
        breakouts("pauper", row("Three", decks=1)),
    )["name"] == "Three"
    # Equal formats: the decks over both decide, so 9 + 9 beats 12 + 5.
    assert pick(
        breakouts("modern", row("Even", decks=9), row("Lopsided", decks=12)),
        breakouts("legacy", row("Even", decks=9), row("Lopsided", decks=5)),
    )["name"] == "Even"
    # Equal formats and decks: the top 8s over both decide.
    assert pick(
        breakouts("modern", row("Few", decks=9, top8=1), row("Many", decks=9, top8=3)),
        breakouts("legacy", row("Few", decks=9, top8=1), row("Many", decks=9, top8=2)),
    )["name"] == "Many"
    # All equal: the name decides.
    assert pick(breakouts("modern", row("Zed"), row("Abe")))["name"] == "Abe"


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


def test_a_card_is_the_same_card_by_oracle_id_or_by_name_when_it_has_none():
    fetchland = breakouts("vintage", row("Fetchland", decks=47))
    assert pick(breakouts("modern", row("Release", decks=5)), breakouts("legacy", row("Release", decks=6)), fetchland)["name"] == "Release"
    nameless = [{key: value for key, value in row("Release", decks=5).items() if key != "oracle_id"} for _ in range(2)]
    assert pick(breakouts("modern", nameless[0]), breakouts("legacy", nameless[1]), fetchland)["name"] == "Release"
    # The same oracle id under another face name is still one card.
    faces = breakouts("legacy", row("Release // Other Face", decks=6, oracle_id="o-release"))
    assert pick(breakouts("modern", row("Release", decks=5, oracle_id="o-release")), faces, fetchland)["oracle_id"] == "o-release"


def test_the_released_card_step_ranks_the_same_way():
    chosen = pick(
        breakouts("vintage", row("Staple", new=False, decks=47)),
        breakouts("modern", row("Spread", new=False, decks=5)),
        breakouts("legacy", row("Spread", new=False, decks=5)),
    )
    assert (chosen["kind"], chosen["name"], chosen["format"]) == ("released_card", "Spread", "modern")


def test_the_released_card_fallback_applies_only_when_no_format_has_a_new_card():
    files = {
        "modern": breakouts("modern", row("Old A", new=False, decks=12), row("Old B", new=False, decks=15)),
        "pauper": breakouts("pauper", row("Old C", new=False, decks=9)),
    }
    card = card_of(build_today(files, None, NOW))
    assert (card["kind"], card["name"], card["format"]) == ("released_card", "Old B", "modern")


def test_with_no_breakouts_the_interesting_card_is_still_in_the_file_with_no_card():
    for files in ({}, {"modern": breakouts("modern")}):
        today = build_today(files, None, NOW)
        assert "interesting_card" in today
        assert today["interesting_card"] == {"card": None}


def test_the_card_kind_is_only_ever_new_card_or_released_card():
    kinds = {
        card_of(build_today({"modern": breakouts("modern", row("A", new=new))}, None, NOW))["kind"]
        for new in (True, False)
    }
    assert kinds == {"new_card", "released_card"}


def test_the_card_keeps_the_listed_fields_in_order_and_drops_the_rest():
    card = card_of(build_today({"modern": breakouts("modern", row("Psychic Frog", decks=61, top8=19, share=8.2, price=18.5))}, None, NOW))
    assert list(card) == [
        "kind", "format", "name", "oracle_id", "type", "decks", "share", "previous_share", "first_seen", "top8", "wins", "price",
    ]
    assert card["price"] == 18.5
    assert card["format"] == "modern"


def test_the_price_is_left_out_when_the_row_has_none():
    card = card_of(build_today({"modern": breakouts("modern", row("Psychic Frog"))}, None, NOW))
    assert "price" not in card
    assert {"results", "mainboard", "best_prestige", "new"}.isdisjoint(card)


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
    assert "history" not in today["movers"]["mover"] and "history" not in today["movers"]["loser"]
    assert file == snapshot


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


def test_without_new_printings_the_preview_is_present_and_has_no_card():
    assert build_today({}, None, NOW)["preview"] == {"card": None}
    assert build_today({"modern": breakouts("modern", row("A"))}, movers(gainers=[mover("Up")]), NOW)["preview"] == {"card": None}
    assert build_today({}, None, NOW, [])["preview"] == {"card": None}


def test_a_new_printing_fills_the_preview_and_leaves_the_rest_of_the_file_as_it_was():
    files, file = {"modern": breakouts("modern", row("Psychic Frog"))}, movers(gainers=[mover("Up")], losers=[mover("Down", 1.0, 2.0)])
    new = [{
        "id": "p-1", "name": "Fresh Face", "oracle_id": "o-fresh", "set": "trk", "set_name": "Track Set",
        "collector_number": "1", "released_at": "2026-09-01", "reprint": False,
    }]
    without, today = build_today(files, file, NOW), build_today(files, file, NOW, new)
    assert today["preview"]["card"]["name"] == "Fresh Face"
    assert today["preview"]["card"]["scryfall_id"] == "p-1"
    assert today["interesting_card"] == without["interesting_card"] and today["movers"] == without["movers"]
    assert list(today) == list(without) == ["schema", "generated_at", "interesting_card", "movers", "preview"]
    assert json.loads(json.dumps(today, ensure_ascii=False)) == today


def test_the_file_has_its_schema_and_time_and_round_trips_as_json():
    today = build_today(
        {"modern": breakouts("modern", row("Psychic Frog", price=18.5))}, movers(gainers=[mover("Up")], losers=[mover("Down", 1.0, 2.0)]), NOW
    )
    assert today["schema"] == 1
    assert today["generated_at"] == "2026-10-03T14:41:07Z"
    assert list(today) == ["schema", "generated_at", "interesting_card", "movers", "preview"]
    assert json.loads(json.dumps(today, ensure_ascii=False)) == today


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
