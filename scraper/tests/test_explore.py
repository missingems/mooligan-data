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


def event(event_id, name, date, finishes, kind="mtgo_challenge", source="mtgo.com"):
    return {
        "event_id": event_id,
        "event_name": name,
        "date": f"{date}T00:00:00Z",
        "url": f"https://www.mtggoldfish.com/tournament/{event_id}",
        "kind": kind,
        "source": source,
        "results": [
            {"finish": finish, "player": f"player{n}", "archetype": "Boros Energy" if n == 0 else "Other Deck", "deck_id": str(n)}
            for n, finish in enumerate(finishes)
        ],
    }


def snapshot(meta30, meta7=None, archetypes=None, events=None):
    meta = {"30d": {"archetypes": meta30}}
    if meta7 is not None:
        meta["7d"] = {"archetypes": meta7}
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
    assert set(recent[0]) == {"name", "date", "kind", "source", "url", "deck_count", "winner_archetype", "winner_player"}
    by_url = {e["url"].rsplit("/", 1)[1]: e for e in recent}
    assert by_url["7"]["winner_archetype"] == "Boros Energy" and by_url["7"]["winner_player"] == "player0" and by_url["7"]["deck_count"] == 3
    assert by_url["8"]["winner_archetype"] is None and by_url["8"]["winner_player"] is None and by_url["8"]["deck_count"] == 2
    assert by_url["8"]["name"] == "Modern League" and by_url["8"]["kind"] == "mtgo_league"


def test_names_without_a_trailing_date_are_kept_whole():
    local = event("3", "Charlotte Legacy League Season 3 Week 13", "2026-09-28", ["4-1"], kind="other", source=None)
    recent = modern(meta30=[archetype("a", 1.0)], events=[local])["recent_events"]
    assert (recent[0]["name"], recent[0]["source"]) == ("Charlotte Legacy League Season 3 Week 13", None)


def test_latest_event_is_the_newest_with_a_winner_else_the_first_else_null():
    league = event("9", "Modern League 2026-09-29", "2026-09-29", ["5-0"], kind="mtgo_league")
    challenge = event("5", "Modern Challenge 32 2026-09-28", "2026-09-28", ["1st Place", "2nd Place"])
    latest = modern(meta30=[archetype("a", 1.0)], events=[league, challenge])["latest_event"]
    assert latest["name"] == "Modern Challenge 32" and latest["winner_archetype"] == "Boros Energy"
    assert set(latest) == {"name", "date", "kind", "source", "url", "deck_count", "winner_archetype"}  # no winner_player

    only_league = modern(meta30=[archetype("a", 1.0)], events=[league])["latest_event"]
    assert only_league["name"] == "Modern League" and only_league["winner_archetype"] is None

    assert modern(meta30=[archetype("a", 1.0)])["latest_event"] is None
