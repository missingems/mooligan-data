"""Every card Magic has, from Scryfall's bulk data, as a slug to name and oracle id.

Two jobs: it gives each card page the `oracle_id` an app joins on, and it is
the list of cards the Commander refresh works through, so a card no tournament
deck plays still gets a page.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import urllib.request
from typing import Dict, Iterator, Optional

from .cards import slug
from .colors import COLORS

log = logging.getLogger(__name__)

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/oracle-cards"
# Every printing, for the price movers, which are priced per printing.
DEFAULT_CARDS_URL = "https://api.scryfall.com/bulk-data/default-cards"
# Every printing in every language, for the localized names and pictures Explore shows.
ALL_CARDS_URL = "https://api.scryfall.com/bulk-data/all-cards"
# Scryfall asks every client for a descriptive User-Agent and an Accept header.
HEADERS = {"User-Agent": "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)", "Accept": "application/json"}

# Layouts that are not real cards to look up: tokens, art cards, emblems.
SKIPPED_LAYOUTS = {"token", "double_faced_token", "art_series", "emblem", "vanguard", "scheme", "planar"}


def card_catalog(url: Optional[str] = None) -> Dict[str, dict]:
    """Maps a card's slug to its name and oracle id, streaming the file a line at a time.

    `"scryfall_id"` is the id of the printing the oracle-cards file picks for the card (the one `"price"` is
    of), kept when the card has an `id`. `"color_identity"` is the card's, as WUBRG letters in WUBRG order
    (`[]` for a colourless card), kept when the card has one.

    What a deck's preview needs to pick its cards is kept too: `"land": true` for a card whose front face is
    a land, `"price"` (Scryfall's USD, else its foil or etched price, when it has any), `"mana_value"`, and
    `"mana_cost"` (see `_mana_cost`) when the card has one. `"oracle_text"`, every face's rules text, is kept for the
    commander guides' card roles when the card has any. What the popular cards lists group by is always
    there: `"type_line"` of the front face, which is what a decklist plays ("" for a card with none), and the
    `"layout"`, which says whether "Fire // Ice" is a split card (both halves are its name) or a double-faced one.
    """
    catalog: Dict[str, dict] = {}
    for card in bulk_cards(url or _bulk_download_uri()):
        if card.get("layout") in SKIPPED_LAYOUTS or not card.get("name"):
            continue
        oracle_id = card.get("oracle_id") or (card.get("card_faces") or [{}])[0].get("oracle_id")
        # Decklists name a double-faced card by its front face, which is how the slug reads.
        key = slug(card["name"].split("//")[0])
        if key and key not in catalog:
            front_type = card.get("type_line") or (card.get("card_faces") or [{}])[0].get("type_line") or ""
            front_type = front_type.split("//")[0].strip()
            entry = {"name": card["name"], "oracle_id": oracle_id, "type_line": front_type, "layout": card.get("layout") or ""}
            if card.get("id"):
                entry["scryfall_id"] = card["id"]
            if "color_identity" in card:
                entry["color_identity"] = sorted(card["color_identity"], key=COLORS.index)
            # A double-faced spell with a land on the back ("Sorcery // Land") plays as a spell.
            if re.search(r"\bLand\b", front_type):
                entry["land"] = True
            price = _price(card.get("prices") or {})
            if price is not None:
                entry["price"] = price
            if card.get("cmc") is not None:
                entry["mana_value"] = card["cmc"]
            cost = _mana_cost(card)
            if cost:
                entry["mana_cost"] = cost
            text = _oracle_text(card)
            if text:
                entry["oracle_text"] = text
            catalog[key] = entry
    log.info("Scryfall: %d cards in the catalog", len(catalog))
    return catalog


def bulk_lines(download: str) -> Iterator[bytes]:
    """Each line of a Scryfall bulk file as raw bytes, streamed so the file is never held whole."""
    request = urllib.request.Request(download, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        stream = gzip.GzipFile(fileobj=response) if download.endswith(".gz") else response
        for line in stream:
            line = line.strip()
            if line:
                yield line


def bulk_cards(download: str) -> Iterator[dict]:
    """Each card of a Scryfall bulk file, streamed a line at a time so the file is never held whole."""
    for line in bulk_lines(download):
        yield json.loads(line)


def _mana_cost(card: dict) -> str:
    """What the card costs to cast, for the colours it needs: "{1}{R}", "" for a land or a card with no cost.

    A single-faced, split or adventure card has it on the card ("{1}{R} // {1}{U}" for a split card, both
    halves joined, and both count). A transform or modal double-faced card has none on the card, so the
    front face's stands in, as the front face is what a decklist plays.
    """
    cost = card.get("mana_cost") or ""
    if not cost:
        cost = (card.get("card_faces") or [{}])[0].get("mana_cost") or ""
    return cost


def _oracle_text(card: dict) -> str:
    """The rules text of the card and of each of its faces, one after another, with curly apostrophes made straight."""
    parts = [card.get("oracle_text") or ""] + [face.get("oracle_text") or "" for face in card.get("card_faces") or []]
    return "\n".join(part for part in parts if part).replace("\u2019", "'")


def _price(prices: dict) -> Optional[float]:
    """The card's price in USD, from its regular printing, else foil, else etched; None when there is none."""
    for kind in ("usd", "usd_foil", "usd_etched"):
        try:
            return float(prices[kind])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _bulk_download_uri(bulk: str = BULK_DATA_URL) -> str:
    request = urllib.request.Request(bulk, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    uri = body.get("jsonl_download_uri") or body.get("download_uri")
    if not uri:
        raise RuntimeError("Scryfall bulk-data gave no download address")
    return uri
