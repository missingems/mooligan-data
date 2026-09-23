from mtgmeta.cards import FormatDecks, build_card_pages, slug


def deck(main, side=()):
    return {"m": [list(card) for card in main], "s": [list(card) for card in side]}


CONTENTS = {
    # Two Izzet decks and one Eldrazi deck, newest first.
    "d1": deck([(4, "Lightning Bolt"), (4, "Monastery Swiftspear")], [(2, "Unholy Heat")]),
    "d2": deck([(3, "Lightning Bolt"), (1, "Unholy Heat")], [(3, "Unholy Heat")]),
    "d3": deck([(4, "Eldrazi Temple")]),
}
ARCHETYPES = {
    "d1": ("modern-izzet-prowess", "Izzet Prowess"),
    "d2": ("modern-izzet-prowess", "Izzet Prowess"),
    "d3": ("modern-eldrazi", "Eldrazi"),
}


def test_slug():
    assert slug("Fable of the Mirror-Breaker") == "fable-of-the-mirror-breaker"
    assert slug("Fire // Ice") == "fire"
    assert slug("Fire/Ice") == "fire", "MTGGoldfish writes split cards with one slash"
    assert slug("Bartolomé del Presidio") == "bartolome-del-presidio"
    assert slug("Bartolome del Presidio") == "bartolome-del-presidio"


def test_a_card_page_counts_decks_and_archetypes():
    pages, index = build_card_pages({"modern": FormatDecks(CONTENTS, ARCHETYPES)}, "2026-09-23T00:00:00Z")

    bolt = pages["lightning-bolt"]
    assert bolt["card_name"] == "Lightning Bolt" and bolt["slug"] == "lightning-bolt"
    modern = bolt["formats"]["modern"]
    assert (modern["decks"], modern["of_decks"]) == (2, 3)
    assert modern["archetypes"] == [
        {
            "archetype_id": "modern-izzet-prowess",
            "name": "Izzet Prowess",
            "decks": 2,
            "avg_copies": 3.5,
            "deck_ids": ["d1", "d2"],
        }
    ]
    # A card in both boards counts as one deck, and its copies add up.
    assert pages["unholy-heat"]["formats"]["modern"]["archetypes"][0]["avg_copies"] == 3.0
    assert pages["unholy-heat"]["formats"]["modern"]["decks"] == 2
    assert index["cards"]["eldrazi-temple"] == {"name": "Eldrazi Temple", "formats": ["modern"]}


def test_a_card_played_in_two_formats_has_an_entry_for_each():
    legacy = FormatDecks({"d9": deck([(4, "Lightning Bolt")])}, {"d9": ("legacy-burn", "Burn")})
    pages, index = build_card_pages(
        {"modern": FormatDecks(CONTENTS, ARCHETYPES), "legacy": legacy}, "2026-09-23T00:00:00Z"
    )
    assert sorted(pages["lightning-bolt"]["formats"]) == ["legacy", "modern"]
    assert index["cards"]["lightning-bolt"]["formats"] == ["legacy", "modern"]
    assert pages["lightning-bolt"]["formats"]["legacy"]["of_decks"] == 1


def test_decks_without_a_tracked_archetype_are_grouped_as_other():
    pages, _ = build_card_pages({"modern": FormatDecks(CONTENTS, {})}, "2026-09-23T00:00:00Z")
    archetypes = pages["lightning-bolt"]["formats"]["modern"]["archetypes"]
    assert archetypes == [{"archetype_id": None, "name": "Other", "decks": 2, "avg_copies": 3.5, "deck_ids": ["d1", "d2"]}]
