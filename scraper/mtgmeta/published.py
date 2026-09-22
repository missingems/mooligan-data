"""Reads decklists the pipeline published earlier, to fill in what a run doesn't download.

Card pages are counted from every deck in the window, but decks are downloaded
from MTGGoldfish once and never again. Their contents come back from our own
bucket instead, which is free, fast and needs no browser.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List

log = logging.getLogger(__name__)


def fetch_published_decks(base_url: str, deck_ids: Iterable[str], workers: int = 16) -> Dict[str, dict]:
    """Downloads `decks/<id>.json` for each id, returning the ones that came back."""
    ids: List[str] = list(deck_ids)
    if not ids:
        return {}
    found: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for deck_id, deck in zip(ids, pool.map(lambda deck_id: _fetch(base_url, deck_id), ids)):
            if deck is not None:
                found[deck_id] = deck
    log.info("Read %d of %d published decklists for the card pages", len(found), len(ids))
    return found


def _fetch(base_url: str, deck_id: str):
    request = urllib.request.Request(
        f"{base_url}/decks/{deck_id}.json", headers={"User-Agent": "mtg-meta-pipeline/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as error:
        log.warning("Could not read published deck %s: %s", deck_id, error)
        return None
