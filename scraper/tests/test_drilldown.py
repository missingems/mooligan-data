from datetime import datetime, timezone

from mtgmeta.drilldown import build_archetype_pages, build_event_pages

NOW = datetime(2026, 9, 30, 2, tzinfo=timezone.utc)


def tile(id, percentage, colors=None, key_cards=4):
    return {
        "name": id.replace("-", " ").title(),
        "id": id,
        "percentage": percentage,
        "deck_count": 10,
        "colors": ["R", "W"] if colors is None else colors,
        "key_cards": [{"name": f"{id} card {n}", "oracle_id": f"{id}-o{n}"} for n in range(key_cards)],
    }


def result(deck_id, date, finish="1st Place", event_id="1", event_name=None):
    return {
        "deck_id": deck_id,
        "date": f"{date}T00:00:00Z",
        "player": f"p{deck_id}",
        "event_id": event_id,
        "event_name": event_name or f"Modern Challenge 32 {date}",
        "finish": finish,
    }


def snapshot(meta, archetypes=None, events=None):
    return {
        "format": "modern",
        "meta": {window: {"archetypes": tiles} for window, tiles in meta.items()},
        "archetypes": {id: {"results": results} for id, results in (archetypes or {}).items()},
        "events": events or [],
    }


def test_an_archetype_page_has_its_tile_its_shares_and_its_decks_newest_first():
    document = snapshot(
        {"30d": [tile("a", 14.64, colors=["U"])], "7d": [tile("a", 9.05)]},
        {"a": [result("3", "2026-09-29"), result("2", "2026-09-28", "5-0", "2", "Modern League 2026-09-28 (1)"), result("1", "2026-09-20", "8th Place", None, "Local")]},
    )
    page = build_archetype_pages(document, NOW, {"3", "1"})["a"]
    assert list(page) == ["id", "name", "format", "colors", "key_cards", "shares", "decks"]
    assert (page["id"], page["name"], page["format"], page["colors"]) == ("a", "A", "modern", ["U"])
    assert [c["oracle_id"] for c in page["key_cards"]] == ["a-o0", "a-o1", "a-o2"]  # up to three
    assert page["shares"] == {"7d": 9.1, "14d": None, "30d": 14.6}  # one decimal, null where the window has none of it
    assert page["decks"] == [
        {"deck_id": "3", "date": "2026-09-29", "event_id": "1", "event_name": "Modern Challenge 32", "finish": "1st Place", "player": "p3", "published": True},
        {"deck_id": "2", "date": "2026-09-28", "event_id": "2", "event_name": "Modern League (1)", "finish": "5-0", "player": "p2", "published": False},
        {"deck_id": "1", "date": "2026-09-20", "event_id": None, "event_name": "Local", "finish": "8th Place", "player": "p1", "published": True},
    ]


def test_a_page_exists_for_every_archetype_of_every_window():
    document = snapshot({"30d": [tile("month", 5.0)], "14d": [tile("fortnight", 4.0), tile("month", 5.0)], "7d": [tile("week", 3.0)]})
    pages = build_archetype_pages(document, NOW, set())
    assert sorted(pages) == ["fortnight", "month", "week"]
    assert pages["week"]["shares"] == {"7d": 3.0, "14d": None, "30d": None}
    assert pages["month"]["decks"] == []  # in the metagame but with no results yet


def test_decks_are_dated_today_or_earlier_and_at_most_sixty():
    results = [result("future", "2026-11-04")]
    results += [result(str(n), "2026-09-30") for n in range(70)]
    results.append(result("older", "2026-09-01"))
    page = build_archetype_pages(snapshot({"30d": [tile("a", 5.0)]}, {"a": results}), NOW, set())["a"]
    assert len(page["decks"]) == 60
    assert "future" not in {deck["deck_id"] for deck in page["decks"]}
    assert [deck["deck_id"] for deck in page["decks"][:3]] == ["0", "1", "2"]  # a day's results keep the snapshot's order
    assert [deck["date"] for deck in page["decks"]] == sorted((deck["date"] for deck in page["decks"]), reverse=True)


def test_an_archetype_from_an_old_snapshot_has_no_colours_or_key_cards():
    old = {"name": "Old", "id": "old", "percentage": 1.0}
    page = build_archetype_pages(snapshot({"30d": [old]}), NOW, set())["old"]
    assert (page["colors"], page["key_cards"], page["shares"]["30d"]) == ([], [], 1.0)


def source_event(event_id, date, results, name=None, kind="mtgo_challenge"):
    return {
        "event_id": event_id,
        "event_name": name or f"Modern Challenge 32 {date}",
        "date": f"{date}T00:00:00Z",
        "url": f"https://www.mtggoldfish.com/tournament/{event_id}",
        "kind": kind,
        "source": "mtgo.com",
        "results": results,
    }


def entry(finish, deck_id, archetype_id="a", archetype="A"):
    return {"finish": finish, "player": f"p{deck_id}", "archetype": archetype, "archetype_id": archetype_id, "deck_id": deck_id}


def test_an_event_page_lists_its_results_in_order_with_two_key_cards_each():
    event = source_event("66947", "2026-09-29", [entry("1st Place", "10"), entry("2nd Place", "11", None, "UR Murktide"), entry("3rd Place", "12", "gone", "Gone")])
    pages = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=[event]), NOW, {"10"})
    assert list(pages) == ["66947"]
    page = pages["66947"]
    assert list(page) == ["id", "name", "date", "kind", "prestige", "source", "url", "format", "results"]
    assert (page["id"], page["name"], page["date"], page["kind"], page["prestige"], page["source"], page["format"]) == (
        "66947", "Modern Challenge 32", "2026-09-29", "mtgo_challenge", 2, "mtgo.com", "modern",
    )
    assert page["url"] == "https://www.mtggoldfish.com/tournament/66947"
    first, second, third = page["results"]
    assert list(first) == ["finish", "player", "archetype", "archetype_id", "deck_id", "published", "colors", "key_cards"]
    assert (first["finish"], first["archetype_id"], first["deck_id"], first["published"]) == ("1st Place", "a", "10", True)
    assert first["key_cards"] == [{"name": "a card 0", "oracle_id": "a-o0"}, {"name": "a card 1", "oracle_id": "a-o1"}]
    # A deck outside a tracked archetype keeps the pilot's title and has no key cards; so does one that left the metagame.
    assert (second["archetype"], second["archetype_id"], second["published"], second["key_cards"]) == ("UR Murktide", None, False, [])
    assert (third["archetype_id"], third["key_cards"]) == ("gone", [])


def test_event_pages_leave_out_events_still_to_be_played_and_take_the_date_out_of_the_name():
    events = [
        source_event("2", "2026-09-30", [entry("5-0", "1")], "Modern League 2026-09-30 (1)", "mtgo_league"),  # today counts
        source_event("3", "2026-11-04", [entry("1st Place", "2")], "Store Qualifier"),
    ]
    pages = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=events), NOW, set())
    assert list(pages) == ["2"]
    assert (pages["2"]["name"], pages["2"]["kind"]) == ("Modern League (1)", "mtgo_league")


def test_an_event_result_with_no_key_cards_takes_its_decks_two_most_played_non_lands():
    event = source_event("66947", "2026-09-29", [entry("5-0", "10", None, "Gruul Aggro"), entry("5-0", "11"), entry("5-0", "12", None, "Unknown Deck")])
    decks = {
        "10": {"m": [[4, "Mountain"], [2, "Bonecrusher Giant"], [4, "Kumano Faces Kakkazan"], [3, "Made-up Card"]], "s": []},
        "11": {"m": [[4, "Kumano Faces Kakkazan"]], "s": []},  # the tile has key cards, so it is used
    }
    catalog = {
        "mountain": {"name": "Mountain", "oracle_id": "o-mountain", "land": True},
        "bonecrusher-giant": {"name": "Bonecrusher Giant // Stomp", "oracle_id": "o-giant"},
        "kumano-faces-kakkazan": {"name": "Kumano Faces Kakkazan", "oracle_id": "o-kumano"},
    }
    page = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=[event]), NOW, {"10", "11"}, decks, catalog)["66947"]
    first, second, third = page["results"]
    # Four Kumano beat two Giants; the Mountain is a land, and the unknown name is skipped. The deck's own name is kept.
    assert first["key_cards"] == [{"name": "Kumano Faces Kakkazan", "oracle_id": "o-kumano"}, {"name": "Bonecrusher Giant", "oracle_id": "o-giant"}]
    assert [c["oracle_id"] for c in second["key_cards"]] == ["a-o0", "a-o1"]
    assert third["key_cards"] == []  # its deck isn't stored (published is false), so there is nothing to show


def test_an_archetype_tile_with_no_key_cards_takes_its_featured_decks_three_cards_led_by_the_namesake():
    document = snapshot({"30d": [tile("beanstalk-control", 5.0, key_cards=0), tile("b", 4.0, key_cards=4), tile("c", 3.0, key_cards=0)]}, {"beanstalk-control": [], "b": [], "c": []})
    document["archetypes"]["beanstalk-control"]["deck_id"] = "9"
    document["archetypes"]["b"]["deck_id"] = "9"  # a tile with key cards keeps them
    document["archetypes"]["c"]["deck_id"] = "8"  # its featured deck isn't stored
    decks = {"9": {"m": [[4, "Mountain"], [4, "Lightning Bolt"], [3, "Fertile Beanstalk"], [2, "Ocelot Pride"], [4, "Ragavan"]], "s": []}}
    catalog = {
        "mountain": {"name": "Mountain", "oracle_id": "o-mountain", "land": True},
        "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "o-bolt", "price": 1.0},
        "fertile-beanstalk": {"name": "Fertile Beanstalk", "oracle_id": "o-beanstalk"},
        "ocelot-pride": {"name": "Ocelot Pride", "oracle_id": "o-ocelot"},
        "ragavan": {"name": "Ragavan", "oracle_id": "o-ragavan", "price": 60.0},
    }
    pages = build_archetype_pages(document, NOW, set(), decks, catalog)
    assert [c["oracle_id"] for c in pages["beanstalk-control"]["key_cards"]] == ["o-beanstalk", "o-ragavan", "o-bolt"]  # the namesake, then the 4-ofs by price
    assert [c["oracle_id"] for c in pages["b"]["key_cards"]] == ["b-o0", "b-o1", "b-o2"]
    assert pages["c"]["key_cards"] == []
    assert build_archetype_pages(document, NOW, set())["beanstalk-control"]["key_cards"] == []  # without decks and a catalog, as before


PIPS = {
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "o-bolt", "mana_cost": "{R}"},
    "path-to-exile": {"name": "Path to Exile", "oracle_id": "o-path", "mana_cost": "{W}"},
    "sol-ring": {"name": "Sol Ring", "oracle_id": "o-ring", "mana_cost": "{1}"},
}


def test_an_event_has_its_prestige_by_its_kind_and_name():
    events = [
        source_event("1", "2026-09-29", [entry("1st Place", "1")], "Pro Tour Marvel Super Heroes 2026-09-29", "pro_tour"),
        source_event("2", "2026-09-29", [entry("1st Place", "2")], "Modern Challenge 64 2026-09-29"),
        source_event("3", "2026-09-29", [entry("1st Place", "3")]),
        source_event("4", "2026-09-29", [entry("5-0", "4")], "Modern League 2026-09-29", "mtgo_league"),
    ]
    pages = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=events), NOW, set())
    assert {event_id: page["prestige"] for event_id, page in pages.items()} == {"1": 4, "2": 3, "3": 2, "4": 1}


def test_an_event_results_colours_are_the_pages_then_the_decks_then_the_archetypes_else_null():
    event = source_event(
        "66947",
        "2026-09-29",
        [
            {**entry("1st Place", "10"), "colors": ["U", "B"]},  # what the event page showed
            entry("2nd Place", "11", None, "Rakdos"),  # its decklist
            entry("3rd Place", "12", None, "Artifacts"),  # a colourless decklist
            entry("4th Place", "13"),  # no deck stored: its archetype's tile
            entry("5th Place", "14", None, "Brew"),  # nothing known
        ],
    )
    decks = {"10": {"m": [[4, "Lightning Bolt"]], "s": []}, "11": {"m": [[4, "Lightning Bolt"]], "s": [[2, "Path to Exile"]]}, "12": {"m": [[4, "Sol Ring"]], "s": []}}
    page = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=[event]), NOW, set(), decks, PIPS)["66947"]
    assert [r["colors"] for r in page["results"]] == [["U", "B"], ["W", "R"], [], ["R", "W"], None]
    # Without decks or a catalog the tile and the page are all there is.
    bare = build_event_pages(snapshot({"30d": [tile("a", 5.0)]}, events=[event]), NOW, set())["66947"]
    assert [r["colors"] for r in bare["results"]] == [["U", "B"], None, None, ["R", "W"], None]


def test_an_archetype_page_takes_its_featured_decks_colours_when_its_tile_shows_none():
    document = snapshot({"30d": [tile("bare", 5.0, colors=[]), tile("shown", 4.0, colors=["U"]), tile("unstored", 3.0, colors=[])]}, {"bare": [], "shown": [], "unstored": []})
    document["archetypes"]["bare"]["deck_id"] = "9"
    document["archetypes"]["shown"]["deck_id"] = "9"
    document["archetypes"]["unstored"]["deck_id"] = "8"
    decks = {"9": {"m": [[4, "Lightning Bolt"]], "s": []}}
    pages = build_archetype_pages(document, NOW, set(), decks, PIPS)
    assert (pages["bare"]["colors"], pages["shown"]["colors"], pages["unstored"]["colors"]) == (["R"], ["U"], [])
    assert build_archetype_pages(document, NOW, set())["bare"]["colors"] == []  # without decks and a catalog, as before
