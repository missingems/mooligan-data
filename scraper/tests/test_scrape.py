import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from mtgmeta import mtgo, mtgtop8
from mtgmeta.http import PoliteClient
from mtgmeta.models import RunReport
from mtgmeta.scrape import ScrapeConfig, scrape
from mtgmeta.store import SnapshotStore

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)

MTGO = "https://www.mtgo.com"
TOP8 = "https://www.mtgtop8.com"
CHALLENGE = "modern-challenge-32-2026-11-0712857687"
LEAGUE_TODAY = "modern-league-2026-11-0811161"
LEAGUE_OLD = "modern-league-2026-11-0511161"
PAPER_DECKS = [str(number) for number in range(907298, 907314)]


def fixture(name):
    return (FIXTURES / name).read_text(encoding="latin-1")


def month_page():
    soup = BeautifulSoup(fixture("mtgo_decklists_2026_11.html"), "html.parser")
    for item in soup.select("li.decklists-item"):
        if item.find("a")["href"].removeprefix("/decklist/") not in (CHALLENGE, LEAGUE_TODAY, LEAGUE_OLD):
            item.decompose()
    return str(soup)


def format_page():
    soup = BeautifulSoup(fixture("mtgtop8_format_modern.html"), "html.parser")
    for row in soup.select("tr.hover_tr"):
        if not any(f"e={event}&" in link["href"] for link in row.find_all("a") for event in ("93409", "93441", "93285", "93303")):
            row.decompose()
    return str(soup)


def older_format_page():
    return (
        '<div class="w_title">Events 21 to 40</div><table>'
        "<tr class=hover_tr><td class=S14><a href=event?e=93105&f=MO>Regional Championship - MIT Championship</a></td>"
        "<td class=S12>01/11/26</td></tr></table>"
    )


def challenge_copy(challenge_players):
    """MTGTop8's page for the Challenge, with its sixteen decks held by the sixteen best players of the mtgo.com event."""
    html = fixture("mtgtop8_event_93409.html")
    for deck, player in zip(mtgtop8.parse_event(html, "93409").decks, challenge_players):
        html = html.replace(f">{deck.player}<", f">{player}<")
    return html


def challenge_players():
    ref = mtgo.EventRef("12857687", CHALLENGE, "modern", "Modern Challenge 32", datetime(2026, 11, 7, tzinfo=timezone.utc), "mtgo_challenge")
    event, _ = mtgo.parse_event(fixture("mtgo_modern_challenge_32_12857687.html"), ref)
    return [result.player for result in event.results]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def sleep(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


class Site:
    """The two sites as a table of url to (status, body), and the urls asked for."""

    def __init__(self):
        self.asked = []
        self.refused = set()
        self.pages = {
            f"{MTGO}/decklists/2026/11": month_page(),
            f"{MTGO}/decklists/2026/10": "<html></html>",
            f"{MTGO}/decklist/{CHALLENGE}": fixture("mtgo_modern_challenge_32_12857687.html"),
            f"{MTGO}/decklist/{LEAGUE_OLD}": fixture("mtgo_modern_league_11161.html"),
            f"{TOP8}/format?f=MO&meta=51": format_page(),
            f"{TOP8}/format?f=MO&meta=51&cp=2": older_format_page(),
            f"{TOP8}/event?e=93409&f=MO": challenge_copy(challenge_players()),
            f"{TOP8}/event?e=93285&f=MO": fixture("mtgtop8_event_93304.html"),
            f"{TOP8}/event?e=93303&f=MO": fixture("mtgtop8_event_93304.html"),
            f"{TOP8}/event?e=93105&f=MO": fixture("mtgtop8_event_93105.html"),
        }
        for deck_id in PAPER_DECKS:
            self.pages[f"{TOP8}/mtgo?d={deck_id}"] = fixture("mtgtop8_deck_909613.txt")

    def opener(self, url, headers, timeout):
        self.asked.append(url)
        if any(host in url for host in self.refused):
            return 403, {}, b""
        body = self.pages.get(url)
        return (404, {}, b"") if body is None else (200, {}, body.encode("latin-1", errors="replace"))

    def client(self, **options):
        clock = Clock()
        return PoliteClient(
            delay=10, opener=self.opener, sleep=clock.sleep, clock=clock, rng=random.Random(1), **options
        )


def run(root, site, client=None, now=NOW, **options):
    cfg = ScrapeConfig(formats=("modern",), **options)
    store = SnapshotStore(root, cfg.formats, cfg.history_days, now=now)
    client = client or site.client()
    report = scrape(client, store, cfg, now=now, report=RunReport())
    store.finish()
    return report, client


def snapshot(root):
    path = root / "snapshots" / "modern.json"
    return json.loads(path.read_text()) if path.exists() else {"meta": {}, "events": [], "archetypes": {}}


def events_by_id(root):
    return {event["event_id"]: event for event in snapshot(root)["events"]}


def deck(root, deck_id):
    return json.loads((root / "decks" / f"{deck_id}.json").read_text())


def test_a_challenge_is_saved_with_its_places_and_decks_named_by_mtgtop8(tmp_path):
    report, _ = run(tmp_path, Site())

    event = events_by_id(tmp_path)["mtgo-12857687"]
    assert (event["event_name"], event["kind"], event["source"]) == ("Modern Challenge 32", "mtgo_challenge", "mtgo.com")
    assert event["url"] == f"{MTGO}/decklist/{CHALLENGE}"
    assert [result["finish"] for result in event["results"][:3]] == ["1st Place", "2nd Place", "3rd Place"]
    assert len(event["results"]) == 32
    assert event["results"][0]["archetype"] == "Scepter Chant"
    assert event["results"][0]["archetype_id"] == "modern-scepter-chant"
    assert report.named_by_top8 == 16 and report.errors == []

    winner = deck(tmp_path, event["results"][0]["deck_id"])
    assert (winner["archetype"], winner["archetype_id"], winner["event_id"]) == ("Scepter Chant", "modern-scepter-chant", "mtgo-12857687")
    assert winner["mainboard"]


def test_a_recent_event_with_no_mtgtop8_copy_is_left_for_the_next_run(tmp_path):
    site = Site()
    run(tmp_path, site)

    assert "mtgo-11161-2026-11-08" not in events_by_id(tmp_path)
    assert f"{MTGO}/decklist/{LEAGUE_TODAY}" not in site.asked


def test_an_older_event_with_no_matching_copy_is_saved_without_an_mtgtop8_name(tmp_path):
    report, _ = run(tmp_path, Site())

    league = events_by_id(tmp_path)["mtgo-11161-2026-11-05"]
    assert (league["kind"], [result["finish"] for result in league["results"]]) == ("mtgo_league", ["5-0"] * 5)
    assert all(result["archetype"] for result in league["results"])
    assert report.named_by_top8 == 16


def test_a_paper_event_is_saved_with_top_n_finishes_and_its_decks(tmp_path):
    report, _ = run(tmp_path, Site())

    event = events_by_id(tmp_path)["t8-93105"]
    assert (event["event_name"], event["kind"], event["source"]) == (
        "Regional Championship - MIT Championship", "regional_championship", "melee.gg",
    )
    assert event["date"] == "2026-11-01T00:00:00Z"
    assert event["url"] == f"{TOP8}/event?e=93105&f=MO"
    assert [result["finish"] for result in event["results"]] == (
        ["1st Place", "2nd Place"] + ["Top 4"] * 2 + ["Top 8"] * 4 + ["Top 16"] * 8
    )
    first = event["results"][0]
    assert (first["deck_id"], first["archetype"], first["archetype_id"]) == ("t8-907298", "Rakdos Delirium", "modern-rakdos-delirium")
    assert deck(tmp_path, "t8-907298")["archetype_id"] == "modern-rakdos-delirium"
    assert all((tmp_path / "decks" / f"t8-{deck_id}.json").exists() for deck_id in PAPER_DECKS)
    assert report.errors == []


def test_an_mtgtop8_event_from_mtgo_com_is_not_saved_as_paper_and_not_asked_for_again(tmp_path):
    site = Site()
    run(tmp_path, site)
    assert "t8-93303" not in events_by_id(tmp_path)
    assert json.loads((tmp_path / "state" / "sources.json").read_text())["modern"]["seen"] == {"93303": "2026-11-05"}

    site.asked.clear()
    run(tmp_path, site)
    assert f"{TOP8}/event?e=93303&f=MO" not in site.asked


def test_the_metagame_windows_and_archetype_histories_come_from_the_stored_results(tmp_path):
    report, _ = run(tmp_path, Site(), now=datetime(2026, 11, 10, tzinfo=timezone.utc))

    meta = snapshot(tmp_path)["meta"]
    assert sorted(meta) == ["14d", "30d", "7d"]
    assert report.meta == ["modern_7d", "modern_14d", "modern_30d"]
    for window in meta.values():
        shares = [archetype["percentage"] for archetype in window["archetypes"]]
        assert shares == sorted(shares, reverse=True) and sum(shares) <= 100
    seven = {archetype["id"]: archetype for archetype in meta["7d"]["archetypes"]}
    thirty = {archetype["id"]: archetype for archetype in meta["30d"]["archetypes"]}
    assert "modern-reanimator" not in seven and "modern-reanimator" in thirty
    winner = events_by_id(tmp_path)["mtgo-12857687"]["results"][0]
    chant = seven["modern-scepter-chant"]
    assert (chant["name"], chant["deck_count"], chant["percentage"]) == ("Scepter Chant", 1, round(100 / 37, 1))
    assert (chant["deck_id"], chant["colors"], chant["key_cards"]) == (winner["deck_id"], [], [])
    assert thirty["modern-scepter-chant"]["deck_count"] == 4

    history = snapshot(tmp_path)["archetypes"]["modern-scepter-chant"]
    assert (history["name"], history["deck_id"], history["featured_player"]) == ("Scepter Chant", winner["deck_id"], winner["player"])
    assert {result["event_id"] for result in history["results"]} == {"mtgo-12857687", "t8-93105"}
    assert report.archetypes and all(name.startswith("modern_") for name in report.archetypes)


def test_the_featured_deck_is_the_newest_best_placed_one(tmp_path):
    run(tmp_path, Site())

    thirty = {archetype["id"]: archetype for archetype in snapshot(tmp_path)["meta"]["30d"]["archetypes"]}
    assert thirty["modern-rakdos-delirium"]["deck_id"] == "t8-907298"
    assert thirty["modern-scepter-chant"]["deck_id"] == events_by_id(tmp_path)["mtgo-12857687"]["results"][0]["deck_id"]


def test_the_first_run_makes_these_requests(tmp_path):
    site = Site()
    _, client = run(tmp_path, site)

    assert client.requests == len(site.asked) == 26
    assert site.asked[:2] == [f"{MTGO}/decklists/2026/11", f"{MTGO}/decklists/2026/10"]
    assert [url for url in site.asked if "/decklist/" in url] == [f"{MTGO}/decklist/{CHALLENGE}", f"{MTGO}/decklist/{LEAGUE_OLD}"]
    assert [url for url in site.asked if "/event?" in url] == [
        f"{TOP8}/event?e=93409&f=MO",
        f"{TOP8}/event?e=93285&f=MO",
        f"{TOP8}/event?e=93303&f=MO",
        f"{TOP8}/event?e=93105&f=MO",
    ]
    assert f"{TOP8}/event?e=93441&f=MO" not in site.asked


def test_a_second_run_asks_only_for_the_pages_that_list_events(tmp_path):
    site = Site()
    run(tmp_path, site)
    site.asked.clear()

    report, client = run(tmp_path, site)

    assert site.asked == [f"{MTGO}/decklists/2026/11", f"{MTGO}/decklists/2026/10", f"{TOP8}/format?f=MO&meta=51"]
    assert report.events == [] and report.decks_written == 0 and report.errors == []
    assert report.meta == ["modern_7d", "modern_14d", "modern_30d"]


@pytest.mark.parametrize("host, saved", [("www.mtgtop8.com", {"mtgo-11161-2026-11-05"}), ("www.mtgo.com", {"t8-93105"})])
def test_a_refusal_is_a_warning_and_stops_that_site_for_the_run_while_older_mtgo_events_still_go_out_named_by_lists(tmp_path, host, saved):
    site = Site()
    site.refused = {host}

    report, client = run(tmp_path, site)

    assert client.refusals == {host: "HTTP 403"}
    assert len([url for url in site.asked if host in url]) == 1
    assert len(report.warnings) == 1 and host in report.warnings[0]
    assert report.deck_block == f"{host}: HTTP 403" and report.errors == []
    assert set(events_by_id(tmp_path)) == saved


def test_a_run_that_runs_out_of_time_stops_cleanly_and_the_next_run_goes_on(tmp_path):
    site = Site()
    report, client = run(tmp_path, site, client=site.client(budget_minutes=1))

    assert 0 < client.requests < 26 and report.errors == []
    for event in snapshot(tmp_path)["events"]:
        assert all((tmp_path / "decks" / f"{result['deck_id']}.json").exists() for result in event["results"])

    run(tmp_path, site)
    assert set(events_by_id(tmp_path)) == {"mtgo-12857687", "mtgo-11161-2026-11-05", "t8-93105"}


def test_a_deck_that_does_not_parse_is_left_out_and_tried_once_more(tmp_path):
    site = Site()
    site.pages[f"{TOP8}/mtgo?d=907300"] = "<html>not a list</html>"
    run(tmp_path, site)
    assert not (tmp_path / "decks" / "t8-907300.json").exists()
    assert "t8-93105" in events_by_id(tmp_path)

    site.asked.clear()
    run(tmp_path, site)
    assert f"{TOP8}/mtgo?d=907300" in site.asked
    site.asked.clear()
    run(tmp_path, site)
    assert f"{TOP8}/mtgo?d=907300" not in site.asked
