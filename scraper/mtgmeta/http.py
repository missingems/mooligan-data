"""Fetches pages one at a time, slowly, and stops asking a site that refuses.

Everything here is pure apart from the default opener: the opener, the sleeping, the clock and the random
numbers are passed in, so the tests run instantly without a network.
"""
from __future__ import annotations

import gzip
import json
import logging
import random
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

USER_AGENT = "MooliganData/1.0 (+https://github.com/missingems/mooligan-data)"
TIMEOUT = 30.0
# MTGTop8's robots.txt Crawl-delay: no setting goes faster.
MIN_DELAY = 5.0
# The extra wait on top of the delay, as a share of it, chosen at random each time.
JITTER = 0.5
# A site that refused one format's job is left alone by the jobs after it, for this long.
REFUSAL_HOURS = 12

Opener = Callable[[str, Dict[str, str], float], Tuple[int, Mapping[str, str], bytes]]


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    def header(self, name: str) -> Optional[str]:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")


def urllib_opener(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, Mapping[str, str], bytes]:
    """Asks for `url` with urllib and returns the status, headers and body; an error status is an answer, not an exception."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        try:
            body = error.read()
        except (OSError, HTTPException):
            body = b""
        return error.code, dict(error.headers.items()) if error.headers else {}, body


def is_refusal(status: int) -> bool:
    return status in (403, 429) or status >= 500


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class PoliteClient:
    """One request at a time, at least `delay` seconds apart (plus up to half as much again, at random),
    within `budget_minutes` of wall-clock time. A refusal or a network error stops that host for the run."""

    def __init__(
        self,
        delay: float = 10.0,
        budget_minutes: float = 90.0,
        user_agent: str = USER_AGENT,
        opener: Opener = urllib_opener,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.delay = delay
        self.budget_minutes = budget_minutes
        self.user_agent = user_agent
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.started = clock()
        self.requests = 0
        self.refusals: Dict[str, str] = {}
        self._last: Optional[float] = None

    def elapsed(self) -> float:
        """Minutes since the client was made."""
        return (self._clock() - self.started) / 60

    def budget_left(self) -> bool:
        return self.elapsed() < self.budget_minutes

    def stopped(self, host: str) -> bool:
        return host.lower() in self.refusals

    def _wait(self) -> None:
        if self._last is None:
            return
        wanted = self.delay + self.rng.uniform(0, JITTER * self.delay)
        seconds = wanted - (self._clock() - self._last)
        if seconds > 0:
            self._sleep(seconds)

    def stop(self, host: str, detail: str) -> None:
        if host not in self.refusals:
            self.refusals[host] = detail
            log.warning("%s stopped for this run: %s", host, detail)

    def get(self, url: str) -> Optional[Fetched]:
        """The answer for `url`, or None when the budget is spent, the host is stopped, or the network failed."""
        host = _host(url)
        if not self.budget_left() or self.stopped(host):
            return None
        self._wait()
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        self.requests += 1
        try:
            status, received, body = self._opener(url, headers, TIMEOUT)
            fetched = Fetched(url, status, body, dict(received))
            if (fetched.header("Content-Encoding") or "").lower() == "gzip":
                fetched.body = gzip.decompress(body)
        except (OSError, HTTPException, EOFError, zlib.error) as error:
            self._last = self._clock()
            self.stop(host, f"network error: {error}")
            return None
        self._last = self._clock()
        if is_refusal(fetched.status):
            detail = f"HTTP {fetched.status}"
            retry_after = fetched.header("Retry-After")
            if retry_after:
                detail += f", Retry-After {retry_after}"
            self.stop(host, detail)
        return fetched


def recent_refusals(path: Path, now: datetime) -> Dict[str, str]:
    """The hosts that refused a run in the last REFUSAL_HOURS, by the file note_deck_block writes."""
    try:
        hosts = json.loads(path.read_text()).get("hosts") or {}
        return {
            host: entry["detail"]
            for host, entry in hosts.items()
            if now - datetime.fromisoformat(entry["at"]) < timedelta(hours=REFUSAL_HOURS)
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def note_deck_block(path: Path, refusals: Mapping[str, str], now: datetime) -> int:
    """Counts the days in a row whose requests were refused, in the JSON file at `path`, and returns the count.

    Every format job of a day writes it, so a refusal within REFUSAL_HOURS of the last one keeps the count, and the
    hosts that refused stay recorded, from their first refusal, for the jobs after (see recent_refusals).
    """
    known = recent_refusals(path, now)
    try:
        previous = json.loads(path.read_text())
        count = int(previous["blocked_runs"])
        last = previous.get("last_blocked")
        same_day = bool(last) and now - datetime.fromisoformat(last) < timedelta(hours=REFUSAL_HOURS)
        stored = previous.get("hosts") or {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        count, last, same_day, stored = 0, None, False, {}
    hosts: Dict[str, dict] = {}
    if refusals:
        count = max(count, 1) if same_day else count + 1
        last = now.isoformat()
        hosts = {host: stored[host] if host in known else {"at": last, "detail": detail} for host, detail in refusals.items()}
    else:
        count = 0
    detail = "; ".join(f"{host}: {entry['detail']}" for host, entry in hosts.items()) or None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"blocked_runs": count, "last_blocked": last, "detail": detail, "hosts": hosts}))
    return count
