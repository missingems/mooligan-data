import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mtgmeta.browser import BlockedError, Fetched
from mtgmeta.pacing import Pacer
from mtgmeta.models import Event, EventResult, EventSummary, RunReport
from mtgmeta.scrape import ScrapeConfig, _events_to_reread, _read_events, scrape
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

    def fetch_batch(self, paths):
        """What the browser's fetch() gives: a body for a page, and a 503 for a path that raises."""
        answers = []
        for path in paths:
            try:
                answers.append(Fetched(path, 200, self.page(path)))
            except Exception as error:
                answers.append(Fetched(path, 503, str(error)))
        return answers

    def fetch_pages(self, paths):
        results = {}
        for path in paths:
            try:
                results[path] = self.page(path)
            except Exception as error:
                results[path] = error
        return results


def quiet_pacer(cfg):
    """A pacer that skips its waiting, so a scrape takes no time."""
    return Pacer(cfg.deck_pacing, random.Random(7), sleep=lambda seconds: None)


def run(root, browser, cfg):
    """One scrape as the workflow runs it: load the directory, scrape, publish."""
    store = SnapshotStore(root, cfg.formats, cfg.history_days, now=NOW)
    report = scrape(browser, store, cfg, now=NOW, pacer=quiet_pacer(cfg))
    store.finish()
    return report


def snapshot(root):
    return json.loads((root / "snapshots" / "modern.json").read_text())


def deck(root, deck_id):
    return json.loads((root / "decks" / f"{deck_id}.json").read_text())


def config(**overrides):
    values = dict(formats=("modern",), events_per_format=2, max_new_events=0, max_new_decks=10, archetype_decks=2, recheck_days=1)
    values.update(overrides)
    return ScrapeConfig(**values)


def test_scrape_publishes_meta_archetypes_events_and_decks(tmp_path):
    browser = FixtureBrowser()

    report = run(tmp_path, browser, config())

    assert report.meta == ["modern_30d"]
    assert report.archetypes == ["modern_modern-izzet-prowess", "modern_modern-eldrazi"]
    # 66764 fails to load; 66753 is saved and the run carries on.
    assert report.events == ["66753"]
    assert len(report.errors) == 2 and "66764" in report.errors[0] and "66742" in report.errors[1]

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

    # Featured decks rank first, so they are in the first visits; the rest are the newest, up to the budget.
    assert report.decks_written == 10
    assert {"9000001", "9000002"} <= set(browser.deck_downloads[:6])
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
    assert report.errors == ["event 66764: 503 on /tournament/66764", "event 66742: 503 on /tournament/66742"]  # the dead deck is not an error
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



class WindowBrowser(FixtureBrowser):
    """Serves the fixture metagame, except a window in `failures`: its errors are raised in turn, then it is served too."""

    def __init__(self, failures):
        super().__init__()
        self.failures = {days: list(errors) for days, errors in failures.items()}
        self.loads = []

    def metagame(self, format, days):
        self.loads.append(days)
        if self.failures.get(days):
            error = self.failures[days].pop(0)
            if isinstance(error, str):
                return error, True  # a page that loaded, without tiles
            raise error
        return super().metagame(format, days)


def meta_messages(messages):
    return [message for message in messages if message.startswith("meta")]


def test_a_window_that_cannot_be_read_is_a_warning_and_the_last_one_stays(tmp_path):
    run(tmp_path, FixtureBrowser(), config(meta_days=("30", "14")))
    before = snapshot(tmp_path)["meta"]["14d"]

    # Penny Dreadful from 17 to 28 October 2026, on every run.
    stuck = TimeoutError("The modern metagame did not switch to 14 days")
    report = run(tmp_path, WindowBrowser({"14": [stuck, stuck]}), config(meta_days=("30", "14")))

    assert report.meta == ["modern_30d"] and meta_messages(report.errors) == []
    assert meta_messages(report.warnings) == [
        "meta modern 14d: The modern metagame did not switch to 14 days (the snapshot keeps the last 14d window read)"
    ]
    assert snapshot(tmp_path)["meta"]["14d"] == before


def test_a_window_is_loaded_again_after_a_browser_error(tmp_path):
    # Modern's 14 days on 16 October 2026: a script hung once.
    browser = WindowBrowser({"14": [RuntimeError("Message: script timeout")]})
    report = run(tmp_path, browser, config(meta_days=("30", "14")))
    assert report.meta == ["modern_30d", "modern_14d"] and meta_messages(report.warnings) == []
    assert browser.loads == ["30", "14", "14"]


def test_a_window_without_tiles_is_not_loaded_again(tmp_path):
    # Penny Dreadful's 7 days on 23 and 24 October 2026 had no decks.
    browser = WindowBrowser({"7": ["<html></html>"]})
    report = run(tmp_path, browser, config(meta_days=("30", "7")))
    assert browser.loads == ["30", "7"] and meta_messages(report.errors) == []
    assert meta_messages(report.warnings) == [
        "meta modern 7d: No archetype tiles on the modern metagame page (the snapshot keeps the last 7d window read)"
    ]


def test_a_run_that_reads_no_window_in_any_format_fails(tmp_path):
    blocked = BlockedError("Blocked on https://www.mtggoldfish.com/metagame/modern/full")
    report = run(tmp_path, WindowBrowser({"30": [blocked, blocked]}), config())
    assert report.meta == [] and meta_messages(report.errors) == ["meta: no window read in any of 1 formats"]


def test_a_run_publishes_card_pages_for_what_the_decks_play(tmp_path):
    run(tmp_path, FixtureBrowser(), config())

    index = json.loads((tmp_path / "cards" / "index.json").read_text())
    assert index["cards"]["lightning-bolt"] == {"name": "Lightning Bolt", "formats": ["modern"], "oracle_id": None}
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


def test_events_without_decklists_are_skipped_and_remembered(tmp_path):
    browser = FixtureBrowser(event_pages=("66753",))
    page = browser.page

    def serve(path):
        if path == "/tournament/66742":
            return "<html><h2>Modern League 2026-09-21</h2><p>Date: 2026-09-21</p><p>No decklists yet</p></html>"
        return page(path)

    browser.page = serve
    report = run(tmp_path, browser, config(max_new_events=1, max_new_decks=0))
    assert not any("66742" in error for error in report.errors)
    assert "66742" in json.loads((tmp_path / "state" / "empty-event-ids.json").read_text())
    second = FixtureBrowser(event_pages=("66753",))
    run(tmp_path, second, config(max_new_events=1, max_new_decks=0))
    assert "/tournament/66742" not in second.requests


def refusing(browser, status=403):
    """Makes every deck download come back refused, as on 5 October 2026."""
    fetch_batch = browser.fetch_batch

    def refuse(paths):
        if paths and paths[0].startswith("/deck/download/"):
            return [Fetched(path, status, "<title>Just a moment...</title>", None, "challenge") for path in paths]
        return fetch_batch(paths)

    browser.fetch_batch = refuse


def test_deck_downloads_that_are_all_refused_are_a_warning_not_an_error(tmp_path):
    browser = FixtureBrowser()
    refusing(browser)

    report = run(tmp_path, browser, config())

    # The pages before the decks were published as usual; only the 66764 page fails, as in every run here.
    assert report.meta == ["modern_30d"] and report.events == ["66753"] and len(report.archetypes) == 2
    assert [error for error in report.errors if "deck" in error] == []
    assert report.decks_written == 0
    assert report.deck_block.startswith("HTTP 403, cf-mitigated=challenge")
    assert len(report.warnings) == 1 and report.warnings[0].startswith("Deck downloads blocked after 0 (HTTP 403")
    # Everything wanted waits for the next run: 44 decks, 10 of them within the format's allowance.
    assert report.decks_deferred == 44
    assert browser.deck_downloads == []
    assert not (tmp_path / "decks").exists()


def test_a_run_that_downloads_every_deck_has_no_warning_and_nothing_deferred(tmp_path):
    report = run(tmp_path, FixtureBrowser(), config(max_new_decks=1000))
    assert (report.warnings, report.deck_block, report.decks_deferred) == ([], None, 0)
    assert report.decks_written == 44


def test_decks_past_an_allowance_are_deferred(tmp_path):
    cfg = config(max_new_decks=8)
    cfg.deck_pacing.per_run = 6
    report = run(tmp_path, FixtureBrowser(), cfg)
    stored = len(list((tmp_path / "decks").glob("*.json")))
    assert report.decks_written == stored == 6
    # 44 are wanted, 8 are within the format's allowance and the run's allowance of 6 is the tighter.
    assert report.decks_deferred == 44 - 6


def test_a_deck_error_that_is_not_a_refusal_is_still_an_error(tmp_path):
    browser = FixtureBrowser()
    fetch_batch = browser.fetch_batch

    def fetch(paths):
        return [Fetched(a.path, 404, "Not found") if a.path.endswith("/7966110") else a for a in fetch_batch(paths)]

    browser.fetch_batch = fetch
    report = run(tmp_path, browser, config())
    assert "deck 7966110: HTTP 404 on /deck/download/7966110" in report.errors
    assert report.deck_block is None and report.warnings == []
    assert not (tmp_path / "decks" / "7966110.json").exists()


def day(date):
    return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def stored_event(event_id, name, date="2026-09-20", results=10):
    return EventSummary(event_id, name, day(date), results)


CUTOFF = day("2026-08-23")


def test_a_stored_fallback_name_is_selected_for_a_re_read():
    stored = {"1": stored_event("1", "Tournament 1"), "2": stored_event("2", "Modern League 2026-09-20")}

    chosen = _events_to_reread(stored, {}, set(), CUTOFF)

    assert chosen == [EventSummary("1", "", day("2026-09-20"))]


def test_a_listing_with_another_name_or_more_results_selects_the_event():
    stored = {
        "1": stored_event("1", "Modern Challenge 2026-09-20"),
        "2": stored_event("2", "Modern League 2026-09-19", results=10),
        "3": stored_event("3", "Modern League 2026-09-18", results=10),
        "4": stored_event("4", "Modern League 2026-09-17", results=10),
    }
    listed = {
        "1": EventSummary("1", "MTG SEA Championships Singapore Open", day("2026-09-20"), 40),
        "2": EventSummary("2", "Modern League 2026-09-19", day("2026-09-19"), 12),
        "3": EventSummary("3", "Modern League 2026-09-18", day("2026-09-18"), 10),
        "4": EventSummary("4", "Modern League 2026-09-17", day("2026-09-17"), 8),
    }

    chosen = _events_to_reread(stored, listed, set(), CUTOFF)

    assert chosen == [listed["1"], listed["2"]]


def test_a_listing_that_is_itself_the_fallback_name_is_not_passed_on():
    stored = {"1": stored_event("1", "Tournament 1")}
    listed = {"1": EventSummary("1", "Tournament 1", day("2026-09-20"), 10)}

    assert _events_to_reread(stored, listed, set(), CUTOFF) == [EventSummary("1", "", day("2026-09-20"))]


def test_events_outside_the_window_or_already_read_this_run_are_not_selected():
    stored = {"1": stored_event("1", "Tournament 1", "2026-08-01"), "2": stored_event("2", "Tournament 2")}

    assert _events_to_reread(stored, {}, {"2"}, CUTOFF) == []


def tamper_stored_event(root, event_id, **changes):
    path = root / "state" / "snapshots" / "modern.json"
    document = json.loads(path.read_text())
    next(e for e in document["events"] if e["event_id"] == event_id).update(changes)
    path.write_text(json.dumps(document))


def stored_event_name(root, event_id):
    return next(e["event_name"] for e in snapshot(root)["events"] if e["event_id"] == event_id)


class OlderFixtureBrowser(FixtureBrowser):
    """A tournaments list that no longer shows 66753, so only the reconcile can reach it."""

    def page(self, path):
        if path == "/tournaments/modern":
            return "<html></html>"
        return super().page(path)


def test_a_stored_fallback_name_is_read_again_and_replaced(tmp_path):
    run(tmp_path, FixtureBrowser(), config(max_new_decks=0))
    tamper_stored_event(tmp_path, "66753", event_name="Tournament 66753")

    second = OlderFixtureBrowser()
    run(tmp_path, second, config(max_new_decks=0, recheck_days=0))

    assert "/tournament/66753" in second.requests
    assert stored_event_name(tmp_path, "66753") == "Modern Challenge 32 2026-09-21"


def test_the_re_reads_of_a_run_are_capped(tmp_path):
    run(tmp_path, FixtureBrowser(), config(max_new_decks=0))
    tamper_stored_event(tmp_path, "66753", event_name="Tournament 66753")

    second = OlderFixtureBrowser()
    run(tmp_path, second, config(max_new_decks=0, max_reread_events=0, recheck_days=0))

    assert "/tournament/66753" not in second.requests
    assert stored_event_name(tmp_path, "66753") == "Tournament 66753"


def test_a_page_without_a_name_does_not_overwrite_the_stored_name(tmp_path):
    run(tmp_path, FixtureBrowser(), config(max_new_decks=0))
    tamper_stored_event(tmp_path, "66753", event_name="Real Name")

    class Nameless(FixtureBrowser):
        def page(self, path):
            html = super().page(path)
            if path == "/tournaments/modern":
                return html.replace("Modern Challenge 32 2026-09-21", "Tournament 66753")
            if path == "/tournament/66753":
                return html.replace("<h2>Modern Challenge 32 2026-09-21</h2>", "")
            return html

    run(tmp_path, Nameless(), config(max_new_decks=0))

    event = next(e for e in snapshot(tmp_path)["events"] if e["event_id"] == "66753")
    assert (event["event_name"], event["kind"]) == ("Real Name", "other")


class ListingBrowser:
    def __init__(self, listing=""):
        self.listing = listing
        self.requests = []

    def page(self, path):
        self.requests.append(path)
        if path == "/tournaments/modern":
            return self.listing
        if path.startswith("/tournament_searches/create?"):
            return "<table><tr><th>Date</th><th>Name</th><th>Format</th><th>Decklists</th></tr></table>"
        return (
            "<h2>Modern League 2026-09-16</h2><p>Date: 2026-09-16</p>"
            '<table class="table-tournament"><tr><td>5 - 0</td><td><a href="/deck/1">UR</a></td>'
            '<td><a href="/player/x">P</a></td></tr></table>'
        )

    def fetch_pages(self, paths):
        return {path: self.page(path) for path in paths}


def read_events_with(store, browser, **overrides):
    values = dict(formats=("modern",), max_new_events=0, recheck_days=7)
    values.update(overrides)
    return _read_events(browser, store, "modern", [], ScrapeConfig(**values), RunReport(), NOW - timedelta(days=30), NOW)


def store_with(tmp_path, *events):
    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    for event_id, name, date in events:
        store.save_event(Event(event_id, name, "modern", day(date), [EventResult("p", "Eldrazi", "5-0", "1")], "url"))
    return store


def test_a_stored_event_six_days_old_is_read_again_and_one_eight_days_old_is_not(tmp_path):
    store = store_with(tmp_path, ("1", "Modern League 2026-09-16", "2026-09-16"), ("2", "Modern League 2026-09-14", "2026-09-14"))
    browser = ListingBrowser()

    events = read_events_with(store, browser)

    assert [event.event_id for event in events] == ["1"]
    assert "/tournament/1" in browser.requests and "/tournament/2" not in browser.requests


def test_an_event_eight_days_old_is_read_when_the_reconcile_rule_picks_it(tmp_path):
    store = store_with(tmp_path, ("1", "Modern League 2026-09-16", "2026-09-16"), ("2", "Tournament 2", "2026-09-14"))
    browser = ListingBrowser()

    events = read_events_with(store, browser)

    assert sorted(event.event_id for event in events) == ["1", "2"]
    assert browser.requests.count("/tournament/1") == 1 and browser.requests.count("/tournament/2") == 1


def test_every_event_of_the_last_days_is_read_however_many_there_are(tmp_path):
    store = store_with(tmp_path, *[(str(n), f"Modern League 2026-09-{16 + n % 6}", f"2026-09-{16 + n % 6}") for n in range(1, 31)])
    browser = ListingBrowser()

    events = read_events_with(store, browser, max_reread_events=0)

    assert len(events) == 30


def test_a_listed_event_not_yet_stored_is_read_within_the_last_days(tmp_path):
    store = store_with(tmp_path)
    listing = '<h4><a href="/tournament/5">Modern League 2026-09-20</a> 2026-09-20</h4>'
    browser = ListingBrowser(listing)

    events = read_events_with(store, browser)

    assert [event.event_id for event in events] == ["5"]
