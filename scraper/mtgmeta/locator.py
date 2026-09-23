"""Upcoming events near a place, from Wizards' Store & Event Locator.

The locator's search page loads its results from `/search.data`, which answers
plain requests in React Router's "turbo-stream" encoding: one flat array where
objects refer to other entries by index. Each configured place is read once a
run, a page at a time, until the events run past the days ahead we publish.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .cards import slug

log = logging.getLogger(__name__)

SEARCH_URL = "https://locator.wizards.com/search.data"
SITE_SEARCH_URL = "https://locator.wizards.com/search"
STORE_URL = "https://locator.wizards.com/store"
PAGE_SIZE = 100  # the most the endpoint honours


class Locator:
    def __init__(self, user_agent: str, delay: float = 1.0) -> None:
        self._user_agent = user_agent
        self._delay = delay

    def events(self, query: str, distance_miles: int, days_ahead: int, max_pages: int = 20, now: Optional[datetime] = None) -> List[dict]:
        """Magic events within `distance_miles` of `query`, starting in the next `days_ahead` days, soonest first."""
        now = now or datetime.now(timezone.utc)
        horizon = now + timedelta(days=days_ahead)
        found: List[dict] = []
        for page in range(1, max_pages + 1):
            if page > 1:
                time.sleep(self._delay)
            payload = self._page(query, distance_miles, page)
            if payload is None:
                break
            events = _events_in(payload)
            for event in events:
                start = _parse_time(event.get("scheduledStartTime"))
                if start is None or start < now - timedelta(hours=12):
                    continue
                if start > horizon:
                    return found
                found.append(_normalize(event, start))
            info = _page_info(payload)
            if not events or not info or (page * PAGE_SIZE) >= info.get("totalResults", 0):
                break
        return found

    def _page(self, query: str, distance_miles: int, page: int) -> Optional[list]:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "searchType": "magic-events",
                "sortBy": "date",
                "sortDirection": "Asc",
                "distance": distance_miles,
                "page": page,
                "pageSize": PAGE_SIZE,
            }
        )
        request = urllib.request.Request(f"{SEARCH_URL}?{params}", headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("Locator %r page %d: %s", query, page, error)
            return None


def decode_turbo_stream(raw: list) -> Any:
    """Expands the flat array the locator sends into ordinary JSON."""

    def decode(index: Any) -> Any:
        if isinstance(index, int) and index < 0:
            return None  # sentinels for undefined, null and so on
        value = raw[index]
        if isinstance(value, dict):
            return {raw[int(key[1:])]: decode(inner) for key, inner in value.items()}
        if isinstance(value, list):
            if value and value[0] == "U":  # a URL wrapper
                return value[1]
            return [decode(inner) for inner in value]
        return value

    return decode(0)


def _search_data(payload: list) -> dict:
    root = decode_turbo_stream(payload)
    route = next((value for key, value in root.items() if key.startswith("routes/") and key.endswith("search")), {})
    return (route or {}).get("data") or {}


def _events_in(payload: list) -> List[dict]:
    search = (_search_data(payload).get("events") or {}).get("advancedSearchEvents") or {}
    return search.get("events") or search.get("storesByLocation") or []


def _page_info(payload: list) -> Optional[dict]:
    search = (_search_data(payload).get("events") or {}).get("advancedSearchEvents") or {}
    return search.get("pageInfo")


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # "2026-09-23T03:00:00.0000000Z": Python takes at most six fractional digits.
        trimmed = value.replace("Z", "+00:00")
        if "." in trimmed:
            head, rest = trimmed.split(".", 1)
            digits = rest[: rest.index("+")] if "+" in rest else rest
            trimmed = f"{head}.{digits[:6]}{rest[len(digits):]}"
        return datetime.fromisoformat(trimmed).astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize(event: dict, start: datetime) -> dict:
    store = event.get("organization") or {}
    fee = event.get("entryFee") or {}
    return {
        "id": str(event.get("id", "")),
        "title": event.get("title", ""),
        "format": (event.get("eventFormat") or {}).get("name"),
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_zone": event.get("timeZone"),
        "rules_level": event.get("rulesEnforcementLevel"),
        "has_top8": bool(event.get("hasTop8")),
        "entry_fee": {"amount": fee.get("amount"), "currency": fee.get("currency")} if fee else None,
        "capacity": event.get("capacity"),
        "tags": [tag for tag in (event.get("tags") or []) if tag != "magic:_the_gathering"],
        "is_online": bool(event.get("isOnline")),
        "latitude": event.get("latitude"),
        "longitude": event.get("longitude"),
        "store": {
            "id": str(store.get("id", "")),
            "name": store.get("name", ""),
            "address": ", ".join(part for part in (store.get("address"), store.get("city"), store.get("postalCode")) if part),
            "website": store.get("website"),
            "phone": store.get("phoneNumber"),
            "premium": bool(store.get("isPremium")),
            "url": f"{STORE_URL}/{store.get('id')}" if store.get("id") else None,
        },
    }


def place_page(query: str, distance_miles: int, days_ahead: int, events: List[dict], generated_at: str) -> dict:
    return {
        "schema": 1,
        "place": query,
        "slug": slug(query),
        "distance_miles": distance_miles,
        "days_ahead": days_ahead,
        "generated_at": generated_at,
        "url": f"{SITE_SEARCH_URL}?{urllib.parse.urlencode({'query': query, 'searchType': 'magic-events', 'distance': distance_miles})}",
        "events": sorted(events, key=lambda event: event["start"]),
    }
