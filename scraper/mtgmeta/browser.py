"""SeleniumBase UC-mode browser that gets past MTGGoldfish's Cloudflare check."""
from __future__ import annotations

import json
import logging
import random
import sys
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Sequence, Tuple, Union

from seleniumbase import SB

from .parsing import BASE_URL, selected_period

log = logging.getLogger(__name__)

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied")


def _is_challenge(body: str) -> bool:
    head = body[:3000].lower()
    return "<title>just a moment" in head or "challenges.cloudflare.com" in head or "cf-chl" in head


class BlockedError(RuntimeError):
    """Cloudflare kept serving its challenge instead of the page."""


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
        html = self.page(f"/metagame/{format}/full")
        window = selected_period(html)
        if window is None:
            log.info("The %s metagame has no window selector; taking the page as it comes", format)
            return html, False
        if window == days:
            return html, True
        before = self._tile_statistics()
        # Changing the select submits a Turbo form that swaps only the tiles, so
        # the option's `selected` attribute in the HTML keeps saying 30 days.
        self._sb.execute_script(
            "const select = document.querySelector('select#period');"
            "select.value = %s;"
            "select.dispatchEvent(new Event('change', {bubbles: true}));" % json.dumps(days)
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.5)
            if self._tile_statistics() != before:
                time.sleep(1)  # let the rest of the tiles land
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
                for path, response in zip(batch, self._fetch_batch(batch)):
                    status, body = response["status"], response["body"]
                    if status == 200 and not _is_challenge(body):
                        results[path] = body
                    elif status in (0, 403, 429, 503) or _is_challenge(body):
                        blocked.append(path)
                    else:
                        results[path] = RuntimeError(f"HTTP {status} on {path}")
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

    def _fetch_batch(self, paths: List[str]) -> List[dict]:
        # BaseCase.execute_async_script takes no script arguments, so embed the paths.
        script = """
            const done = arguments[arguments.length - 1];
            Promise.all(%s.map(path => fetch(path, {credentials: 'include'})
              .then(r => r.text().then(body => ({status: r.status, body})))
              .catch(error => ({status: 0, body: String(error)}))))
              .then(responses => done(JSON.stringify(responses)));
        """ % json.dumps(paths)
        try:
            return json.loads(self._sb.execute_async_script(script, timeout=90))
        except Exception as error:  # noqa: BLE001 - a hung request times out the whole script
            return [{"status": 0, "body": str(error)} for _ in paths]

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


@contextmanager
def open_browser(headless: bool, delay: float, concurrency: int) -> Iterator[GoldfishBrowser]:
    # On Linux (the Cloud Run container) UC mode runs headed inside Xvfb, which
    # Cloudflare challenges far less often than headless Chrome.
    use_xvfb = sys.platform.startswith("linux") and not headless
    with SB(uc=True, headless=headless, xvfb=use_xvfb, locale="en") as sb:
        yield GoldfishBrowser(sb, delay, concurrency)
