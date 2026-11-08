import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mtgmeta.mtgo import EventRef, event_id, parse_event, parse_month
from mtgmeta.parsing import ParseError

FIXTURES = Path(__file__).parent / "fixtures"
CHALLENGE_SLUG = "modern-challenge-32-2026-11-0712857687"
LEAGUE_SLUG = "modern-league-2026-11-0811161"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def event_data(name: str) -> dict:
    html = fixture(name)
    marker = "window.MTGO.decklists.data = "
    return json.JSONDecoder().raw_decode(html[html.index(marker) + len(marker) :])[0]


def challenge_ref() -> EventRef:
    return EventRef("12857687", CHALLENGE_SLUG, "modern", "Modern Challenge 32", datetime(2026, 11, 7, tzinfo=timezone.utc), "mtgo_challenge")


def league_ref() -> EventRef:
    return EventRef("11161", LEAGUE_SLUG, "modern", "Modern League", datetime(2026, 11, 8, tzinfo=timezone.utc), "mtgo_league")


def event_page(decklists: list) -> str:
    return "<script>window.MTGO.decklists.data = " + json.dumps({"name": "Modern League", "decklists": decklists}) + ";</script>"


def test_month_lists_the_events_in_supported_formats():
    refs = parse_month(fixture("mtgo_decklists_2026_11.html"))
    assert len(refs) == 111
    assert {ref.format for ref in refs} == {"modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "duel_commander"}
    assert len({ref.slug for ref in refs}) == len(refs)
    assert {ref.kind for ref in refs} == {"mtgo_challenge", "mtgo_league"}
    assert sum(ref.kind == "mtgo_league" for ref in refs) == 64


def test_month_reads_a_challenge_and_a_league():
    refs = {ref.slug: ref for ref in parse_month(fixture("mtgo_decklists_2026_11.html"))}
    assert refs[CHALLENGE_SLUG] == challenge_ref()
    assert refs[LEAGUE_SLUG] == league_ref()
    assert event_id(refs[CHALLENGE_SLUG]) == "mtgo-12857687"
    assert event_id(refs[LEAGUE_SLUG]) == "mtgo-11161-2026-11-08"


def test_month_reads_showcases_and_duel_commander():
    refs = {ref.slug: ref for ref in parse_month(fixture("mtgo_decklists_2026_11.html"))}
    showcase = refs["pioneer-showcase-challenge-2026-11-0112857433"]
    assert (showcase.format, showcase.kind, showcase.name) == ("pioneer", "mtgo_challenge", "Pioneer Showcase Challenge")
    commander = next(ref for ref in refs.values() if ref.format == "duel_commander")
    assert commander.slug.startswith("duel-commander-")


def test_month_skips_unsupported_formats():
    html = """
    <ul>
      <li class="decklists-item"><a class="decklists-link" href="/decklist/limited-league-2026-11-0811200"><h3>Limited League</h3></a></li>
      <li class="decklists-item"><a class="decklists-link" href="/decklist/modern-league-2026-11-0811161"><h3>Modern League</h3></a></li>
    </ul>
    """
    assert [ref.slug for ref in parse_month(html)] == [LEAGUE_SLUG]


def test_challenge_event_has_every_player_placed():
    event, decks = parse_event(fixture("mtgo_modern_challenge_32_12857687.html"), challenge_ref())
    data = event_data("mtgo_modern_challenge_32_12857687.html")
    assert (event.event_id, event.event_name, event.format, event.kind, event.source) == ("mtgo-12857687", "Modern Challenge 32", "modern", "mtgo_challenge", "mtgo.com")
    assert event.date == datetime(2026, 11, 7, tzinfo=timezone.utc)
    assert event.url == f"https://www.mtgo.com/decklist/{CHALLENGE_SLUG}"
    assert len(event.results) == len(decks) == 32

    winner = next(row["loginid"] for row in data["final_rank"] if row["rank"] == "1")
    winner_player = next(decklist["player"] for decklist in data["decklists"] if decklist["loginid"] == winner)
    assert (event.results[0].player, event.results[0].finish) == (winner_player, "1st Place")

    finishes = [result.finish for result in event.results]
    assert finishes[:4] == ["1st Place", "2nd Place", "3rd Place", "4th Place"]
    assert finishes[10:13] == ["11th Place", "12th Place", "13th Place"]
    assert finishes[20:22] == ["21st Place", "22nd Place"]
    assert len(set(finishes)) == 32
    assert all(result.archetype == "" and result.archetype_id is None and result.colors is None for result in event.results)


def test_challenge_decks_match_their_results():
    event, decks = parse_event(fixture("mtgo_modern_challenge_32_12857687.html"), challenge_ref())
    assert {result.deck_id for result in event.results} == {deck.deck_id for deck in decks}
    deck = next(deck for deck in decks if deck.deck_id == "mtgo-58709847")
    assert (deck.player, deck.archetype, deck.format, deck.event_id, deck.archetype_id) == ("O_danielakos", "", "modern", "mtgo-12857687", None)
    assert sum(card.quantity for card in deck.mainboard) == 60
    assert sum(card.quantity for card in deck.sideboard) == 15
    assert deck.mainboard[0].card_name == "Bloodstained Mire" and deck.mainboard[0].quantity == 3
    assert next(result.finish for result in event.results if result.deck_id == deck.deck_id) == "22nd Place"


def test_league_event_lists_the_five_zero_decks():
    event, decks = parse_event(fixture("mtgo_modern_league_11161.html"), league_ref())
    data = event_data("mtgo_modern_league_11161.html")
    assert (event.event_id, event.event_name, event.kind, event.source) == ("mtgo-11161-2026-11-08", "Modern League", "mtgo_league", "mtgo.com")
    assert event.date == datetime(2026, 11, 8, tzinfo=timezone.utc)
    assert event.url == f"https://www.mtgo.com/decklist/{LEAGUE_SLUG}"
    assert [result.finish for result in event.results] == ["5-0"] * 5
    assert [result.player for result in event.results] == [decklist["player"] for decklist in data["decklists"]]
    assert len({deck.deck_id for deck in decks}) == 5
    assert all(deck.event_id == event.event_id for deck in decks)
    assert all(deck.deck_id.startswith("mtgo-") for deck in decks)


def test_duplicate_card_names_are_summed():
    def entry(name: str, qty: str) -> dict:
        return {"qty": qty, "card_attributes": {"card_name": name}}

    decklist = {
        "loginplayeventcourseid": "7",
        "loginid": "1",
        "player": "Someone",
        "main_deck": [entry("Island", "4"), entry("Opt", "2"), entry("Island", "3")],
        "sideboard_deck": [entry("Negate", "1"), entry("Negate", "2")],
    }
    _, decks = parse_event(event_page([decklist]), league_ref())
    assert [(card.quantity, card.card_name) for card in decks[0].mainboard] == [(7, "Island"), (2, "Opt")]
    assert [(card.quantity, card.card_name) for card in decks[0].sideboard] == [(3, "Negate")]
    assert decks[0].deck_id == "mtgo-7"


def test_event_without_data_raises():
    with pytest.raises(ParseError):
        parse_event("<html><body>Not found</body></html>", challenge_ref())
    with pytest.raises(ParseError):
        parse_event("<script>window.MTGO.decklists.data = {oops;</script>", challenge_ref())
