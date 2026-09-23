"""Commander (EDH) usage for a card, from EDHREC, used with their permission.

EDHREC publishes a JSON page per card holding how many Commander decks play
it and which commanders play it most. A run refreshes a slice of the cards,
oldest check first, so the whole set comes round over a few days without
asking them for much at once. Their numbers move about once a day.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

BASE_URL = "https://json.edhrec.com/pages/cards"
CARD_URL = "https://edhrec.com/cards"
# Commanders kept per card, most decks first.
MAX_COMMANDERS = 12

# EDHREC drops apostrophes and commas rather than replacing them:
# "Y'shtola, Night's Blessed" becomes "yshtola-nights-blessed".
_DROPPED = re.compile(r"['’.,:!?\"()]")


def edhrec_slug(card_name: str) -> str:
    front = card_name.split("//")[0]
    return re.sub(r"[^a-z0-9]+", "-", _DROPPED.sub("", front.lower())).strip("-")


class Edhrec:
    def __init__(self, user_agent: str, delay: float = 0.4) -> None:
        self._user_agent = user_agent
        self._delay = delay

    def card(self, slug: str) -> Optional[dict]:
        """What Commander decks do with this card, or None when EDHREC has no page for it."""
        request = urllib.request.Request(f"{BASE_URL}/{slug}.json", headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            # A card they have no page for answers 403 from their bucket.
            if error.code in (403, 404):
                return None
            log.warning("EDHREC %s: %s", slug, error)
            return None
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("EDHREC %s: %s", slug, error)
            return None
        return _entry(body, slug)

    def cards(self, slugs: Sequence[str]) -> Dict[str, Optional[dict]]:
        """Reads each card in turn, pausing between requests to keep the rate low."""
        entries: Dict[str, Optional[dict]] = {}
        for index, slug in enumerate(slugs):
            if index:
                time.sleep(self._delay)
            entries[slug] = self.card(slug)
        found = sum(1 for entry in entries.values() if entry)
        log.info("EDHREC: read %d cards, %d with Commander data", len(entries), found)
        return entries


def _entry(body: dict, slug: str) -> Optional[dict]:
    container = body.get("container", {}).get("json_dict", {})
    card = container.get("card") or {}
    decks, of_decks = card.get("num_decks"), card.get("potential_decks")
    if not isinstance(decks, int) or not isinstance(of_decks, int) or of_decks <= 0:
        return None
    commanders: List[dict] = []
    for cardlist in container.get("cardlists", []):
        if cardlist.get("tag") != "topcommanders":
            continue
        for view in cardlist.get("cardviews", [])[:MAX_COMMANDERS]:
            if not isinstance(view.get("num_decks"), int) or not view.get("sanitized"):
                continue
            commanders.append(
                {
                    "name": view.get("name", ""),
                    "slug": view["sanitized"],
                    "decks": view["num_decks"],
                    "of_decks": view.get("potential_decks") or 0,
                }
            )
    return {
        "decks": decks,
        "of_decks": of_decks,
        "salt": round(card["salt"], 2) if isinstance(card.get("salt"), (int, float)) else None,
        "url": f"{CARD_URL}/{slug}",
        "commanders": commanders,
    }


def due_slugs(known: Dict[str, dict], wanted: Dict[str, str], limit: int) -> List[Tuple[str, str]]:
    """The cards to refresh this run: never checked first, then the longest unchecked."""
    if limit <= 0:
        return []
    ordered = sorted(wanted.items(), key=lambda item: known.get(item[1], {}).get("checked_at", ""))
    return ordered[:limit]
