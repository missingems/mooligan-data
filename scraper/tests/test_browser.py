import json
import re

from mtgmeta import browser as browser_module
from mtgmeta.browser import BlockedError, GoldfishBrowser


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


class MetagameSession(FakeSession):
    """A metagame page, optionally without the window selector some formats lack."""

    def __init__(self, has_selector):
        super().__init__([])
        self.scripts = []
        self.html = (
            '<select id="period"><option selected value="30">30 Days</option></select>' if has_selector else "<p>no selector</p>"
        )

    def get_page_source(self):
        return self.html

    def execute_script(self, script):
        self.scripts.append(script)
        return ""


def test_a_metagame_without_a_window_selector_is_taken_as_it_comes(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=False)
    html = GoldfishBrowser(session, delay=0, concurrency=3).metagame("duel_commander", "7")
    assert html == session.html and session.scripts == []


def test_the_selected_window_is_returned_unchanged(monkeypatch):
    monkeypatch.setattr(browser_module.time, "sleep", lambda seconds: None)
    session = MetagameSession(has_selector=True)
    html = GoldfishBrowser(session, delay=0, concurrency=3).metagame("modern", "30")
    assert html == session.html and session.scripts == []
