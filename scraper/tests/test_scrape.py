import json
from datetime import datetime, timezone
from pathlib import Path

from mtgmeta.scrape import ScrapeConfig, scrape
from mtgmeta.store import SnapshotStore

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
EMPTY_DECKS_PAGE = "<table><tr><th>Date</th><th>Deck</th><th>Author</th><th>Event</th><th>Place</th></tr></table>"


class FixtureBrowser:
    def __init__(self, event_pages=("66753",)):
        self.event_pages = set(event_pages)
        self.requests = []
        self.deck_downloads = []

    def page(self, path):
        self.requests.append(path)
        if path.startswith("/deck/download/"):
            self.deck_downloads.append(path.rsplit("/", 1)[1])
            return (FIXTURES / "deck_7967072.txt").read_text()
        if path == "/tournaments/modern":
            return (FIXTURES / "tournaments_modern.html").read_text()
        if path.startswith("/tournament_searches/create?"):
            # Page 1 is a real results page that says a next page exists; page 2 is empty.
            if path.endswith("&page=1"):
                return (FIXTURES / "tournament_search_modern_p2.html").read_text()
            return "<table><tr><th>Date</th><th>Name</th><th>Format</th><th>Decklists</th></tr></table>"
        if path.startswith("/tournament/") and path.rsplit("/", 1)[1] in self.event_pages:
            return (FIXTURES / "tournament_66753.html").read_text()
        if path == "/archetype/modern-izzet-prowess/decks?page=1":
            return (FIXTURES / "archetype_decks_modern_izzet_prowess.html").read_text()
        if path.startswith("/archetype/") and "/decks?page=" in path:
            return EMPTY_DECKS_PAGE
        if path.startswith("/archetype/"):
            # Give each archetype a featured deck of its own.
            deck_id = {"/archetype/modern-izzet-prowess": "9000001", "/archetype/modern-eldrazi": "9000002"}[path]
            return (FIXTURES / "archetype_modern_izzet_prowess.html").read_text().replace("7945486", deck_id)
        raise RuntimeError(f"503 on {path}")

    def metagame(self, format, days):
        return (FIXTURES / "metagame_modern.html").read_text(), True

    def fetch_pages(self, paths):
        results = {}
        for path in paths:
            try:
                results[path] = self.page(path)
            except Exception as error:
                results[path] = error
        return results


def run(root, browser, cfg):
    """One scrape as the workflow runs it: load the directory, scrape, publish."""
    store = SnapshotStore(root, cfg.formats, cfg.history_days, now=NOW)
    report = scrape(browser, store, cfg, now=NOW)
    store.finish()
    return report


def snapshot(root):
    return json.loads((root / "snapshots" / "modern.json").read_text())


def deck(root, deck_id):
    return json.loads((root / "decks" / f"{deck_id}.json").read_text())


def config(**overrides):
    values = dict(formats=("modern",), events_per_format=2, max_new_events=0, max_new_decks=10, archetype_decks=2)
    values.update(overrides)
    return ScrapeConfig(**values)


def test_scrape_publishes_meta_archetypes_events_and_decks(tmp_path):
    browser = FixtureBrowser()

    report = run(tmp_path, browser, config())

    assert report.meta == ["modern_30d"]
    assert report.archetypes == ["modern_modern-izzet-prowess", "modern_modern-eldrazi"]
    # 66764 fails to load; 66753 is saved and the run carries on.
    assert report.events == ["66753"]
    assert len(report.errors) == 1 and "66764" in report.errors[0]

    published = snapshot(tmp_path)
    meta = published["meta"]["30d"]
    assert [a.get("deck_id") for a in meta["archetypes"]] == ["9000001", "9000002", None, None, None, None]

    izzet = published["archetypes"]["modern-izzet-prowess"]
    assert (izzet["name"], izzet["deck_id"], izzet["featured_player"]) == ("Izzet Prowess", "9000001", "Roy Varney")
    assert len(izzet["results"]) == 12
    assert izzet["results"][0] == {
        "deck_id": "7966110",
        "date": "2026-09-21T00:00:00Z",
        "player": "Xsper",
        "event_id": "66753",
        "event_name": "Modern Challenge 32 2026-09-21",
        "finish": "13th Place",
    }

    # Event rows of a tracked archetype carry its name and id.
    event = next(e for e in published["events"] if e["event_id"] == "66753")
    xsper = next(r for r in event["results"] if r["deck_id"] == "7966110")
    assert (xsper["archetype"], xsper["archetype_id"]) == ("Izzet Prowess", "modern-izzet-prowess")

    # Featured decks come first, then the newest results, up to the budget.
    assert report.decks_written == 10
    assert browser.deck_downloads[:2] == ["9000001", "9000002"]
    assert deck(tmp_path, "9000001")["event_id"] is None
    assert deck(tmp_path, "7966110")["archetype"] == "Izzet Prowess"
    # A deck carries its archetype's id, so the app can open the archetype from the deck.
    assert deck(tmp_path, "7966110")["archetype_id"] == "modern-izzet-prowess"
    assert deck(tmp_path, "9000001")["archetype_id"] == "modern-izzet-prowess"
    assert len(json.loads((tmp_path / "state" / "deck-ids.json").read_text())) == 10


def test_a_second_run_reads_one_page_and_keeps_the_history(tmp_path):
    run(tmp_path, FixtureBrowser(), config())
    browser = FixtureBrowser()

    report = run(tmp_path, browser, config(max_new_decks=100))

    # Page 1 held nothing new, so page 2 was never asked for.
    assert "/archetype/modern-izzet-prowess/decks?page=2" not in browser.requests
    assert len(snapshot(tmp_path)["archetypes"]["modern-izzet-prowess"]["results"]) == 12
    assert report.decks_skipped == 10
    assert not set(browser.deck_downloads) & {"9000001", "9000002", "7966110"}


def test_history_older_than_the_window_is_dropped(tmp_path):
    run(tmp_path, FixtureBrowser(), config(history_days=3))
    dates = {r["date"][:10] for r in snapshot(tmp_path)["archetypes"]["modern-izzet-prowess"]["results"]}
    assert dates == {"2026-09-20", "2026-09-21"}  # 2026-09-16 is out


def test_events_found_through_archetypes_are_read(tmp_path):
    browser = FixtureBrowser(event_pages=("66753", "66742", "66728"))

    report = run(tmp_path, browser, config(max_new_events=2, max_new_decks=0))

    # The two newest events the Izzet list mentions that the tournaments list did not.
    assert report.events == ["66753", "66742", "66728"]


def test_rows_and_events_of_known_duplicates_are_skipped(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "duplicate-event-ids.json").write_text('["66742"]')
    # Only 66753 has a page: the fixture would otherwise make every event look identical.
    browser = FixtureBrowser(event_pages=("66753",))

    report = run(tmp_path, browser, config(max_new_events=5, max_new_decks=0))

    assert "66742" not in report.events
    assert "/tournament/66742" not in browser.requests
    results = snapshot(tmp_path)["archetypes"]["modern-izzet-prowess"]["results"]
    assert "66742" not in {r["event_id"] for r in results} and len(results) == 8


def test_each_format_has_its_own_deck_allowance(tmp_path):
    browser = FixtureBrowser()
    browser_page = browser.page

    def page(path):
        # Serve the Modern fixtures for a second format too.
        return browser_page(path.replace("/tournaments/legacy", "/tournaments/modern").replace("legacy-", "modern-"))

    browser.page = page
    report = run(tmp_path, browser, config(formats=("modern", "legacy"), max_new_decks=3))
    # A shared allowance would stop at 3 in total; each format gets its own 3.
    assert report.decks_written == 6
    assert len(browser.deck_downloads) == 6


def test_decks_mtggoldfish_no_longer_serves_are_skipped_next_run(tmp_path):
    browser = FixtureBrowser()
    browser_page = browser.page

    def page(path):
        # A deleted deck redirects to a page instead of a list.
        if path == "/deck/download/7966110":
            browser.deck_downloads.append("7966110")
            return "<!DOCTYPE html><html><head><title>Metagame</title></head><body></body></html>"
        return browser_page(path)

    browser.page = page
    report = run(tmp_path, browser, config())
    assert report.errors == ["event 66764: 503 on /tournament/66764"]  # the dead deck is not an error
    assert json.loads((tmp_path / "state" / "missing-deck-ids.json").read_text()) == ["7966110"]

    second = FixtureBrowser()
    run(tmp_path, second, config(max_new_decks=100))
    assert "7966110" not in second.deck_downloads


def test_an_unwindowed_metagame_is_published_once(tmp_path):
    browser = FixtureBrowser()
    browser.metagame = lambda format, days: ((FIXTURES / "metagame_modern.html").read_text(), False)
    report = run(tmp_path, browser, config(meta_days=("30", "7")))
    assert report.meta == ["modern_30d"]
    assert list(snapshot(tmp_path)["meta"]) == ["30d"]


def test_a_run_publishes_card_pages_for_what_the_decks_play(tmp_path):
    run(tmp_path, FixtureBrowser(), config())

    index = json.loads((tmp_path / "cards" / "index.json").read_text())
    assert index["cards"]["lightning-bolt"] == {"name": "Lightning Bolt", "formats": ["modern"]}
    bolt = json.loads((tmp_path / "cards" / "lightning-bolt.json").read_text())
    modern = bolt["formats"]["modern"]
    # Every fixture deck is the same Izzet list. 9 of the 10 downloaded are counted:
    # Eldrazi has no results in the fixture, so neither it nor its featured deck is published.
    assert (modern["decks"], modern["of_decks"]) == (9, 9)
    assert modern["archetypes"][0]["archetype_id"] == "modern-izzet-prowess"
    assert modern["archetypes"][0]["deck_ids"][0] in modern["archetypes"][0]["deck_ids"]

    # A run that finds nothing new rewrites no card page, only the index.
    before = {p.name for p in (tmp_path / "cards").glob("*.json")}
    for path in (tmp_path / "cards").glob("*.json"):
        path.unlink()
    run(tmp_path, FixtureBrowser(), config(max_new_decks=0))
    after = {p.name for p in (tmp_path / "cards").glob("*.json")}
    assert after == {"index.json"} and len(before) > 10


def test_events_come_from_the_tournament_search_and_carry_their_kind(tmp_path):
    browser = FixtureBrowser(event_pages=("66753", "66742", "66728", "66737", "66723", "66651", "66660"))

    report = run(tmp_path, browser, config(max_new_events=6, max_new_decks=0))

    # After the tournaments list's own: the newest unstored events first, whether the
    # archetype lists mention them (66742, 66728, 66737, 66723) or only the search does.
    assert report.events == ["66753", "66742", "66728", "66737", "66723", "66651", "66660"]
    searched = [p for p in browser.requests if p.startswith("/tournament_searches/create?")]
    assert len(searched) == 2 and "tournament_search%5Bformat%5D=modern" in searched[0]
    # Every fixture event page is the same, so the duplicate check keeps one; it carries its tier and source.
    events = snapshot(tmp_path)["events"]
    assert len(events) == 1 and (events[0]["kind"], events[0]["source"]) == ("mtgo_challenge", "mtgo.com")
