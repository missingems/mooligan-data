from datetime import datetime, timedelta, timezone

from mtgmeta.breakouts import MIN_BASELINE_DECKS, build_breakouts
from mtgmeta.cards import slug

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def card(name, type_line, layout="normal", **extra):
    return {"name": name, "oracle_id": "o-" + slug(name), "type_line": type_line, "layout": layout, **extra}


CATALOG = {
    slug(entry["name"]): entry
    for entry in [
        card("Lightning Bolt", "Instant", price=1.5),
        card("Psychic Frog", "Creature — Frog", price=18.0, scryfall_id="s-psychic-frog"),
        card("Consign to Memory", "Instant"),
        card("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Enchantment — Saga", layout="transform"),
        card("Mountain", "Basic Land — Mountain"),
    ]
}
FILLER = [(4, "Lightning Bolt"), (20, "Mountain")]


def world(recent, baseline=MIN_BASELINE_DECKS, kind="mtgo_challenge", name="Modern Challenge 32"):
    """A snapshot with `baseline` filler decks 15 days ago, and `recent` decks 2 days ago in one event.

    Each recent deck is `(mainboard, sideboard, finish, archetype id)`, in standings order.
    """
    deck_cards, events, archetypes = {}, [], {}
    old = (NOW - timedelta(days=15)).strftime("%Y-%m-%dT00:00:00Z")
    old_results = []
    for n in range(baseline):
        deck_cards[f"b{n}"] = {"m": FILLER, "s": []}
        old_results.append({"deck_id": f"b{n}", "finish": f"{n + 1}th Place", "archetype_id": "burn", "archetype": "Burn"})
    events.append({"event_id": "1", "event_name": "Modern Challenge 32", "kind": "mtgo_challenge", "date": old, "results": old_results})
    results = []
    for n, (main, side, finish, archetype_id) in enumerate(recent):
        deck_cards[f"r{n}"] = {"m": FILLER + main, "s": side}
        results.append({"deck_id": f"r{n}", "finish": finish, "archetype_id": archetype_id, "archetype": archetype_id or "Brew"})
        if archetype_id:
            archetypes.setdefault(archetype_id, {"name": archetype_id.title(), "results": []})
    events.append({"event_id": "2", "event_name": name, "kind": kind, "date": (NOW - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z"), "results": results})
    return {"format": "modern", "events": events, "archetypes": archetypes}, deck_cards


def breakouts(*args, **kwargs):
    document, deck_cards = world(*args, **kwargs)
    return build_breakouts(document, deck_cards, CATALOG, NOW)


def test_a_card_the_last_week_plays_and_the_weeks_before_did_not_breaks_out():
    frog = [(4, "Psychic Frog")]
    recent = [(frog, [], "1st Place", "dimir"), (frog, [], "2nd Place", "dimir"), (frog, [], "9th Place", "dimir"), ([], [(2, "Psychic Frog")], "5th Place", "dimir-control"), ([], [], "3rd Place", None)]
    file = breakouts(recent)
    assert (file["schema"], file["format"], file["deck_count"], file["baseline_deck_count"]) == (1, "modern", 5, MIN_BASELINE_DECKS)
    [row] = file["cards"]  # Lightning Bolt is everywhere and Mountain is a basic
    assert row == {
        "name": "Psychic Frog",
        "oracle_id": "o-psychic-frog",
        "scryfall_id": "s-psychic-frog",
        "type": "creature",
        "decks": 4,
        "share": 80.0,
        "previous_share": 0.0,
        "new": True,
        "first_seen": "2026-09-28",
        "mainboard": 3,
        "top8": 3,
        "wins": 1,
        "best_prestige": 2,
        "price": 18.0,
        "results": row["results"],
    }
    assert "archetypes" not in row
    # The printing the price is of sits right after the oracle id.
    assert list(row)[:3] == ["name", "oracle_id", "scryfall_id"]
    assert [(r["deck_id"], r["finish"], r["top8"], r["archetype_id"], r["archetype"], r["copies"], r["mainboard"]) for r in row["results"]] == [
        ("r0", "1st Place", True, "dimir", "Dimir", 4, True),
        ("r1", "2nd Place", True, "dimir", "Dimir", 4, True),
        ("r3", "5th Place", True, "dimir-control", "Dimir-Control", 2, False),
        ("r2", "9th Place", False, "dimir", "Dimir", 4, True),
    ]


def test_too_few_decks_or_too_little_growth_is_no_breakout():
    three = [([(4, "Psychic Frog")], [], "1st Place", "a")] * 3
    assert breakouts(three + [([], [], "4th Place", "a")] * 5)["cards"] == []  # three decks are not enough
    # A card the earlier weeks played in 2 of 20 decks (10%) needs 30% now.
    document, deck_cards = world([([(1, "Consign to Memory")], [], "1st Place", "a")] * 5 + [([], [], "9th Place", "a")] * 12)
    deck_cards["b0"] = deck_cards["b1"] = {"m": FILLER + [(1, "Consign to Memory")], "s": []}
    assert build_breakouts(document, deck_cards, CATALOG, NOW)["cards"] == []  # 5 of 17 is 29.4%
    document, deck_cards = world([([(1, "Consign to Memory")], [], "1st Place", "a")] * 5 + [([], [], "9th Place", "a")] * 11)
    deck_cards["b0"] = deck_cards["b1"] = {"m": FILLER + [(1, "Consign to Memory")], "s": []}
    [row] = build_breakouts(document, deck_cards, CATALOG, NOW)["cards"]
    assert (row["share"], row["previous_share"], row["new"], row["first_seen"]) == (31.2, 10.0, False, "2026-09-15")


def test_a_format_without_enough_earlier_decks_has_no_breakouts():
    file = breakouts([([(4, "Psychic Frog")], [], "1st Place", "a")] * 6, baseline=MIN_BASELINE_DECKS - 1)
    assert (file["deck_count"], file["cards"]) == (6, [])


def test_breakouts_rank_by_decks_hold_at_most_the_limit_and_name_a_double_faced_card_by_its_front():
    fable = [(4, "Fable of the Mirror-Breaker")]
    recent = [(fable + [(1, "Consign to Memory")], [], "1st Place", "a")] * 6 + [(fable, [], "1st Place", "a")]
    file = breakouts(recent, kind="regional_championship", name="Regional Championship")
    assert [(row["name"], row["decks"], row["best_prestige"]) for row in file["cards"]] == [("Fable of the Mirror-Breaker", 7, 4), ("Consign to Memory", 6, 4)]


def test_results_list_every_recent_deck_in_order_with_what_each_played():
    frog = [(4, "Psychic Frog")]
    recent = [
        (frog, [], "9th Place", "dimir"),
        (frog, [], "5-0", "dimir"),
        ([], [(1, "Psychic Frog")], "2nd Place", "dimir"),
        (frog + [(1, "Consign to Memory")], [(1, "Psychic Frog")], "1st Place", None),
        (frog, [], "1st Place", "dimir"),
    ]
    document, deck_cards = world(recent)
    document["events"][1]["event_name"] = "Modern Challenge 32 2026-09-28"
    # r4 was in a Regional Championship the day before; r0..r3 are from the challenge two days ago.
    other = {"event_id": "3", "event_name": "Regional Championship", "kind": "regional_championship", "date": "2026-09-29T00:00:00Z", "results": [document["events"][1]["results"].pop(4)]}
    document["events"].append(other)
    for r in document["events"][1]["results"] + other["results"]:
        r["player"] = "P" + r["deck_id"]
    document["events"][1]["results"][1]["colors"] = ["U", "B"]
    document["events"][1]["results"][4 - 1]["colors"] = ["R"]
    [row] = build_breakouts(document, deck_cards, CATALOG, NOW)["cards"]
    assert "archetypes" not in row
    assert row["decks"] == len(row["results"]) == 5
    assert [r["deck_id"] for r in row["results"]] == ["r4", "r3", "r2", "r0", "r1"]
    first, second, third, fourth, last = row["results"]
    assert first == {
        "deck_id": "r4", "date": "2026-09-29", "event_id": "3", "event_name": "Regional Championship", "prestige": 4,
        "finish": "1st Place", "top8": True, "player": "Pr4", "archetype": "Dimir", "archetype_id": "dimir",
        "colors": [], "copies": 4, "mainboard": True,
    }
    assert (third["finish"], third["copies"], third["mainboard"], third["prestige"]) == ("2nd Place", 1, False, 2)
    # Untracked: no archetype id, the pilot's own deck title, and the colours scraped from the event page.
    assert (second["archetype_id"], second["archetype"], second["colors"], second["copies"], second["event_name"]) == (None, "Brew", ["R"], 5, "Modern Challenge 32")
    assert (fourth["finish"], fourth["top8"]) == ("9th Place", False)
    # A League-style record is no placing, so it is not a top 8, and it follows the placings.
    assert (last["finish"], last["top8"], last["colors"]) == ("5-0", False, ["U", "B"])
    assert [r["date"] for r in row["results"]] == ["2026-09-29", "2026-09-28", "2026-09-28", "2026-09-28", "2026-09-28"]


def test_a_deck_only_an_archetype_lists_has_no_event_and_the_lowest_prestige():
    document, deck_cards = world([([(4, "Psychic Frog")], [], "1st Place", "a")] * 4)
    document["events"][1]["results"].pop()
    document["archetypes"]["a"]["results"] = [{"deck_id": "r3", "date": "2026-09-27T00:00:00Z", "event_id": "99", "event_name": "Gone 2026-09-27", "finish": "3rd Place", "player": None}]
    [row] = build_breakouts(document, deck_cards, CATALOG, NOW)["cards"]
    last = row["results"][-1]
    assert (last["deck_id"], last["date"], last["event_id"], last["event_name"], last["prestige"], last["player"], last["top8"]) == ("r3", "2026-09-27", None, None, 1, None, True)
    assert last["archetype_id"] == "a"


def test_a_result_without_scraped_colours_has_those_of_its_deck():
    recent = [([(4, "Psychic Frog")], [], "1st Place", "dimir")] * 4
    document, deck_cards = world(recent)
    catalog = {**CATALOG, slug("Psychic Frog"): card("Psychic Frog", "Creature — Frog", mana_cost="{1}{U}{B}")}
    [row] = build_breakouts(document, deck_cards, catalog, NOW)["cards"]
    assert {tuple(r["colors"]) for r in row["results"]} == {("U", "B")}
