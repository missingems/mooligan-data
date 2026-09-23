"""Every card Magic has, from Scryfall's bulk data, as a slug to name and oracle id.

Two jobs: it gives each card page the `oracle_id` an app joins on, and it is
the list of cards the Commander refresh works through, so a card no tournament
deck plays still gets a page.
"""
from __future__ import annotations

import gzip
import json
import logging
import urllib.request
from typing import Dict, Optional

from .cards import slug

log = logging.getLogger(__name__)

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/oracle-cards"
# Scryfall asks every client for a descriptive User-Agent and an Accept header.
HEADERS = {"User-Agent": "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)", "Accept": "application/json"}

# Layouts that are not real cards to look up: tokens, art cards, emblems.
SKIPPED_LAYOUTS = {"token", "double_faced_token", "art_series", "emblem", "vanguard", "scheme", "planar"}


def card_catalog(url: Optional[str] = None) -> Dict[str, dict]:
    """Maps a card's slug to its name and oracle id, streaming the file a line at a time."""
    download = url or _bulk_download_uri()
    catalog: Dict[str, dict] = {}
    request = urllib.request.Request(download, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        stream = gzip.GzipFile(fileobj=response) if download.endswith(".gz") else response
        for line in stream:
            line = line.strip()
            if not line:
                continue
            card = json.loads(line)
            if card.get("layout") in SKIPPED_LAYOUTS or not card.get("name"):
                continue
            oracle_id = card.get("oracle_id") or (card.get("card_faces") or [{}])[0].get("oracle_id")
            # Decklists name a double-faced card by its front face, which is how the slug reads.
            key = slug(card["name"].split("//")[0])
            if key:
                catalog.setdefault(key, {"name": card["name"], "oracle_id": oracle_id})
    log.info("Scryfall: %d cards in the catalog", len(catalog))
    return catalog


def _bulk_download_uri() -> str:
    request = urllib.request.Request(BULK_DATA_URL, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    uri = body.get("jsonl_download_uri") or body.get("download_uri")
    if not uri:
        raise RuntimeError("Scryfall bulk-data gave no download address")
    return uri
