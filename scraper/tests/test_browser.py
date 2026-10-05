import json
import re

from mtgmeta import browser as browser_module
from mtgmeta.browser import BlockedError, Fetched, GoldfishBrowser


class FakeSession:
    """Stands in for SeleniumBase: answers each fetch batch from a script of statuses."""

    def __init__(self, statuses):
        self.statuses = list(statuses)  # one list of statuses per batch
        self.batches = []
        self.reloads = 0

    def execute_async_script(self, script, timeout=None):
        paths = json.loads(re.search(r"Promise\.all\((\[.*?\])\.map", script, re.S).group(1))
        self.batches.append(paths)
        statuses = self.statuses.pop(0) if self.statuses else [200] * len(paths)
        return json.dumps([
            {"status": status, "body": {200: f"<html>{path}</html>", 403: "<title>Just a moment...</title>"}.get(status, "Not found")}
            for path, status in zip(paths, statuses)
        ])

    def uc_open_with_reconnect(self, url, seconds):
        self.reloads += 1

    def get_title(self):
        return "MTGGoldfish"

    def get_page_source(self):
        return "<html></html>"


def make(statuses, concurrency=3, monkeypatch=None):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = FakeSession(statuses)
    return GoldfishBrowser(session, delay=0, concurrency=concurrency), session


def test_pages_are_fetched_in_batches(monkeypatch):
    browser, session = make([], monkeypatch=monkeypatch)
    results = browser.fetch_pages([f"/p{i}" for i in range(7)])
    assert [len(batch) for batch in session.batches] == [3, 3, 1]
    assert results["/p6"] == "<html>/p6</html>" and session.reloads == 0


def test_refused_requests_are_retried_after_renewing_the_clearance(monkeypatch):
    # The first batch is refused outright, as right after the first page load.
    browser, session = make([[403, 403, 403]], monkeypatch=monkeypatch)
    results = browser.fetch_pages([f"/p{i}" for i in range(5)])
    assert session.reloads == 1
    assert all(results[f"/p{i}"] == f"<html>/p{i}</html>" for i in range(5))
    # After the refusal it stopped and renewed rather than sending the second batch.
    assert session.batches[1] == ["/p0", "/p1", "/p2"]


def test_a_real_error_is_not_retried(monkeypatch):
    browser, session = make([[200, 404]], concurrency=2, monkeypatch=monkeypatch)
    results = browser.fetch_pages(["/a", "/b"])
    assert results["/a"] == "<html>/a</html>"
    assert "404" in str(results["/b"]) and session.reloads == 0


def test_paths_still_refused_after_every_attempt_fail(monkeypatch):
    browser, session = make([[403]] * 10, concurrency=1, monkeypatch=monkeypatch)
    results = browser.fetch_pages(["/a"], attempts=2)
    assert isinstance(results["/a"], BlockedError) and session.reloads == 2


class HeaderSession(FakeSession):
    """Answers a batch with the headers the real script reads, or with none."""

    def __init__(self, responses):
        super().__init__([])
        self.responses = responses

    def execute_async_script(self, script, timeout=None):
        super().execute_async_script(script, timeout)
        return json.dumps(self.responses)


def test_fetch_batch_reads_the_status_and_the_headers(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = HeaderSession([
        {"status": 403, "body": "<title>Just a moment...</title>", "retryAfter": "120", "mitigated": "challenge",
         "url": "https://www.mtggoldfish.com/deck/download/1"},
        {"status": 200, "body": "4 Bolt", "retryAfter": None, "mitigated": None, "url": "https://www.mtggoldfish.com/deck/download/2"},
        {"status": 429, "body": "slow down", "retryAfter": "Wed, 21 Oct 2026 07:28:00 GMT"},
    ])
    first, second, third = GoldfishBrowser(session, delay=0, concurrency=3).fetch_batch(
        ["/deck/download/1", "/deck/download/2", "/deck/download/3"]
    )
    assert (first.status, first.retry_after, first.mitigated, first.refused) == (403, 120.0, "challenge", True)
    assert (second.status, second.retry_after, second.mitigated, second.refused) == (200, None, "", False)
    # An HTTP-date is not a number of seconds.
    assert (third.status, third.retry_after, third.refused) == (429, None, True)


def test_fetch_batch_is_one_attempt_with_no_pause_or_renewal(monkeypatch):
    slept = []
    monkeypatch.setattr(browser_module.time, "sleep", slept.append)
    session = FakeSession([[403, 403]])
    results = GoldfishBrowser(session, delay=5, concurrency=2).fetch_batch(["/a", "/b"])
    assert [r.refused for r in results] == [True, True]
    assert session.batches == [["/a", "/b"]] and session.reloads == 0 and slept == []


def test_a_challenge_page_is_refused_whatever_its_status():
    assert Fetched("/a", 200, "<html><title>Just a moment...</title></html>").refused
    assert Fetched("/a", 0, "TimeoutError").refused
    assert not Fetched("/a", 404, "Not found").refused and not Fetched("/a", 200, "4 Bolt").refused


def test_describe_is_one_line_with_the_status_and_headers():
    fetched = Fetched("/deck/download/1", 403, "<html><head><title>Just a moment...</title></head></html>", None, "challenge")
    assert fetched.describe() == "HTTP 403, cf-mitigated=challenge, retry-after=none, title 'Just a moment...'"
    assert Fetched("/a", 429, "slow down", 30.0).describe() == "HTTP 429, cf-mitigated=none, retry-after=30s, title 'slow down'"


def test_describe_names_the_page_a_redirect_ended_on():
    url = "https://www.mtggoldfish.com/metagame/modern"
    assert Fetched("/deck/download/1", 200, "x", final_url=url).describe().endswith("redirected to /metagame/modern")
    same = Fetched("/deck/download/1", 200, "x", final_url="https://www.mtggoldfish.com/deck/download/1")
    assert "redirected" not in same.describe()


class MetagameSession(FakeSession):
    """A metagame page, optionally without the window selector some formats lack."""

    def __init__(self, has_selector, tiles_from_load=1):
        super().__init__([])
        self.scripts = []
        self.tiles_from_load = tiles_from_load  # the load whose tiles land; None for a page that never shows any
        self.html = (
            '<select id="period"><option selected value="30">30 Days</option></select>' if has_selector else "<p>no selector</p>"
        )

    def get_page_source(self):
        return self.html

    def execute_script(self, script):
        if "archetype-tile-statistic-value" in script and "dispatchEvent" not in script:
            # Reading the tiles' statistics, as the page shows them after this many loads.
            landed = self.tiles_from_load is not None and self.reloads >= self.tiles_from_load
            return "12.3%|4.5%" if landed else ""
        self.scripts.append(script)
        return ""


def test_a_metagame_without_a_window_selector_is_taken_as_it_comes(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=False)
    html, windowed = GoldfishBrowser(session, delay=0, concurrency=3).metagame("duel_commander", "7")
    assert (html, windowed) == (session.html, False) and session.scripts == []


def test_the_selected_window_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=True)
    html, windowed = GoldfishBrowser(session, delay=0, concurrency=3).metagame("modern", "30")
    assert (html, windowed) == (session.html, True) and session.scripts == []


def test_a_metagame_page_waits_for_its_tiles_without_loading_again(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=True)
    GoldfishBrowser(session, delay=0, concurrency=3).metagame("legacy", "30")
    assert session.reloads == 1


def test_a_metagame_page_without_tiles_is_loaded_again(monkeypatch):
    # Legacy's 30 day window on 2 October 2026: the page cleared the challenge before its tiles landed.
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=True, tiles_from_load=2)
    html, windowed = GoldfishBrowser(session, delay=0, concurrency=3).metagame("legacy", "30")
    assert session.reloads == 2 and (html, windowed) == (session.html, True)


def test_a_metagame_page_that_never_shows_tiles_is_returned_after_two_loads(monkeypatch):
    # Parsing it then reports the missing tiles, as before.
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=True, tiles_from_load=None)
    html, _ = GoldfishBrowser(session, delay=0, concurrency=3).metagame("legacy", "30")
    assert session.reloads == 2 and html == session.html
