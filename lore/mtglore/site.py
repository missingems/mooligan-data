"""Reads every Magic Story article and story profile from magic.wizards.com into data/stories and data/profiles.

The pages are server-rendered, so plain requests do: no browser. The sitemap lists most articles; the
paged listing at /en/news/magic-story fills in any the sitemap leaves out. A page already saved is skipped
unless `refresh` is set, so a run picks up only what is new.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List

from .parse import SITE, kind_of, listing_total, listing_urls, parse_page, sitemap_urls, slug_of

log = logging.getLogger(__name__)

USER_AGENT = "mooligan-lore/1.0 (+https://data.mooligan.com)"


class Site:
    def __init__(self, delay: float = 1.0, user_agent: str = USER_AGENT) -> None:
        self._delay = delay
        self._user_agent = user_agent
        self._last = 0.0

    def get(self, url: str, attempts: int = 4) -> str:
        for attempt in range(1, attempts + 1):
            wait = self._last + self._delay - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            request = urllib.request.Request(url, headers={"User-Agent": self._user_agent, "Accept": "text/html,application/xml"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == attempts:
                    raise
            log.warning("Retrying %s (attempt %d/%d)", url, attempt, attempts)
            time.sleep(5 * attempt)
        raise AssertionError("unreachable")

    def discover(self, max_listing_pages: int = 200) -> List[str]:
        """Every story and profile page: the sitemap's, then whatever the listing adds."""
        urls = sitemap_urls(self.get(f"{SITE}/en/sitemap.xml"))
        seen = set(urls)
        total = None
        listed = 0
        for page in range(1, max_listing_pages + 1):
            html = self.get(f"{SITE}/en/news/magic-story?page={page}")
            total = total or listing_total(html)
            found = listing_urls(html)
            if not found:
                break
            listed += len(found)
            new = [url for url in found if url not in seen]
            urls.extend(new)
            seen.update(new)
            if total and listed >= total:
                break
        stories = sum(1 for url in urls if kind_of(url) == "story")
        log.info("Found %d articles (the listing says %s) and %d profiles", stories, total, len(urls) - stories)
        return [url for url in urls if kind_of(url)]


def _path(directory: Path, url: str) -> Path:
    folder = "profiles" if kind_of(url) == "profile" else "stories"
    return directory / folder / f"{slug_of(url)}.json"


def scrape(site: Site, directory: Path, urls: Iterable[str], refresh: bool = False) -> dict:
    """Saves each page as JSON, and returns how many were saved, skipped and failed."""
    report = {"saved": 0, "skipped": 0, "failed": []}
    for url in urls:
        path = _path(directory, url)
        if path.exists() and not refresh:
            report["skipped"] += 1
            continue
        try:
            page = parse_page(site.get(url), url)
        except Exception as error:  # noqa: BLE001 - one page must not stop the rest
            log.warning("Could not read %s: %s", url, error)
            report["failed"].append(f"{url}: {error}")
            continue
        if not page["paragraphs"]:
            report["failed"].append(f"{url}: no text")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n")
        report["saved"] += 1
        if report["saved"] % 25 == 0:
            log.info("Saved %d pages", report["saved"])
    return report
