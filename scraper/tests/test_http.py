import gzip
import random
import urllib.error
from datetime import datetime, timedelta, timezone

from mtgmeta.http import USER_AGENT, Fetched, PoliteClient, note_deck_block, recent_refusals

A = "https://www.mtgo.com/decklists/2026/11"
B = "https://www.mtgtop8.com/format?f=MO"


class Clock:
    """A clock that only moves when something sleeps or `advance` is called."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


class Opener:
    """Answers from a table of url to (status, headers, body) or an exception, and records the calls."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        answer = self.answers.get(url, (200, {}, b"ok"))
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_client(answers=None, seed=1, **values):
    clock = Clock()
    opener = Opener(answers)
    client = PoliteClient(opener=opener, sleep=clock.sleep, clock=clock, rng=random.Random(seed), **values)
    return client, opener, clock


def test_first_request_has_no_wait():
    client, opener, clock = make_client()
    fetched = client.get(A)
    assert fetched == Fetched(A, 200, b"ok", {})
    assert clock.slept == []
    assert client.requests == 1


def test_later_requests_wait_between_delay_and_one_and_a_half_times_it():
    client, opener, clock = make_client(delay=10.0)
    for _ in range(50):
        client.get(A)
    assert len(clock.slept) == 49
    assert all(10.0 <= seconds <= 15.0 for seconds in clock.slept)
    assert len(set(clock.slept)) > 1
    assert client.requests == 50


def test_spacing_is_measured_from_the_previous_request():
    client, opener, clock = make_client(delay=10.0)
    client.get(A)
    clock.advance(4.0)
    client.get(A)
    assert len(clock.slept) == 1
    assert 6.0 <= clock.slept[0] <= 11.0


def test_a_slow_caller_waits_nothing_more():
    client, opener, clock = make_client(delay=10.0)
    client.get(A)
    clock.advance(15.0)
    client.get(A)
    assert clock.slept == []


def test_the_gap_between_requests_is_never_below_the_delay():
    client, opener, clock = make_client(delay=10.0)
    times = []
    original = opener.__call__

    def stamped(url, headers, timeout):
        times.append(clock())
        return original(url, headers, timeout)

    client._opener = stamped
    for _ in range(30):
        client.get(A)
        clock.advance(2.0)
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    assert all(gap >= 10.0 for gap in gaps)


def test_a_429_stops_that_host_and_records_it_while_another_host_still_fetches():
    client, opener, clock = make_client({A: (429, {"Retry-After": "120"}, b"slow down")})
    fetched = client.get(A)
    assert fetched.status == 429
    assert client.stopped("www.mtgo.com")
    assert "429" in client.refusals["www.mtgo.com"]
    assert "120" in client.refusals["www.mtgo.com"]
    assert client.get(A) is None
    assert client.get(A + "/other") is None
    assert len(opener.calls) == 1
    assert client.get(B).status == 200
    assert not client.stopped("www.mtgtop8.com")
    assert len(opener.calls) == 2


def test_403_and_server_errors_stop_the_host():
    for status in (403, 500, 503):
        client, opener, clock = make_client({A: (status, {}, b"")})
        assert client.get(A).status == status
        assert client.stopped("www.mtgo.com")
        assert str(status) in client.refusals["www.mtgo.com"]
        assert client.get(A) is None


def test_retry_after_is_found_whatever_its_case():
    client, opener, clock = make_client({A: (429, {"retry-after": "30"}, b"")})
    client.get(A)
    assert "30" in client.refusals["www.mtgo.com"]


def test_a_404_is_returned_and_does_not_stop_the_host():
    client, opener, clock = make_client({A: (404, {}, b"missing")})
    fetched = client.get(A)
    assert fetched.status == 404
    assert not client.stopped("www.mtgo.com")
    assert client.refusals == {}
    assert client.get(A).status == 404
    assert len(opener.calls) == 2


def test_a_network_error_stops_the_host_and_returns_none():
    client, opener, clock = make_client({A: urllib.error.URLError("unreachable")})
    assert client.get(A) is None
    assert client.stopped("www.mtgo.com")
    assert "unreachable" in client.refusals["www.mtgo.com"]
    assert client.get(A) is None
    assert len(opener.calls) == 1
    assert client.get(B).status == 200


def test_a_timeout_stops_the_host():
    client, opener, clock = make_client({A: TimeoutError("timed out")})
    assert client.get(A) is None
    assert client.stopped("www.mtgo.com")


def test_a_spent_budget_returns_none_without_a_request():
    client, opener, clock = make_client(delay=10.0, budget_minutes=1.0)
    assert client.budget_left()
    assert client.get(A) is not None
    clock.advance(61.0)
    assert not client.budget_left()
    assert client.elapsed() >= 1.0
    assert client.get(B) is None
    assert len(opener.calls) == 1
    assert client.requests == 1


def test_elapsed_counts_minutes():
    client, opener, clock = make_client()
    clock.advance(150.0)
    assert client.elapsed() == 2.5


def test_the_user_agent_and_timeout_are_sent():
    client, opener, clock = make_client()
    client.get(A)
    url, headers, timeout = opener.calls[0]
    assert url == A
    assert headers["User-Agent"] == USER_AGENT
    assert USER_AGENT == "MooliganData/1.0 (+https://github.com/missingems/mooligan-data)"
    assert headers["Accept-Encoding"] == "gzip"
    assert timeout == 30.0


def test_a_custom_user_agent_is_sent():
    client, opener, clock = make_client(user_agent="Test/1")
    client.get(A)
    assert opener.calls[0][1]["User-Agent"] == "Test/1"


def test_a_gzip_body_is_decoded():
    body = gzip.compress("café deck".encode("utf-8"))
    client, opener, clock = make_client({A: (200, {"Content-Encoding": "gzip"}, body)})
    fetched = client.get(A)
    assert fetched.body == "café deck".encode("utf-8")
    assert fetched.text() == "café deck"


def test_text_replaces_bytes_it_cannot_decode():
    fetched = Fetched(A, 200, b"ok \xff", {})
    assert fetched.text() == "ok �"
    assert Fetched(A, 200, "café".encode("latin-1"), {}).text("latin-1") == "café"


def test_days_in_a_row_with_a_refusal_are_counted_and_the_site_is_kept_for_the_jobs_after(tmp_path):
    path = tmp_path / "state" / "deck-downloads.json"
    morning = datetime(2026, 11, 8, 6, tzinfo=timezone.utc)

    assert note_deck_block(path, {"www.mtgtop8.com": "HTTP 429"}, morning) == 1
    assert recent_refusals(path, morning + timedelta(hours=1)) == {"www.mtgtop8.com": "HTTP 429"}
    # The next format job, which never asked the site, keeps the count and the first refusal.
    assert note_deck_block(path, {"www.mtgtop8.com": "refused an earlier job (HTTP 429)"}, morning + timedelta(hours=1)) == 1
    assert recent_refusals(path, morning + timedelta(hours=2)) == {"www.mtgtop8.com": "HTTP 429"}
    assert recent_refusals(path, morning + timedelta(hours=13)) == {}
    assert note_deck_block(path, {"www.mtgtop8.com": "HTTP 429"}, morning + timedelta(days=1)) == 2
    assert note_deck_block(path, {}, morning + timedelta(days=2)) == 0
    assert recent_refusals(path, morning + timedelta(days=2)) == {}
