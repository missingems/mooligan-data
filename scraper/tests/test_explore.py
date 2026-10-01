from datetime import datetime, timezone

from mtgmeta.explore import build_explore, deck_key_cards, prestige

NOW = datetime(2026, 9, 30, 2, tzinfo=timezone.utc)


def archetype(id, percentage, deck_count=10, colors=None, key_cards=None):
    return {
        "name": id.replace("-", " ").title(),
        "id": id,
        "percentage": percentage,
        "deck_count": deck_count,
        "colors": ["R", "W"] if colors is None else colors,
        "key_cards": [{"name": f"Card {n}", "oracle_id": f"o{n}"} for n in range(3)] if key_cards is None else key_cards,
    }


def result(date, finish, deck_id="1", event_id="1"):
    return {"deck_id": deck_id, "date": f"{date}T00:00:00Z", "player": "p", "event_id": event_id, "event_name": "E", "finish": finish}


def event(event_id, name, date, finishes, kind="mtgo_challenge", source="mtgo.com", archetype_id="a"):
    return {
        "event_id": event_id,
        "event_name": name,
        "date": f"{date}T00:00:00Z",
        "url": f"https://www.mtggoldfish.com/tournament/{event_id}",
        "kind": kind,
        "source": source,
        "results": [
            {
                "finish": finish,
                "player": f"player{n}",
                "archetype": "Boros Energy" if n == 0 else "Other Deck",
                "archetype_id": archetype_id if n == 0 else None,
                "deck_id": str(n),
            }
            for n, finish in enumerate(finishes)
        ],
    }


def snapshot(meta30, meta7=None, archetypes=None, events=None, meta14=None):
    meta = {"30d": {"archetypes": meta30}}
    if meta7 is not None:
        meta["7d"] = {"archetypes": meta7}
    if meta14 is not None:
        meta["14d"] = {"archetypes": meta14}
    return {"meta": meta, "archetypes": archetypes or {}, "events": events or []}


def modern(decks=None, catalog=None, **kwargs):
    return build_explore({"modern": snapshot(**kwargs)}, NOW, {"modern": decks or {}}, catalog)["formats"][0]


def stored(*cards):
    """A stored decklist's mainboard, as the store keeps it: [quantity, name] pairs."""
    return {"m": [list(card) for card in cards], "s": [[4, "Sideboard Card"]]}


# What the Scryfall catalog gives: its name and oracle id, and "land" for a land.
CATALOG = {
    "ragavan-nimble-pilferer": {"name": "Ragavan, Nimble Pilferer", "oracle_id": "o-ragavan"},
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "o-bolt"},
    "ocelot-pride": {"name": "Ocelot Pride", "oracle_id": "o-ocelot"},
    "sideboard-card": {"name": "Sideboard Card", "oracle_id": "o-side"},
    "mountain": {"name": "Mountain", "oracle_id": "o-mountain", "land": True},
    "arid-mesa": {"name": "Arid Mesa", "oracle_id": "o-mesa", "land": True},
}


def test_formats_come_in_the_apps_order_and_skip_what_is_missing():
    empty = snapshot([archetype("a", 1.0)])
    explore = build_explore({"vintage": empty, "modern": empty, "premodern": empty, "standard": empty}, NOW)
    assert explore["generated_at"] == "2026-09-30T02:00:00Z"
    assert [(f["format"], f["name"]) for f in explore["formats"]] == [("standard", "Standard"), ("modern", "Modern"), ("vintage", "Vintage")]


def test_standings_are_the_top_eight_by_thirty_day_share():
    entries = [archetype(f"a{n}", n / 10) for n in range(1, 13)]  # 0.1 ... 1.2, in a scrambled order
    entries = entries[6:] + entries[:6]
    standings = modern(meta30=entries)["standings"]
    assert [s["id"] for s in standings] == ["a12", "a11", "a10", "a9", "a8", "a7", "a6", "a5"]
    assert standings[0]["share_30d"] == 1.2


def test_share_is_one_decimal_and_the_seven_day_share_is_null_without_data():
    both = modern(meta30=[archetype("a", 9.87, deck_count=120), archetype("b", 5.0)], meta7=[archetype("a", 11.04)])["standings"]
    assert (both[0]["share_30d"], both[0]["share_7d"], both[0]["deck_count_30d"]) == (9.9, 11.0, 120)
    assert both[1]["share_7d"] is None  # not in the 7-day window
    assert modern(meta30=[archetype("a", 9.0)])["standings"][0]["share_7d"] is None  # no 7-day window at all


def test_each_window_lists_its_own_top_eight_by_its_own_share():
    month = [archetype(f"a{n}", n / 10, deck_count=n) for n in range(1, 13)]
    week = [archetype(f"a{n}", (13 - n) / 10, deck_count=100 + n) for n in range(1, 13)]  # the reverse order
    fortnight = week[6:] + week[:6]
    by_window = modern(meta30=month, meta14=fortnight, meta7=week)["standings_by_window"]
    assert list(by_window) == ["7d", "14d", "30d"]
    assert [s["id"] for s in by_window["30d"]] == ["a12", "a11", "a10", "a9", "a8", "a7", "a6", "a5"]
    assert [s["id"] for s in by_window["7d"]] == ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"]
    assert [s["id"] for s in by_window["14d"]] == ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"]
    # A window's own share and deck count, never the month's.
    assert (by_window["7d"][0]["share"], by_window["7d"][0]["deck_count"]) == (1.2, 101)
    assert (by_window["30d"][0]["share"], by_window["30d"][0]["deck_count"]) == (1.2, 12)


def test_the_thirty_day_list_matches_the_older_standings_field_and_the_field_stays_as_it_was():
    entries = [archetype("a", 9.87, deck_count=120, colors=["U"]), archetype("b", 5.0, deck_count=None, key_cards=[])]
    document = modern(meta30=entries, meta7=[archetype("a", 11.04)])
    old, new = document["standings"], document["standings_by_window"]["30d"]
    assert set(old[0]) == {"id", "name", "share_30d", "share_7d", "deck_count_30d", "top8_30d", "wins_30d", "colors", "key_cards"}
    assert [(o["id"], o["name"], o["share_30d"], o["deck_count_30d"], o["colors"], o["key_cards"]) for o in old] == [
        (n["id"], n["name"], n["share"], n["deck_count"], n["colors"], n["key_cards"]) for n in new
    ]
    assert set(new[0]) == {"id", "name", "share", "deck_count", "top8", "wins", "trend", "colors", "key_cards"}
    assert new[1]["deck_count"] is None and new[1]["key_cards"] == [] and new[0]["colors"] == ["U"]
    assert [k["oracle_id"] for k in new[0]["key_cards"]] == ["o0", "o1"]  # the first two


def test_a_window_with_no_data_is_an_empty_list():
    by_window = modern(meta30=[archetype("a", 5.0)])["standings_by_window"]
    assert by_window["7d"] == [] and by_window["14d"] == []
    assert [s["id"] for s in by_window["30d"]] == ["a"]
    assert modern(meta30=[])["standings_by_window"] == {"7d": [], "14d": [], "30d": []}


def test_each_windows_trend_compares_it_with_the_next_longer_one():
    # 7d against 14d, 14d against 30d, and 30d against the last week.
    week = [archetype("up", 12.0), archetype("down", 3.0), archetype("flat", 8.0), archetype("edge", 9.0), archetype("new", 4.0)]
    fortnight = [archetype("up", 10.0), archetype("down", 5.0), archetype("flat", 8.5), archetype("edge", 8.0), archetype("gone", 2.0)]
    month = [archetype("up", 8.0), archetype("down", 6.0), archetype("flat", 8.0), archetype("edge", 8.0), archetype("new", 1.0), archetype("gone", 5.0)]
    by_window = modern(meta30=month, meta14=fortnight, meta7=week)["standings_by_window"]
    trends = {window: {s["id"]: s["trend"] for s in standings} for window, standings in by_window.items()}
    assert trends["7d"] == {"up": "up", "down": "down", "flat": None, "edge": None, "new": None}  # exactly a point is not more; "new" has no 14d share
    assert trends["14d"] == {"up": "up", "down": None, "flat": None, "edge": None, "gone": "down"}
    assert trends["30d"] == {"up": "up", "down": "down", "flat": None, "edge": None, "new": "up", "gone": None}  # "gone" has no 7d share


def test_a_trend_is_null_when_the_comparison_window_is_missing_and_uses_shares_as_shown():
    only_month = modern(meta30=[archetype("a", 5.0)])["standings_by_window"]
    assert only_month["30d"][0]["trend"] is None  # no 7-day window to compare with
    week_and_month = modern(meta30=[archetype("a", 5.0)], meta7=[archetype("a", 9.0)])["standings_by_window"]
    assert week_and_month["7d"][0]["trend"] is None  # no 14-day window
    assert week_and_month["30d"][0]["trend"] == "up"
    # 15.04 shows as 15.0 and 14.0 is one point below it, not more than one.
    shown = modern(meta30=[archetype("a", 14.0)], meta7=[archetype("a", 15.04)])["standings_by_window"]
    assert shown["30d"][0]["trend"] is None
    shown = modern(meta30=[archetype("a", 14.0)], meta7=[archetype("a", 15.06)])["standings_by_window"]
    assert shown["30d"][0]["trend"] == "up"


def test_top8_and_wins_count_placings_in_the_window_only():
    results = [
        result("2026-09-29", "1st Place"),
        result("2026-09-28", "1st Place"),
        result("2026-09-27", "8th Place"),
        result("2026-09-27", "9th Place"),
        result("2026-09-27", "11th Place"),  # not a 1st, not a top 8
        result("2026-09-26", "5-0"),  # a league record is not a placing
        result("2026-09-26", "-"),
        result("2026-08-25", "1st Place"),  # older than 30 days
        result("2026-11-04", "2nd Place"),  # an event still to be played
    ]
    standing = modern(meta30=[archetype("a", 5.0)], archetypes={"a": {"results": results}})["standings"][0]
    assert (standing["top8_30d"], standing["wins_30d"]) == (3, 2)


def test_an_archetype_with_no_results_counts_zero():
    standing = modern(meta30=[archetype("a", 5.0)])["standings"][0]
    assert (standing["top8_30d"], standing["wins_30d"]) == (0, 0)


def test_colours_and_the_first_two_key_cards_pass_through_and_old_snapshots_give_empty_lists():
    standings = modern(meta30=[archetype("a", 5.0, colors=["U", "R"]), {"name": "Old", "id": "old", "percentage": 1.0}])["standings"]
    assert standings[0]["colors"] == ["U", "R"]
    assert standings[0]["key_cards"] == [{"name": "Card 0", "oracle_id": "o0"}, {"name": "Card 1", "oracle_id": "o1"}]
    assert (standings[1]["colors"], standings[1]["key_cards"], standings[1]["deck_count_30d"]) == ([], [], None)


def test_recent_events_are_newest_first_up_to_today_and_at_most_thirty():
    # Two Challenges a day for the first fifteen days of the month, then a League a day.
    events = [
        event(str(100 + n), f"Modern Challenge 32 2026-09-{day:02d}", f"2026-09-{day:02d}", ["1st Place", "2nd Place"])
        for n, day in enumerate(list(range(1, 16)) * 2)
    ]
    events += [event(str(200 + day), f"Modern League 2026-09-{day:02d}", f"2026-09-{day:02d}", ["5-0"], kind="mtgo_league") for day in range(16, 30)]
    events.append(event("999", "Store Qualifier 2026-11-04", "2026-11-04", ["1st Place"]))
    events.append(event("998", "Modern Challenge 32 2026-09-30", "2026-09-30", ["1st Place"]))  # today counts
    recent = modern(meta30=[archetype("a", 1.0)], events=events)["recent_events"]
    assert len(recent) == 30  # 45 are dated up to today
    assert recent[0]["date"] == "2026-09-30" and recent[1]["date"] == "2026-09-29"
    assert [e["kind"] for e in recent[:15]].count("mtgo_league") == 14  # Leagues count like any other event
    assert [e["date"] for e in recent] == sorted((e["date"] for e in recent), reverse=True)
    assert all(e["date"] <= "2026-09-30" for e in recent)


def test_an_event_lists_its_winner_and_publishes_no_deck_lists():
    challenge = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place", "3rd Place"])
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0", "5-0"], kind="mtgo_league")
    recent = modern(meta30=[archetype("a", 1.0)], events=[challenge, league])["recent_events"]
    assert set(recent[0]) == {"id", "name", "date", "kind", "prestige", "source", "url", "deck_count", "result_count", "winner_archetype", "winner_player", "lead", "top"}
    by_url = {e["url"].rsplit("/", 1)[1]: e for e in recent}
    assert by_url["7"]["winner_archetype"] == "Boros Energy" and by_url["7"]["winner_player"] == "player0" and by_url["7"]["deck_count"] == 3
    assert by_url["8"]["winner_archetype"] is None and by_url["8"]["winner_player"] is None and by_url["8"]["deck_count"] == 2
    assert by_url["8"]["name"] == "Modern League" and by_url["8"]["kind"] == "mtgo_league"


def test_the_events_own_date_leaves_its_name_wherever_it_sits():
    copy = event("4", "Modern League 2026-09-29 (1)", "2026-09-29", ["5-0"], kind="mtgo_league")
    other_date = event("5", "Modern Challenge 32 2026-09-28", "2026-09-29", ["1st Place"])  # not this event's own date
    names = {e["url"].rsplit("/", 1)[1]: e["name"] for e in modern(meta30=[archetype("a", 1.0)], events=[copy, other_date])["recent_events"]}
    assert names == {"4": "Modern League (1)", "5": "Modern Challenge 32 2026-09-28"}


def test_names_without_a_trailing_date_are_kept_whole():
    local = event("3", "Charlotte Legacy League Season 3 Week 13", "2026-09-28", ["4-1"], kind="other", source=None)
    recent = modern(meta30=[archetype("a", 1.0)], events=[local])["recent_events"]
    assert (recent[0]["name"], recent[0]["source"]) == ("Charlotte Legacy League Season 3 Week 13", None)


def test_latest_event_is_the_newest_with_a_winner_else_the_first_else_null():
    league = event("9", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league")
    challenge = event("5", "Modern Challenge 32 2026-09-28", "2026-09-28", ["1st Place", "2nd Place"])
    latest = modern(meta30=[archetype("a", 1.0)], events=[league, challenge])["latest_event"]
    assert latest["name"] == "Modern Challenge 32" and latest["winner_archetype"] == "Boros Energy"
    assert set(latest) == {"id", "name", "date", "kind", "prestige", "source", "url", "deck_count", "result_count", "winner_archetype", "lead", "top"}  # no winner_player

    only_league = modern(meta30=[archetype("a", 1.0)], events=[league])["latest_event"]
    assert only_league["name"] == "Modern League" and only_league["winner_archetype"] is None

    assert modern(meta30=[archetype("a", 1.0)])["latest_event"] is None


def test_an_event_has_its_id_and_result_count():
    challenge = event("66947", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place", "3rd Place"])
    recent = modern(meta30=[archetype("a", 1.0)], events=[challenge])["recent_events"][0]
    assert (recent["id"], recent["result_count"], recent["deck_count"]) == ("66947", 3, 3)
    assert recent["url"].endswith("/66947")  # the id is the tournament id in the url


def test_the_lead_of_an_event_is_its_winner_with_the_first_two_key_cards_of_its_archetype():
    challenge = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place", "3rd Place"])
    challenge["results"].reverse()  # the winner is listed last
    lead = modern(meta30=[archetype("a", 5.0)], events=[challenge])["recent_events"][0]["lead"]
    assert lead == {
        "finish": "1st Place",
        "archetype": "Boros Energy",
        "archetype_id": "a",
        "player": "player0",
        "deck_id": "0",
        "colors": ["R", "W"],  # its archetype's tile, as no deck is stored
        "key_cards": [{"name": "Card 0", "oracle_id": "o0"}, {"name": "Card 1", "oracle_id": "o1"}],
    }


def test_an_event_without_a_winner_leads_with_its_first_listed_result():
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0", "5-0"], kind="mtgo_league")
    document = modern(meta30=[archetype("a", 5.0)], events=[league])
    lead = document["recent_events"][0]["lead"]
    assert (lead["finish"], lead["archetype"], lead["player"], lead["deck_id"]) == ("5-0", "Boros Energy", "player0", "0")
    assert lead["key_cards"] != [] and document["latest_event"]["lead"] == lead


def test_a_lead_has_no_key_cards_when_its_archetype_is_untracked_or_not_in_the_metagame():
    untracked = event("9", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league", archetype_id=None)
    gone = event("10", "Modern League 2026-09-28", "2026-09-28", ["5-0"], kind="mtgo_league", archetype_id="not-in-meta")
    recent = modern(meta30=[archetype("a", 5.0)], events=[untracked, gone])["recent_events"]
    assert [(e["lead"]["archetype_id"], e["lead"]["key_cards"]) for e in recent] == [(None, []), ("not-in-meta", [])]


def test_key_cards_come_from_the_longest_window_that_shows_the_archetype_and_falls_back_to_a_shorter_one():
    week_only = archetype("w", 3.0, key_cards=[{"name": "Week Card", "oracle_id": "w0"}])
    bare_month = archetype("m", 3.0, key_cards=[])
    week_has_them = archetype("m", 3.0, key_cards=[{"name": "Filled", "oracle_id": "f0"}])
    winners = [
        event("1", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place"], archetype_id="w"),
        event("2", "Modern Challenge 32 2026-09-28", "2026-09-28", ["1st Place"], archetype_id="m"),
    ]
    recent = modern(meta30=[archetype("a", 9.0), bare_month], meta7=[week_only, week_has_them], events=winners)["recent_events"]
    assert [e["lead"]["key_cards"] for e in recent] == [[{"name": "Week Card", "oracle_id": "w0"}], [{"name": "Filled", "oracle_id": "f0"}]]


def test_an_event_with_no_results_has_a_null_lead_and_no_top():
    empty = event("11", "Modern League 2026-09-29", "2026-09-29", [], kind="mtgo_league")
    document = modern(meta30=[archetype("a", 1.0)], events=[empty])
    assert document["recent_events"][0]["lead"] is None and document["recent_events"][0]["result_count"] == 0
    assert document["latest_event"]["lead"] is None
    assert document["recent_events"][0]["top"] == [] and document["latest_event"]["top"] == []


def test_top_is_the_first_three_results_in_finish_order_and_its_first_is_the_lead():
    challenge = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place", "3rd Place", "4th Place"])
    challenge["results"][1]["archetype_id"] = "b"
    challenge["results"][1]["archetype"] = "Bee"
    challenge["results"].reverse()  # listed out of order: 4th, 3rd, 2nd, 1st
    metas = [archetype("a", 5.0), archetype("b", 4.0, key_cards=[{"name": "Bee Card", "oracle_id": "b0"}])]
    recent = modern(meta30=metas, events=[challenge])["recent_events"][0]
    top = recent["top"]
    assert [(r["finish"], r["player"], r["deck_id"]) for r in top] == [("1st Place", "player0", "0"), ("2nd Place", "player1", "1"), ("3rd Place", "player2", "2")]
    assert set(top[0]) == {"finish", "player", "archetype", "archetype_id", "deck_id", "colors", "key_cards"}
    assert (top[1]["archetype"], top[1]["archetype_id"], top[1]["key_cards"]) == ("Bee", "b", [{"name": "Bee Card", "oracle_id": "b0"}])
    assert (top[2]["archetype"], top[2]["archetype_id"], top[2]["key_cards"]) == ("Other Deck", None, [])  # untracked, and no deck stored
    assert recent["lead"] == top[0] and recent["winner_player"] == "player0"


def test_top_of_a_league_is_the_first_three_listed_and_a_short_event_has_fewer():
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0"] * 5, kind="mtgo_league")
    two = event("9", "Modern League 2026-09-28", "2026-09-28", ["5-0", "5-0"], kind="mtgo_league")
    recent = modern(meta30=[archetype("a", 1.0)], events=[league, two])["recent_events"]
    assert [r["player"] for r in recent[0]["top"]] == ["player0", "player1", "player2"]
    assert len(recent[1]["top"]) == 2 and recent[1]["lead"] == recent[1]["top"][0]


def test_latest_event_has_the_top_of_its_event():
    challenge = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place"])
    document = modern(meta30=[archetype("a", 1.0)], events=[challenge])
    assert document["latest_event"]["top"] == document["recent_events"][0]["top"] and len(document["latest_event"]["top"]) == 2


def test_a_result_without_key_cards_takes_its_decks_two_most_played_non_lands():
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0", "5-0", "5-0"], kind="mtgo_league", archetype_id=None)
    decks = {
        "0": stored((4, "Mountain"), (4, "Lightning Bolt"), (4, "Arid Mesa"), (3, "Ragavan, Nimble Pilferer"), (2, "Ocelot Pride")),
        "1": stored((2, "Ragavan, Nimble Pilferer"), (2, "Lightning Bolt"), (2, "Ocelot Pride"), (1, "Made-up Card")),  # ties keep the decklist's order
        "2": stored((2, "Lightning Bolt"), (2, "Ragavan, Nimble Pilferer"), (1, "Lightning Bolt"), (3, "Made-up Card")),  # copies of a name add up; unknown names are skipped
    }
    top = modern(meta30=[archetype("a", 1.0)], events=[league], decks=decks, catalog=CATALOG)["recent_events"][0]["top"]
    assert [r["key_cards"] for r in top] == [
        [{"name": "Lightning Bolt", "oracle_id": "o-bolt"}, {"name": "Ragavan, Nimble Pilferer", "oracle_id": "o-ragavan"}],
        [{"name": "Ragavan, Nimble Pilferer", "oracle_id": "o-ragavan"}, {"name": "Lightning Bolt", "oracle_id": "o-bolt"}],
        [{"name": "Lightning Bolt", "oracle_id": "o-bolt"}, {"name": "Ragavan, Nimble Pilferer", "oracle_id": "o-ragavan"}],
    ]


def test_the_deck_fallback_covers_an_archetype_left_out_of_the_metagame_and_a_tile_with_no_key_cards():
    gone = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league", archetype_id="not-in-meta")
    bare = event("9", "Modern League 2026-09-28", "2026-09-28", ["5-0"], kind="mtgo_league", archetype_id="bare")
    decks = {"0": stored((4, "Lightning Bolt"), (4, "Ocelot Pride"))}
    recent = modern(meta30=[archetype("bare", 1.0, key_cards=[])], events=[gone, bare], decks=decks, catalog=CATALOG)["recent_events"]
    assert [[c["oracle_id"] for c in e["lead"]["key_cards"]] for e in recent] == [["o-bolt", "o-ocelot"]] * 2


def test_the_archetypes_own_key_cards_win_over_the_deck_and_a_deck_only_has_its_mainboard():
    winner = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place"])
    decks = {"0": stored((4, "Lightning Bolt")), "1": {"m": [[4, "Mountain"]], "s": [[4, "Sideboard Card"]]}}
    top = modern(meta30=[archetype("a", 1.0)], events=[winner], decks=decks, catalog=CATALOG)["recent_events"][0]["top"]
    assert [c["oracle_id"] for c in top[0]["key_cards"]] == ["o0", "o1"]  # the tile's, though the deck is known
    assert top[1]["key_cards"] == []  # only a land in the main, and the sideboard doesn't count


def test_without_a_stored_deck_or_a_catalog_a_result_keeps_empty_key_cards():
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league", archetype_id=None)
    decks = {"0": stored((4, "Lightning Bolt"))}
    assert modern(meta30=[archetype("a", 1.0)], events=[league], catalog=CATALOG)["recent_events"][0]["lead"]["key_cards"] == []
    assert modern(meta30=[archetype("a", 1.0)], events=[league], decks=decks)["recent_events"][0]["lead"]["key_cards"] == []
    assert modern(meta30=[archetype("a", 1.0)], events=[league], decks=decks, catalog={})["recent_events"][0]["lead"]["key_cards"] == []


# Prices and mana values decide ties between cards played in equal numbers.
PRICED = {
    "amulet-of-vigor": {"name": "Amulet of Vigor", "oracle_id": "o-amulet", "price": 30.0, "mana_value": 1},
    "primeval-titan": {"name": "Primeval Titan", "oracle_id": "o-titan", "price": 2.0, "mana_value": 6},
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "o-bolt", "price": 1.5, "mana_value": 1},
    "ocelot-pride": {"name": "Ocelot Pride", "oracle_id": "o-ocelot", "price": 8.0, "mana_value": 1},
    "spell-cheap": {"name": "Spell Cheap", "oracle_id": "o-cheap", "mana_value": 1},
    "spell-dear": {"name": "Spell Dear", "oracle_id": "o-dear", "mana_value": 5},
    "spell-free": {"name": "Spell Free", "oracle_id": "o-free", "price": 0.0, "mana_value": 0},
    "wear": {"name": "Wear // Tear", "oracle_id": "o-wear", "mana_value": 2},
    "fable-of-the-mirror-breaker": {"name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "oracle_id": "o-fable", "price": 10.0, "mana_value": 3},
    "mountain": {"name": "Mountain", "oracle_id": "o-mountain", "land": True},
}


def picked(mainboard, archetype="", limit=2):
    return [card["oracle_id"] for card in deck_key_cards(mainboard, PRICED, archetype, limit)]


def test_a_namesake_card_comes_first_then_the_most_played():
    deck = [[4, "Lightning Bolt"], [4, "Ocelot Pride"], [1, "Amulet of Vigor"], [4, "Primeval Titan"], [4, "Mountain"]]
    # "Amulet Titan" names two cards; the better ranked, four Primeval Titan against one Amulet, is the namesake.
    assert picked(deck, "Amulet Titan") == ["o-titan", "o-ocelot"]  # then the priciest of the 4-ofs left
    assert picked(deck, "Amulet Titan", limit=3) == ["o-titan", "o-ocelot", "o-bolt"]
    assert picked(deck, "Lands Deck") == ["o-ocelot", "o-titan"]  # no namesake: the most played, the pricier first; the land never counts
    assert picked([[4, "Lightning Bolt"], [1, "Amulet of Vigor"]], "Amulet Titan") == ["o-amulet", "o-bolt"]  # a one-of namesake still leads


def test_the_namesake_matches_on_words_of_four_letters_or_more_in_the_front_face_name():
    deck = [[4, "Lightning Bolt"], [3, "Ocelot Pride"], [2, "Wear/Tear"], [1, "Fable of the Mirror-Breaker"]]
    assert picked(deck, "Wear Deck") == ["o-wear", "o-bolt"]  # "Wear/Tear" is written by its front face
    assert picked(deck, "Tear Deck") == ["o-bolt", "o-ocelot"]  # the back face doesn't count
    assert picked(deck, "FABLE MIRROR") == ["o-fable", "o-bolt"]  # any case; the deck writes the front face of a double-faced card
    assert picked(deck, "Big Ice Pod") == ["o-bolt", "o-ocelot"]  # "Big", "Ice" and "Pod" are under four letters
    assert picked(deck, "W") == ["o-bolt", "o-ocelot"] and picked(deck, "") == ["o-bolt", "o-ocelot"]


def test_ties_in_copies_go_to_the_price_then_the_mana_value_then_the_decklist_order():
    deck = [[4, "Spell Cheap"], [4, "Lightning Bolt"], [4, "Ocelot Pride"], [4, "Spell Dear"], [4, "Spell Free"], [3, "Primeval Titan"]]
    # $8, $1.5, then a $0 card beats the two with no price, which fall to mana value (5, then 1).
    assert picked(deck, "", limit=5) == ["o-ocelot", "o-bolt", "o-free", "o-dear", "o-cheap"]
    assert picked([[4, "Spell Dear"], [4, "Spell Cheap"], [4, "Spell Free"]], "", limit=2) == ["o-free", "o-dear"]
    same = {"a": {"name": "A", "oracle_id": "oa", "price": 1.0, "mana_value": 2}, "b": {"name": "B", "oracle_id": "ob", "price": 1.0, "mana_value": 2}}
    assert [c["name"] for c in deck_key_cards([[2, "B"], [2, "A"]], same)] == ["B", "A"]  # nothing left to tell them apart
    assert [c["name"] for c in deck_key_cards([[1, "B"], [2, "A"]], same)] == ["A", "B"]  # copies come before price


def test_a_result_previews_its_deck_with_the_namesake_of_its_archetype_title():
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league", archetype_id=None)
    league["results"][0]["archetype"] = "Amulet Titan"
    decks = {"0": stored((4, "Lightning Bolt"), (1, "Amulet of Vigor"), (2, "Primeval Titan"))}
    lead = modern(meta30=[archetype("a", 1.0)], events=[league], decks=decks, catalog=PRICED)["recent_events"][0]["lead"]
    assert [c["oracle_id"] for c in lead["key_cards"]] == ["o-titan", "o-bolt"]


def test_each_windows_top8_and_wins_count_only_the_placings_of_its_own_days():
    results = [
        result("2026-09-30", "2nd Place"),  # today counts
        result("2026-09-29", "1st Place"),
        result("2026-09-24", "5th Place"),
        result("2026-09-22", "1st Place"),  # outside 7 days (the 7-day window starts on the 23rd, at 02:00)
        result("2026-09-17", "8th Place"),
        result("2026-09-15", "1st Place"),  # outside 14 days
        result("2026-09-05", "9th Place"),  # in the month, but not a top 8
        result("2026-09-05", "5-0"),  # a record is not a placing
        result("2026-08-31", "1st Place"),  # outside 30 days
        result("2026-11-04", "1st Place"),  # not played yet
    ]
    entries = [archetype("a", 5.0)]
    by_window = modern(meta30=entries, meta14=entries, meta7=entries, archetypes={"a": {"results": results}})["standings_by_window"]
    assert [(w, by_window[w][0]["top8"], by_window[w][0]["wins"]) for w in ("7d", "14d", "30d")] == [("7d", 3, 1), ("14d", 5, 2), ("30d", 6, 3)]
    # The 30-day list agrees with the older standings field.
    standing = modern(meta30=entries, archetypes={"a": {"results": results}})["standings"][0]
    assert (standing["top8_30d"], standing["wins_30d"]) == (6, 3)


def test_top8_and_wins_of_a_window_are_zero_without_results():
    by_window = modern(meta30=[archetype("a", 5.0)], meta7=[archetype("a", 5.0)])["standings_by_window"]
    assert (by_window["7d"][0]["top8"], by_window["7d"][0]["wins"]) == (0, 0)
    assert (by_window["30d"][0]["top8"], by_window["30d"][0]["wins"]) == (0, 0)


def event_of(kind, name, results=8):
    return {"kind": kind, "event_name": name, "results": [{}] * results}


def test_prestige_runs_from_one_to_four():
    # 4: the top of the game.
    assert prestige(event_of("pro_tour", "Pro Tour Marvel Super Heroes")) == 4
    assert prestige(event_of("regional_championship", "Regional Championship - SCG CON Baltimore - Saturday")) == 4
    # 3: qualifiers, Showcases and the big Challenges.
    assert prestige(event_of("rcq", "$uper $unday RCQ - Modern - SCG CON Baltimore")) == 3
    assert prestige(event_of("mtgo_challenge", "Modern Showcase Challenge 2026-09-27")) == 3
    assert prestige(event_of("mtgo_challenge", "Modern Super Qualifier 2026-09-27")) == 3
    assert prestige(event_of("mtgo_challenge", "Modern Challenge 64 2026-09-28")) == 3
    assert prestige(event_of("mtgo_challenge", "Legacy Challenge 96 2026-09-28")) == 3
    assert prestige(event_of("mtgo_challenge", "Pioneer Challenge 128 2026-09-28")) == 3
    # 2: the regular Challenges, Store Championships and big local events.
    assert prestige(event_of("mtgo_challenge", "Modern Challenge 32 2026-09-28")) == 2
    assert prestige(event_of("mtgo_challenge", "Modern Prelim 2026-09-28")) == 2
    assert prestige(event_of("mtgo_challenge", "Modern Challenge 640 2026-09-28")) == 2  # not a 64
    assert prestige(event_of("store_championship", "Modern Store Championship", results=4)) == 2
    assert prestige(event_of("other", "Big Local Open", results=64)) == 2
    # 1: everything else, every League included.
    assert prestige(event_of("other", "Big Local Open", results=63)) == 1
    assert prestige(event_of("mtgo_league", "Modern League 2026-09-28", results=100)) == 1
    assert prestige({"event_name": "Charlotte Legacy League", "results": []}) == 1  # no kind is "other"


def test_prestige_is_published_on_recent_events_and_the_latest_event():
    big = event("1", "Modern Challenge 64 2026-09-29", "2026-09-29", ["1st Place"] * 4)
    league = event("2", "Modern League 2026-09-28", "2026-09-28", ["5-0"], kind="mtgo_league")
    document = modern(meta30=[archetype("a", 1.0)], events=[big, league])
    assert {e["id"]: e["prestige"] for e in document["recent_events"]} == {"1": 3, "2": 1}
    assert document["latest_event"]["prestige"] == 3


# Costs for the colour tests: the catalog's `mana_cost`, and "land" for a land.
PIPS = {
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "o-bolt", "mana_cost": "{R}"},
    "path-to-exile": {"name": "Path to Exile", "oracle_id": "o-path", "mana_cost": "{W}"},
    "counterspell": {"name": "Counterspell", "oracle_id": "o-counter", "mana_cost": "{U}{U}"},
    "sol-ring": {"name": "Sol Ring", "oracle_id": "o-ring", "mana_cost": "{1}"},
    "mountain": {"name": "Mountain", "oracle_id": "o-mountain", "land": True},
}
RED = stored((4, "Lightning Bolt"), (20, "Mountain"))
WHITE = stored((4, "Path to Exile"))
BLUE = stored((2, "Counterspell"))
COLOURLESS = stored((4, "Sol Ring"), (20, "Mountain"))


def history(deck_ids, featured=None):
    """An archetype of the snapshot: its featured deck and one result per deck id."""
    return {"deck_id": featured, "results": [result("2026-09-28", "1st Place", deck_id=deck_id) for deck_id in deck_ids]}


def with_results(*entries):
    """A Challenge whose results are the given dicts, in finish order, with the fields every result has."""
    results = [
        {"finish": f"{n + 1}st Place", "player": f"p{n}", "archetype": "Deck", "archetype_id": None, "deck_id": str(n), **entry}
        for n, entry in enumerate(entries)
    ]
    return {**event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", []), "results": results}


def test_a_results_colours_come_from_the_event_page_then_its_decklist_then_its_tile_else_null():
    challenge = with_results(
        {"colors": ["U", "B"]},  # the page's pips win over everything below
        {},  # its decklist: Bolt and Path
        {},  # a decklist of colourless cards: colourless, not "go and look at the tile"
        {"archetype_id": "a"},  # no deck stored: its archetype's tile
        {},  # nothing at all
    )
    decks = {"0": RED, "1": stored((4, "Lightning Bolt"), (4, "Path to Exile")), "2": COLOURLESS}
    recent = modern(meta30=[archetype("a", 5.0, colors=["R", "W"])], events=[challenge], decks=decks, catalog=PIPS)["recent_events"][0]
    assert [r["colors"] for r in recent["top"]] == [["U", "B"], ["W", "R"], []]
    assert recent["lead"]["colors"] == ["U", "B"]
    # The fourth and fifth are past the top three, so look at them through the event page's results.
    challenge["results"] = challenge["results"][3:]
    deeper = modern(meta30=[archetype("a", 5.0, colors=["R", "W"])], events=[challenge], decks=decks, catalog=PIPS)["recent_events"][0]["top"]
    assert [r["colors"] for r in deeper] == [["R", "W"], None]


def test_the_page_colours_of_a_result_are_used_as_they_are_and_an_empty_list_there_is_ignored():
    challenge = with_results({"colors": ["W", "B", "G"], "archetype_id": "a"}, {"colors": []})
    top = modern(meta30=[archetype("a", 5.0, colors=["R"])], events=[challenge], decks={"1": RED}, catalog=PIPS)["recent_events"][0]["top"]
    assert top[0]["colors"] == ["W", "B", "G"]
    assert top[1]["colors"] == ["R"]  # an empty list is no pips shown, so the decklist says


def test_a_result_with_a_tile_that_shows_no_colours_takes_its_archetypes_featured_deck_and_else_says_so():
    challenge = with_results(
        {"archetype_id": "bare"},
        {"archetype_id": "plain"},
        {"archetype_id": "old"},
    )
    metas = [archetype("bare", 5.0, colors=[]), archetype("plain", 4.0, colors=[]), {"name": "Old", "id": "old", "percentage": 1.0}]
    archetypes = {"bare": history([], featured="50"), "plain": history([], featured="51")}
    decks = {"50": RED}  # "plain"'s featured deck is not stored
    top = modern(meta30=metas, events=[challenge], decks=decks, catalog=PIPS, archetypes=archetypes)["recent_events"][0]["top"]
    # The featured deck is red; the tile shows none and there is no deck to ask, so colourless; a tile from before colours were read, unknown.
    assert [r["colors"] for r in top] == [["R"], [], None]


def test_standings_take_the_featured_decks_colours_when_the_tile_shows_none():
    metas = [
        archetype("bare", 9.0, colors=[]),
        archetype("artifacts", 8.0, colors=[]),
        archetype("shown", 7.0, colors=["U"]),
        archetype("unstored", 6.0, colors=[]),
    ]
    archetypes = {
        "bare": history([], featured="50"),
        "artifacts": history([], featured="51"),
        "shown": history([], featured="50"),  # the tile's colours stay when it has some
        "unstored": history([], featured="99"),
    }
    document = modern(meta30=metas, meta7=metas, archetypes=archetypes, decks={"50": RED, "51": COLOURLESS}, catalog=PIPS)
    expected = {"bare": ["R"], "artifacts": [], "shown": ["U"], "unstored": []}
    assert {s["id"]: s["colors"] for s in document["standings"]} == expected
    assert {s["id"]: s["colors"] for s in document["standings_by_window"]["7d"]} == expected
    assert {s["id"]: s["colors"] for s in document["standings_by_window"]["30d"]} == expected
