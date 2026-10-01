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
        card("Psychic Frog", "Creature — Frog", price=18.0),
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
        "archetypes": [{"id": "dimir", "name": "Dimir", "decks": 3}, {"id": "dimir-control", "name": "Dimir-Control", "decks": 1}],
        "price": 18.0,
    }


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


def test_an_archetype_has_the_colours_its_standings_tile_shows_and_none_when_unknown():
    frog = [(4, "Psychic Frog")]
    recent = [(frog, [], "1st Place", "dimir")] * 2 + [(frog, [], "2nd Place", "burn")] * 2 + [(frog, [], "3rd Place", "mystery")] * 2
    document, deck_cards = world(recent)
    # A tile with colours; a tile with no pips whose featured deck is red; and an archetype with no tile, which is unknown.
    tile = lambda id, **extra: {"id": id, "name": id.title(), **extra}
    document["meta"] = {"30d": {"archetypes": [tile("dimir", colors=["U", "B"]), tile("burn", colors=[])]}}
    document["archetypes"]["burn"]["deck_id"] = "b0"
    deck_cards["b0"] = {"m": [(4, "Lightning Bolt")], "s": []}
    catalog = {**CATALOG, slug("Lightning Bolt"): card("Lightning Bolt", "Instant", mana_cost="{R}")}
    [row] = build_breakouts(document, deck_cards, catalog, NOW)["cards"]
    assert row["archetypes"] == [
        {"id": "burn", "name": "Burn", "decks": 2, "colors": ["R"]},
        {"id": "dimir", "name": "Dimir", "decks": 2, "colors": ["U", "B"]},
        {"id": "mystery", "name": "Mystery", "decks": 2},
    ]
