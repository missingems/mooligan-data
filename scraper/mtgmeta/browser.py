"""SeleniumBase UC-mode browser that gets past MTGGoldfish's Cloudflare check."""
from __future__ import annotations

import json
import logging
import math
import random
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from seleniumbase import SB

from .parsing import BASE_URL, selected_period

log = logging.getLogger(__name__)

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied")


def _is_challenge(body: str) -> bool:
    head = body[:3000].lower()
    return "<title>just a moment" in head or "challenges.cloudflare.com" in head or "cf-chl" in head


# Statuses that mean "not now" rather than "not there": 0 is a request that never got an answer.
_REFUSED_STATUSES = (0, 403, 429, 503)


def _retry_after(value: object) -> Optional[float]:
    """A Retry-After header as seconds. An HTTP-date or anything else that is not a number gives None."""
    try:
        seconds = float(str(value).strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


class BlockedError(RuntimeError):
    """Cloudflare kept serving its challenge instead of the page."""


@dataclass
class Fetched:
    """One answer to a fetch() made from inside the open page."""

    path: str
    status: int
    body: str
    retry_after: Optional[float] = None
    # The cf-mitigated header ("challenge" when Cloudflare answered with its check), if any.
    mitigated: str = ""
    # The URL the answer came from, which differs from the request after a redirect.
    final_url: str = ""

    @property
    def refused(self) -> bool:
        """Whether the site said "not now": a refusing status or a challenge page, whatever the status."""
        return self.status in _REFUSED_STATUSES or _is_challenge(self.body)

    def describe(self) -> str:
        """A one-line diagnostic of the answer, for the log."""
        match = re.search(r"<title[^>]*>(.*?)</title>", self.body[:3000], re.I | re.S)
        title = match.group(1).strip() if match else self.body[:80].strip()
        retry = "none" if self.retry_after is None else f"{self.retry_after:g}s"
        parts = [f"HTTP {self.status}", f"cf-mitigated={self.mitigated or 'none'}", f"retry-after={retry}", f"title {title!r}"]
        final = self.final_url[len(BASE_URL) :] if self.final_url.startswith(BASE_URL) else self.final_url
        if final and final != self.path:
            parts.append(f"redirected to {final}")
        return ", ".join(parts)


class GoldfishBrowser:
    def __init__(self, sb, delay: float, concurrency: int) -> None:
        self._sb = sb
        self._delay = delay
        self._concurrency = max(1, concurrency)

    def _pause(self) -> None:
        time.sleep(self._delay + random.uniform(0, self._delay / 2))

    def page(self, path: str, attempts: int = 3) -> str:
        url = f"{BASE_URL}{path}"
        for attempt in range(1, attempts + 1):
            self._pause()
            self._sb.uc_open_with_reconnect(url, 4)
            if self._cleared(wait=10):
                return self._sb.get_page_source()
            log.warning("Challenge page on %s (attempt %d/%d)", url, attempt, attempts)
            try:
                self._sb.uc_gui_click_captcha()
            except Exception:  # noqa: BLE001 - nothing to click in some challenge variants
                pass
            if self._cleared(wait=10):
                return self._sb.get_page_source()
        raise BlockedError(f"Blocked on {url}")

    def metagame(self, format: str, days: str) -> Tuple[str, bool]:
        """The metagame page with the `days` window selected, and whether the page has a selector.

        A format without one (Duel Commander) has a single, unwindowed page.
        """
        html = self._loaded_metagame(format)
        window = selected_period(html)
        if window is None:
            log.info("The %s metagame has no window selector; taking the page as it comes", format)
            return html, False
        if window == days:
            return html, True
        before = self._tile_statistics()
        # Changing the select submits a Turbo form that swaps only the tiles, so
        # the option's `selected` attribute in the HTML keeps saying 30 days.
        # The tiles on show are stamped first, since the swap can bring tiles that read exactly the same: in
        # the weeks after a Penny Dreadful season starts, every deck of the 30 days is also in the 14 and the 7.
        # Whether the swap replaces the tiles or morphs them, the new ones carry no stamp.
        stamped = self._sb.execute_script(
            "const tiles = document.querySelectorAll('.archetype-tile');"
            "tiles.forEach(tile => tile.setAttribute('data-mtgmeta-stale', ''));"
            "const select = document.querySelector('select#period');"
            "select.value = %s;"
            "select.dispatchEvent(new Event('change', {bubbles: true}));"
            "return tiles.length;" % json.dumps(days)
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.5)
            if (stamped and not self._stale_tiles()) or self._tile_statistics() != before:
                time.sleep(1)  # let the rest of the tiles land
                if not self._tile_statistics():
                    log.info("The %s metagame shows no archetypes for %s days", format, days)
                return self._sb.get_page_source(), True
        raise TimeoutError(f"The {format} metagame did not switch to {days} days")

    def fetch_pages(self, paths: Sequence[str], attempts: int = 4) -> Dict[str, Union[str, Exception]]:
        """Fetches `paths` with fetch() inside the open page, `concurrency` at a time.

        The requests reuse the page's Cloudflare clearance and skip rendering, so
        they take a fraction of a navigation. A 403 or challenge means the
        clearance isn't ready or has lapsed: the page is reloaded to renew it and
        those paths are retried. Each path maps to its body, or to the error it
        ended with.
        """
        results: Dict[str, Union[str, Exception]] = {}
        pending = list(dict.fromkeys(paths))
        for attempt in range(1, attempts + 1):
            blocked: List[str] = []
            for start in range(0, len(pending), self._concurrency):
                batch = pending[start : start + self._concurrency]
                self._pause()
                for fetched in self.fetch_batch(batch):
                    if fetched.status == 200 and not fetched.refused:
                        results[fetched.path] = fetched.body
                    elif fetched.refused:
                        blocked.append(fetched.path)
                    else:
                        results[fetched.path] = RuntimeError(f"HTTP {fetched.status} on {fetched.path}")
                if blocked and len(blocked) == len(batch):
                    # The whole batch was refused: stop spending requests and renew first.
                    blocked.extend(pending[start + self._concurrency :])
                    break
            if not blocked:
                break
            log.warning("%d requests refused (attempt %d/%d); renewing the clearance", len(blocked), attempt, attempts)
            pending = blocked
            time.sleep(5 * attempt)
            self.page("/")
        else:
            for path in pending:
                results[path] = BlockedError(f"Blocked on {path}")
        return results

    def fetch_batch(self, paths: Sequence[str]) -> List[Fetched]:
        """Fetches `paths` together with fetch() inside the open page: one attempt, no pause, no retry.

        A refusal is reported in the answer, not handled here, so the caller decides how long to wait.
        """
        paths = list(paths)
        return [
            Fetched(
                path,
                status=int(response.get("status", 0)),
                body=str(response.get("body", "")),
                retry_after=_retry_after(response.get("retryAfter")),
                mitigated=response.get("mitigated") or "",
                final_url=response.get("url") or "",
            )
            for path, response in zip(paths, self._fetch_batch(paths))
        ]

    def _fetch_batch(self, paths: List[str]) -> List[dict]:
        # BaseCase.execute_async_script takes no script arguments, so embed the paths.
        script = """
            const done = arguments[arguments.length - 1];
            Promise.all(%s.map(path => fetch(path, {credentials: 'include'})
              .then(r => r.text().then(body => ({
                status: r.status,
                body,
                retryAfter: r.headers.get('retry-after'),
                mitigated: r.headers.get('cf-mitigated'),
                url: r.url,
              })))
              .catch(error => ({status: 0, body: String(error)}))))
              .then(responses => done(JSON.stringify(responses)));
        """ % json.dumps(paths)
        try:
            return json.loads(self._sb.execute_async_script(script, timeout=90))
        except Exception as error:  # noqa: BLE001 - a hung request times out the whole script
            return [{"status": 0, "body": str(error)} for _ in paths]

    def _loaded_metagame(self, format: str, attempts: int = 2) -> str:
        """The metagame page once its archetype tiles are in, loaded again if they never come.

        The tiles can land after the page has cleared the challenge, and a page read before them parses
        as having none. Still without tiles after every attempt, the page is returned as it is.
        """
        path = f"/metagame/{format}/full"
        for attempt in range(1, attempts + 1):
            self.page(path)
            if self._tiles_landed(wait=15):
                return self._sb.get_page_source()
            log.warning("No archetype tiles on the %s metagame page yet (attempt %d/%d)", format, attempt, attempts)
        return self._sb.get_page_source()

    def _tiles_landed(self, wait: float) -> bool:
        """Whether the metagame page shows its archetype tiles, giving them `wait` seconds to arrive."""
        for _ in range(int(wait / 0.5) + 1):
            if self._tile_statistics():
                return True
            time.sleep(0.5)
        return False

    def _cleared(self, wait: float) -> bool:
        """Whether the real page is showing, giving an automatic challenge `wait` seconds to pass."""
        deadline = time.time() + wait
        while True:
            title = (self._sb.get_title() or "").lower()
            if not any(marker in title for marker in _CHALLENGE_TITLES):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(1)

    def _tile_statistics(self) -> str:
        return self._sb.execute_script(
            "return [...document.querySelectorAll('.metagame-percentage .archetype-tile-statistic-value')]"
            ".map(e => e.textContent.trim()).join('|')"
        )

    def _stale_tiles(self) -> int:
        """How many of the tiles stamped before a window switch are still on the page."""
        return self._sb.execute_script("return document.querySelectorAll('.archetype-tile[data-mtgmeta-stale]').length")


@contextmanager
def open_browser(headless: bool, delay: float, concurrency: int) -> Iterator[GoldfishBrowser]:
    # On Linux (the Cloud Run container) UC mode runs headed inside Xvfb, which
    # Cloudflare challenges far less often than headless Chrome.
    use_xvfb = sys.platform.startswith("linux") and not headless
    with SB(uc=True, headless=headless, xvfb=use_xvfb, locale="en") as sb:
        yield GoldfishBrowser(sb, delay, concurrency)
