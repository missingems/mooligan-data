import json
from pathlib import Path

from mtgmeta.scrape import ScrapeConfig, scrape
from mtgmeta.store import JsonFileStore

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureBrowser:
    def __init__(self):
        self.deck_downloads = []
        self.archetype_deck_ids = {}

    def page(self, path):
        if path == "/tournaments/modern":
            return (FIXTURES / "tournaments_modern.html").read_text()
        if path == "/tournament/66753":
            return (FIXTURES / "tournament_66753.html").read_text()
        if path.startswith("/archetype/"):
            # Give each archetype a deck id of its own.
            html = (FIXTURES / "archetype_modern_izzet_prowess.html").read_text()
            deck_id = self.archetype_deck_ids.setdefault(path, str(9000001 + len(self.archetype_deck_ids)))
            return html.replace("7945486", deck_id)
        raise RuntimeError(f"503 on {path}")

    def metagame(self, format, days):
        return (FIXTURES / "metagame_modern.html").read_text()

    def deck_text(self, deck_id):
        self.deck_downloads.append(deck_id)
        return (FIXTURES / "deck_7967072.txt").read_text()


def test_scrape_writes_meta_events_and_only_new_decks(tmp_path):
    store = JsonFileStore(tmp_path)
    browser = FixtureBrowser()
    config = ScrapeConfig(formats=("modern",), events_per_format=2, max_new_decks=10, archetype_decks=2)

    report = scrape(browser, store, config)

    assert report.meta == ["modern_30d"]
    # 66764 fails to load; 66753 is saved and the run carries on.
    assert report.events == ["66753"]
    assert len(report.errors) == 1 and "66764" in report.errors[0]
    # Two featured archetype decks, then ten event decks.
    assert report.decks_written == 12
    meta = json.loads((tmp_path / "meta" / "modern_30d.json").read_text())
    featured = [archetype.get("deck_id") for archetype in meta["archetypes"]]
    assert featured[:2] == ["9000001", "9000002"] and featured[2:] == [None] * 4
    featured_deck = json.loads((tmp_path / "decks" / "9000001.json").read_text())
    assert (featured_deck["archetype"], featured_deck["player"], featured_deck["event_id"]) == ("Izzet Prowess", "Roy Varney", None)
    assert (tmp_path / "events" / "66753.json").exists()
    assert (tmp_path / "decks" / "7966104.json").exists()

    browser.deck_downloads.clear()
    second = scrape(browser, store, ScrapeConfig(formats=("modern",), events_per_format=2, max_new_decks=100, archetype_decks=2))
    assert second.decks_skipped == 10
    assert second.decks_written == 22
    assert "7966104" not in browser.deck_downloads
