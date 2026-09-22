"""SeleniumBase UC-mode browser that gets past MTGGoldfish's Cloudflare check."""
from __future__ import annotations

import json
import logging
import random
import sys
import time
from contextlib import contextmanager
from typing import Iterator

from seleniumbase import SB

from .parsing import BASE_URL, selected_period

log = logging.getLogger(__name__)

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied")


class BlockedError(RuntimeError):
    """Cloudflare kept serving its challenge instead of the page."""


class GoldfishBrowser:
    def __init__(self, sb, delay: float) -> None:
        self._sb = sb
        self._delay = delay

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

    def metagame(self, format: str, days: str) -> str:
        """The full metagame page with the `days` window selected."""
        html = self.page(f"/metagame/{format}/full")
        if selected_period(html) == days:
            return html
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
                return self._sb.get_page_source()
        raise TimeoutError(f"The {format} metagame did not switch to {days} days")

    def deck_text(self, deck_id: str, attempts: int = 3) -> str:
        """Downloads a plain-text decklist with fetch() inside the page, reusing its Cloudflare clearance."""
        for attempt in range(1, attempts + 1):
            self._pause()
            try:
                # BaseCase.execute_async_script takes no script arguments, so embed the path.
                raw = self._sb.execute_async_script(
                    """
                    const done = arguments[arguments.length - 1];
                    fetch(%s, {credentials: 'include'})
                      .then(r => r.text().then(body => done(JSON.stringify({status: r.status, type: r.headers.get('content-type') || '', body}))))
                      .catch(error => done(JSON.stringify({status: 0, type: '', body: String(error)})));
                    """
                    % json.dumps(f"/deck/download/{deck_id}"),
                    timeout=30,
                )
                response = json.loads(raw)
            except Exception as error:  # noqa: BLE001 - a hung request times out the script
                response = {"status": 0, "type": "", "body": str(error)}
            if response["status"] == 200 and response["type"].startswith("text/plain"):
                return response["body"]
            log.warning("Deck %s download got %s %s (attempt %d/%d)", deck_id, response["status"], response["type"], attempt, attempts)
            # A challenge page means the clearance expired; reload a page to renew it.
            self.page(f"/deck/{deck_id}")
        raise BlockedError(f"Could not download deck {deck_id}")

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
def open_browser(headless: bool, delay: float) -> Iterator[GoldfishBrowser]:
    # On Linux (the Cloud Run container) UC mode runs headed inside Xvfb, which
    # Cloudflare challenges far less often than headless Chrome.
    use_xvfb = sys.platform.startswith("linux") and not headless
    with SB(uc=True, headless=headless, xvfb=use_xvfb, locale="en") as sb:
        yield GoldfishBrowser(sb, delay)
