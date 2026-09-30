from datetime import datetime, timezone

from mtgmeta.explore import build_explore

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


def modern(**kwargs):
    return build_explore({"modern": snapshot(**kwargs)}, NOW)["formats"][0]


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
    assert set(new[0]) == {"id", "name", "share", "deck_count", "trend", "colors", "key_cards"}
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


def test_recent_events_are_newest_first_up_to_today_and_at_most_twenty():
    events = [event(str(100 + n), f"Modern Challenge 32 2026-09-{day:02d}", f"2026-09-{day:02d}", ["1st Place", "2nd Place"]) for n, day in enumerate(range(1, 30))]
    events.append(event("999", "Store Qualifier 2026-11-04", "2026-11-04", ["1st Place"]))
    events.append(event("998", "Modern Challenge 32 2026-09-30", "2026-09-30", ["1st Place"]))  # today counts
    recent = modern(meta30=[archetype("a", 1.0)], events=events)["recent_events"]
    assert len(recent) == 20
    assert recent[0]["date"] == "2026-09-30" and recent[1]["date"] == "2026-09-29"
    assert [e["date"] for e in recent] == sorted((e["date"] for e in recent), reverse=True)
    assert all(e["date"] <= "2026-09-30" for e in recent)


def test_an_event_lists_its_winner_and_publishes_no_deck_lists():
    challenge = event("7", "Modern Challenge 32 2026-09-29", "2026-09-29", ["1st Place", "2nd Place", "3rd Place"])
    league = event("8", "Modern League 2026-09-29", "2026-09-29", ["5-0", "5-0"], kind="mtgo_league")
    recent = modern(meta30=[archetype("a", 1.0)], events=[challenge, league])["recent_events"]
    assert set(recent[0]) == {"id", "name", "date", "kind", "source", "url", "deck_count", "result_count", "winner_archetype", "winner_player", "lead"}
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
    assert set(latest) == {"id", "name", "date", "kind", "source", "url", "deck_count", "result_count", "winner_archetype", "lead"}  # no winner_player

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


def test_an_event_with_no_results_has_a_null_lead():
    empty = event("11", "Modern League 2026-09-29", "2026-09-29", [], kind="mtgo_league")
    document = modern(meta30=[archetype("a", 1.0)], events=[empty])
    assert document["recent_events"][0]["lead"] is None and document["recent_events"][0]["result_count"] == 0
    assert document["latest_event"]["lead"] is None
