"""The premier play calendar from magic.gg: Pro Tours, Regional Championships, Spotlight Series, Worlds.

magic.gg/schedule is a Nuxt page that embeds its whole calendar as
`window.__NUXT__`, a JavaScript function expression rather than JSON. Node
evaluates it; nothing else on the page is needed.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

SCHEDULE_URL = "https://magic.gg/schedule"

# Wizards' Regional Championship regions, matched on the city or country in an
# event's name. The app picks a region from the device's country the same way.
REGIONS = {
    "southeast_asia": ("Singapore", "Kuala Lumpur", "Bangkok", "Manila", "Jakarta", "Ho Chi Minh", "Hanoi", "SEA Championship"),
    "japan": ("Japan", "Tokyo", "Yokohama", "Osaka", "Chiba", "Champions Cup"),
    "chinese_taipei": ("Taipei", "Taiwan", "MIT Championship"),
    "china": ("China", "Hangzhou", "Shanghai", "Beijing", "Shenzhen", "Dragon Shield Cup"),
    "korea": ("Korea", "Seoul"),
    "australia_nz": ("Australia", "Sydney", "Melbourne", "Brisbane", "Auckland", "New Zealand", "Super Series"),
    "usa": ("USA", "United States", "SCG", "Los Angeles", "Baltimore", "Atlanta", "Las Vegas", "Orlando", "Sacramento", "Elmhurst", "Alexandria", "Chicago", "Dallas", "Seattle"),
    "canada": ("Canada", "Ottawa", "Toronto", "Montreal", "Vancouver", "F2F Tour"),
    "europe": ("EMEA", "Europe", "Ghent", "Bologna", "Leicester", "Marl", "Lyon", "Paris", "London", "Barcelona", "Madrid", "Berlin", "Amsterdam", "Utrecht", "Prague", "Warsaw", "Lisbon", "Milan", "Naples"),
    "mexico_central_america": ("Mexico", "Central America", "Caribbean", "Guatemala", "Costa Rica"),
    "south_america": ("South America", "Buenos Aires", "São Paulo", "Sao Paulo", "Santiago", "Bogotá", "Bogota", "Lima", "Brazil", "Argentina", "Chile"),
}


def fetch_schedule(user_agent: str, url: str = SCHEDULE_URL) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def calendar_from_html(html: str) -> List[dict]:
    """The raw calendar entries embedded in the schedule page."""
    match = re.search(r"<script>window\.__NUXT__=(.*?)</script>", html, re.S)
    if not match:
        raise ValueError("No __NUXT__ state on the schedule page")
    script = "globalThis.window={};const v=" + match.group(1) + ";process.stdout.write(JSON.stringify(v.fetch||{}));"
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise ValueError(f"Node could not evaluate the schedule state: {result.stderr.strip()[:200]}")
    fetched = json.loads(result.stdout)
    for key, value in fetched.items():
        if key.startswith("EventsCalendar") and isinstance(value, dict) and isinstance(value.get("payload"), list):
            return value["payload"]
    raise ValueError("No EventsCalendar payload on the schedule page")


def premier_events(entries: List[dict], now: Optional[datetime] = None, months_ahead: int = 12) -> List[dict]:
    """Upcoming (and just-finished) premier events, soonest first, in the published shape."""
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=31 * months_ahead)
    events = []
    for entry in entries:
        start, end = _parse(entry.get("startTime")), _parse(entry.get("endTime"))
        if start is None:
            continue
        if (end or start) < now - timedelta(days=7) or start > horizon:
            continue
        name = (entry.get("eventName") or entry.get("entryTitle") or "").strip()
        place = name.split(": ", 1)[1].strip() if ": " in name else None
        events.append(
            {
                "id": entry.get("id"),
                "name": name,
                "type": (entry.get("eventScheduleType") or {}).get("typeTitle"),
                "start": start.strftime("%Y-%m-%d"),
                "end": (end or start).strftime("%Y-%m-%d"),
                "start_time": entry.get("startTime"),
                "end_time": entry.get("endTime"),
                "place": place,
                "region": region_of(name),
                "game_type": entry.get("gameType"),
                "url": entry.get("link") or SCHEDULE_URL,
            }
        )
    return sorted(events, key=lambda event: (event["start"], event["name"]))


def region_of(name: str) -> Optional[str]:
    for region, keywords in REGIONS.items():
        if any(keyword.lower() in name.lower() for keyword in keywords):
            return region
    return None


def schedule_page(events: List[dict], generated_at: str) -> dict:
    return {
        "schema": 1,
        "generated_at": generated_at,
        "source": SCHEDULE_URL,
        "regions": sorted(REGIONS),
        "events": events,
    }


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def by_type(events: List[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in events:
        counts[event["type"] or "Other"] = counts.get(event["type"] or "Other", 0) + 1
    return counts
