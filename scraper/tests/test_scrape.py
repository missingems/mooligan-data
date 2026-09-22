import json
from datetime import datetime, timezone
from pathlib import Path

from mtgmeta.scrape import ScrapeConfig, scrape
from mtgmeta.store import JsonFileStore

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
        if path == "/tournaments/modern":
            return (FIXTURES / "tournaments_modern.html").read_text()
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
        return (FIXTURES / "metagame_modern.html").read_text()

    def deck_text(self, deck_id):
        self.deck_downloads.append(deck_id)
        return (FIXTURES / "deck_7967072.txt").read_text()


def read(root, collection, doc_id):
    return json.loads((root / collection / f"{doc_id}.json").read_text())


def config(**overrides):
    values = dict(formats=("modern",), events_per_format=2, max_new_events=0, max_new_decks=10, archetype_decks=2)
    values.update(overrides)
    return ScrapeConfig(**values)


def test_scrape_writes_meta_archetypes_events_and_decks(tmp_path):
    store = JsonFileStore(tmp_path)
    browser = FixtureBrowser()

    report = scrape(browser, store, config(), now=NOW)

    assert report.meta == ["modern_30d"]
    assert report.archetypes == ["modern_modern-izzet-prowess", "modern_modern-eldrazi"]
    # 66764 fails to load; 66753 is saved and the run carries on.
    assert report.events == ["66753"]
    assert len(report.errors) == 1 and "66764" in report.errors[0]

    meta = read(tmp_path, "meta", "modern_30d")
    assert [a.get("deck_id") for a in meta["archetypes"]] == ["9000001", "9000002", None, None, None, None]

    izzet = read(tmp_path, "archetypes", "modern_modern-izzet-prowess")
    assert (izzet["name"], izzet["deck_id"], izzet["featured_player"]) == ("Izzet Prowess", "9000001", "Roy Varney")
    assert len(izzet["results"]) == 12
    assert izzet["results"][0] == {
        "deck_id": "7966110",
        "date": "2026-09-21T00:00:00+00:00",
        "player": "Xsper",
        "event_id": "66753",
        "event_name": "Modern Challenge 32 2026-09-21",
        "finish": "13th Place",
    }

    # Event rows of a tracked archetype carry its name and id.
    event = read(tmp_path, "events", "66753")
    xsper = next(r for r in event["results"] if r["deck_id"] == "7966110")
    assert (xsper["archetype"], xsper["archetype_id"]) == ("Izzet Prowess", "modern-izzet-prowess")

    # Featured decks come first, then the newest results, up to the budget.
    assert report.decks_written == 10
    assert browser.deck_downloads[:2] == ["9000001", "9000002"]
    assert read(tmp_path, "decks", "9000001")["event_id"] is None
    assert read(tmp_path, "decks", "7966110")["archetype"] == "Izzet Prowess"


def test_a_second_run_reads_one_page_and_keeps_the_history(tmp_path):
    store = JsonFileStore(tmp_path)
    scrape(FixtureBrowser(), store, config(), now=NOW)
    browser = FixtureBrowser()

    report = scrape(browser, store, config(max_new_decks=100), now=NOW)

    # Page 1 held nothing new, so page 2 was never asked for.
    assert "/archetype/modern-izzet-prowess/decks?page=2" not in browser.requests
    assert len(read(tmp_path, "archetypes", "modern_modern-izzet-prowess")["results"]) == 12
    assert report.decks_skipped == 10
    assert not set(browser.deck_downloads) & {"9000001", "9000002", "7966110"}


def test_history_older_than_the_window_is_dropped(tmp_path):
    store = JsonFileStore(tmp_path)
    scrape(FixtureBrowser(), store, config(history_days=3), now=NOW)
    dates = {r["date"][:10] for r in read(tmp_path, "archetypes", "modern_modern-izzet-prowess")["results"]}
    assert dates == {"2026-09-20", "2026-09-21"}  # 2026-09-16 is out


def test_events_found_through_archetypes_are_read(tmp_path):
    store = JsonFileStore(tmp_path)
    browser = FixtureBrowser(event_pages=("66753", "66742", "66728"))

    report = scrape(browser, store, config(max_new_events=2, max_new_decks=0), now=NOW)

    # The two newest events the Izzet list mentions that the tournaments list did not.
    assert report.events == ["66753", "66742", "66728"]
