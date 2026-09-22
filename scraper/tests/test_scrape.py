from pathlib import Path

from mtgmeta.scrape import ScrapeConfig, scrape
from mtgmeta.store import JsonFileStore

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureBrowser:
    def __init__(self):
        self.deck_downloads = []

    def page(self, path):
        if path == "/tournaments/modern":
            return (FIXTURES / "tournaments_modern.html").read_text()
        if path == "/tournament/66753":
            return (FIXTURES / "tournament_66753.html").read_text()
        raise RuntimeError(f"503 on {path}")

    def metagame(self, format, days):
        return (FIXTURES / "metagame_modern.html").read_text()

    def deck_text(self, deck_id):
        self.deck_downloads.append(deck_id)
        return (FIXTURES / "deck_7967072.txt").read_text()


def test_scrape_writes_meta_events_and_only_new_decks(tmp_path):
    store = JsonFileStore(tmp_path)
    browser = FixtureBrowser()
    config = ScrapeConfig(formats=("modern",), events_per_format=2, max_new_decks=10)

    report = scrape(browser, store, config)

    assert report.meta == ["modern_30d"]
    # 66764 fails to load; 66753 is saved and the run carries on.
    assert report.events == ["66753"]
    assert len(report.errors) == 1 and "66764" in report.errors[0]
    assert report.decks_written == 10
    assert (tmp_path / "meta" / "modern_30d.json").exists()
    assert (tmp_path / "events" / "66753.json").exists()
    assert (tmp_path / "decks" / "7966104.json").exists()

    browser.deck_downloads.clear()
    second = scrape(browser, store, ScrapeConfig(formats=("modern",), events_per_format=2, max_new_decks=100))
    assert second.decks_skipped == 10
    assert second.decks_written == 22
    assert "7966104" not in browser.deck_downloads
