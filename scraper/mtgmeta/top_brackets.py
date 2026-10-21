"""edh/top.json's `brackets`: the 50 commanders most played at each of Wizards' five Commander Brackets.

Brackets 1 to 4 rank EDHREC's top 300 commanders of the past month by how many of each one's decks their builders put
at that bracket (EDHREC's `bracket_counts`, used with their permission). A commander's counts come from the page the
run just wrote for it, else from `state/bracket-counts.json` when under a week old, else from EDHREC, at most
BRACKET_PAGES_PER_RUN pages a run with EDHREC_DELAY seconds between; so after the first run only the stale ones are read.

Bracket 5, cEDH, ranks the commanders of competitive tournaments instead: EDHTop16's tournament entries of the past three
months, at events of 30 players or more. EDHREC's Bracket 5 counts are what builders call their own decks (Etali, Primal
Conqueror has 2,532 "cEDH" decks there and about 40 tournament entries a month), so they rank popular casual commanders
with cEDH ones; tournament entries are what cEDH players do play. Each EDHTop16 commander is matched to its EDHREC page,
which gives the slug, the name and the EDHREC Bracket 5 count shown beside the entries. When EDHTop16 cannot be read
(its rows are cached in `state/edhtop16.json` for a day), Bracket 5 falls back to EDHREC's counts, and says so in its
`source`. See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .edhrec import COMMANDER_URL, edhrec_slug
from .guide_brackets import NAMES

log = logging.getLogger(__name__)

PER_BRACKET = 50
COUNTS_PATH = "state/bracket-counts.json"
COUNTS_DAYS = 7
EDHTOP16_PATH = "state/edhtop16.json"
EDHTOP16_HOURS = 20
# A cached read older than this is not used even when EDHTop16 cannot be read; EDHREC's counts are then.
EDHTOP16_STALE_DAYS = 7
CEDH = 5

EDHTOP16_SITE = "https://edhtop16.com"
EDHTOP16_GRAPHQL = f"{EDHTOP16_SITE}/api/graphql"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
# EDHTop16's GraphQL takes only the queries its own site was built with, by id ("pastoria-id"). This is the id of its
# commander list's paging query, read from its page script; a rebuild of the site can change it, and `query_id` then
# reads the current one from the site.
EDHTOP16_QUERY = "TopCommandersQuery"
EDHTOP16_QUERY_ID = "86fac9d8c2353944c65306a21cd17574"
EDHTOP16_PERIOD = "THREE_MONTHS"
EDHTOP16_WINDOW = "3m"
EDHTOP16_MIN_SIZE = 30
# More than 50, for the ones no EDHREC page is found for.
EDHTOP16_COUNT = 60


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}


def _http_json(url: str, body: Optional[dict] = None) -> Optional[dict]:
    """The JSON at `url` (POSTed `body` when given); None when there is none."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": USER_AGENT, **({"Content-Type": "application/json"} if data else {})}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return None
        raise


def _http_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def edhrec_page_counts(body: Optional[dict]) -> Optional[dict]:
    """A commander page's name, decks and decks per bracket, as `state/bracket-counts.json` keeps them."""
    card = (((body or {}).get("container") or {}).get("json_dict") or {}).get("card") or {}
    if not isinstance(card.get("num_decks"), int) or not card.get("name"):
        return None
    counts = (body or {}).get("bracket_counts") or {}
    return {
        "name": card["name"],
        "decks": card["num_decks"],
        "bracket_decks": {level: counts[level] for level in sorted(counts) if level in "12345" and len(level) == 1 and isinstance(counts[level], int)},
    }


@dataclass
class Counts:
    """Each commander's decks per bracket, from this run's pages, the cache, or EDHREC, a few pages a run."""

    directory: Path
    now: datetime
    fetch: Callable[[str], Optional[dict]]
    limit: int = 150
    delay: float = 0.4
    cache: Dict[str, dict] = field(default_factory=dict)
    fetched: int = 0

    def __post_init__(self) -> None:
        self.cache = _read(self.directory / COUNTS_PATH)

    def get(self, slug: str) -> Optional[dict]:
        page = _read(self.directory / "edh" / "commanders" / f"{slug}.json")
        if page.get("name") and "bracket_decks" in page:
            self.cache[slug] = {"name": page["name"], "decks": page.get("decks") or 0, "bracket_decks": page["bracket_decks"], "checked_at": _iso(self.now)}
            return self.cache[slug]
        cached = self.cache.get(slug)
        if cached and cached.get("checked_at", "") >= _iso(self.now - timedelta(days=COUNTS_DAYS)):
            return cached if cached.get("name") else None
        if self.fetched >= self.limit:
            return cached if cached and cached.get("name") else None
        if self.fetched:
            time.sleep(self.delay)
        self.fetched += 1
        try:
            entry = edhrec_page_counts(self.fetch(f"{COMMANDER_URL}/{slug}.json"))
        except Exception as error:  # noqa: BLE001 - a page that cannot be read is skipped this run
            log.warning("Bracket counts %s: %s", slug, error)
            return cached if cached and cached.get("name") else None
        # A commander EDHREC has no page for is remembered too, so it is not asked for again all week.
        self.cache[slug] = {**(entry or {}), "checked_at": _iso(self.now)}
        return self.cache[slug] if entry else None

    def save(self) -> None:
        path = self.directory / COUNTS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.cache, sort_keys=True, separators=(",", ":")))


def rank_by_decks(counts: Dict[str, dict], level: int, limit: int = PER_BRACKET) -> List[dict]:
    """The commanders with the most decks at `level`, most first (by name on a tie), as top.json's rows."""
    key = str(level)
    played = [(slug, entry) for slug, entry in counts.items() if (entry.get("bracket_decks") or {}).get(key)]
    played.sort(key=lambda item: (-item[1]["bracket_decks"][key], item[1]["name"]))
    return [
        {"slug": slug, "name": entry["name"], "decks": entry["bracket_decks"][key], "of_decks": entry.get("decks") or 0}
        for slug, entry in played[:limit]
    ]


def edhrec_slugs(name: str) -> List[str]:
    """The EDHREC slugs an EDHTop16 commander may have, the likeliest first.

    EDHTop16 writes a partner pair "A / B" and a double-faced card "Front // Back". EDHREC slugs a double-faced card by
    its front face, and a pair by both names in alphabetical order ("kraum-ludevics-opus-tymna-the-weaver").
    """
    if " // " in name or " / " not in name:
        return [edhrec_slug(name)]
    halves = sorted((half.strip() for half in name.split(" / ")), key=str.lower)
    return list(dict.fromkeys(["-".join(edhrec_slug(half) for half in halves), "-".join(edhrec_slug(half) for half in reversed(halves))]))


def query_id(read_text: Callable[[str], str] = _http_text) -> Optional[str]:
    """The id EDHTop16's current page script gives its commander list's paging query, or None when it cannot be found."""
    try:
        home = read_text(EDHTOP16_SITE + "/")
        for script in dict.fromkeys(re.findall(r'/assets/page-[\w-]+\.js', home)):
            match = re.search(r"id:`([0-9a-f]{32})`,metadata:\{\},name:`" + EDHTOP16_QUERY + "`", read_text(EDHTOP16_SITE + script))
            if match:
                return match.group(1)
    except (urllib.error.URLError, OSError, ValueError) as error:
        log.warning("EDHTop16: its page script could not be read: %s", error)
    return None


def edhtop16_rows(post: Callable[[str, dict], Optional[dict]] = _http_json, find_id: Callable[[], Optional[str]] = query_id) -> Optional[List[dict]]:
    """EDHTop16's most entered commanders of the period, most first; None when it cannot be read."""
    variables = {
        "colorId": None, "minEntries": 1, "minSize": EDHTOP16_MIN_SIZE, "sortBy": "POPULARITY",
        "timePeriod": EDHTOP16_PERIOD, "count": EDHTOP16_COUNT, "cursor": None,
    }

    def ask(identifier: str) -> Optional[List[dict]]:
        try:
            body = post(EDHTOP16_GRAPHQL, {"query": None, "variables": variables, "extensions": {"pastoria-id": identifier}})
        except (urllib.error.URLError, OSError, ValueError) as error:
            log.warning("EDHTop16: %s", error)
            return None
        edges = ((((body or {}).get("data") or {}).get("commanders") or {}).get("edges")) or []
        rows = []
        for edge in edges:
            node = edge.get("node") or {}
            stats = node.get("stats") or {}
            if node.get("name") and isinstance(stats.get("count"), int):
                rows.append({
                    "name": node["name"],
                    "entries": stats["count"],
                    "top_cuts": stats.get("topCuts") if isinstance(stats.get("topCuts"), int) else None,
                    "conversion_rate": round(stats["conversionRate"] * 100, 1) if isinstance(stats.get("conversionRate"), (int, float)) else None,
                })
        return rows or None

    rows = ask(EDHTOP16_QUERY_ID)
    if rows is None:
        current = find_id()
        if current and current != EDHTOP16_QUERY_ID:
            log.warning("EDHTop16: query id %s failed; the site's current one is %s (update EDHTOP16_QUERY_ID)", EDHTOP16_QUERY_ID, current)
            rows = ask(current)
    return rows


def cached_edhtop16(directory: Path, now: datetime, read: Callable[[], Optional[List[dict]]] = edhtop16_rows) -> Optional[List[dict]]:
    """EDHTop16's rows, read again when the cached ones are a day old; a week-old read stands in when it cannot be."""
    path = directory / EDHTOP16_PATH
    cached = _read(path)
    if cached.get("rows") and cached.get("fetched_at", "") >= _iso(now - timedelta(hours=EDHTOP16_HOURS)):
        return cached["rows"]
    rows = read()
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": _iso(now), "period": EDHTOP16_PERIOD, "min_size": EDHTOP16_MIN_SIZE, "rows": rows}, separators=(",", ":")))
        return rows
    if cached.get("rows") and cached.get("fetched_at", "") >= _iso(now - timedelta(days=EDHTOP16_STALE_DAYS)):
        log.warning("EDHTop16 could not be read; using its rows of %s", cached["fetched_at"])
        return cached["rows"]
    return None


def rank_cedh(rows: Sequence[dict], counts: Counts, limit: int = PER_BRACKET) -> List[dict]:
    """EDHTop16's commanders matched to their EDHREC pages, most entries first; one with no page is left out."""
    ranked: List[dict] = []
    seen = set()
    for row in rows:
        match = next(((slug, entry) for slug in edhrec_slugs(row["name"]) for entry in [counts.get(slug)] if entry), None)
        if match is None:
            log.info("cEDH: no EDHREC page for %s", row["name"])
            continue
        slug, entry = match
        if slug in seen:
            continue
        seen.add(slug)
        ranked.append({
            "slug": slug,
            "name": entry["name"],
            "entries": row["entries"],
            "top_cuts": row["top_cuts"],
            "conversion_rate": row["conversion_rate"],
            "decks": (entry.get("bracket_decks") or {}).get(str(CEDH)),
            "of_decks": entry.get("decks") or 0,
        })
        if len(ranked) == limit:
            break
    return ranked


def rank_brackets(
    directory: Path,
    candidates: Sequence[str],
    now: datetime,
    *,
    fetch_edhrec: Callable[[str], Optional[dict]],
    read_edhtop16: Callable[[], Optional[List[dict]]] = edhtop16_rows,
    limit: int = 150,
    delay: float = 0.4,
) -> Dict[int, dict]:
    """Each bracket's ranked commanders, as `top.build_top` takes them: {level: {"source", "rows"[, "window"]}}."""
    counts = Counts(directory, now, fetch_edhrec, limit=limit, delay=delay)
    known = {slug: entry for slug in dict.fromkeys(candidates) for entry in [counts.get(slug)] if entry}
    brackets: Dict[int, dict] = {}
    for level in NAMES:
        if level == CEDH:
            continue
        rows = rank_by_decks(known, level)
        if rows:
            brackets[level] = {"source": "edhrec", "rows": rows}
    tournament = cached_edhtop16(directory, now, read_edhtop16)
    cedh = rank_cedh(tournament, counts) if tournament else []
    if cedh:
        brackets[CEDH] = {"source": "edhtop16", "window": EDHTOP16_WINDOW, "rows": cedh}
    else:
        log.warning("cEDH: EDHTop16 could not be read, so Bracket 5 is ranked by EDHREC's counts")
        rows = rank_by_decks(known, CEDH)
        if rows:
            brackets[CEDH] = {"source": "edhrec", "rows": rows}
    counts.save()
    log.info(
        "Bracket rankings: %d candidates with counts, %d EDHREC pages read; %s",
        len(known), counts.fetched, ", ".join(f"{level}: {len(block['rows'])} ({block['source']})" for level, block in sorted(brackets.items())),
    )
    return brackets


def bracket_slugs(top: Optional[dict]) -> List[str]:
    """Every commander a published top.json ranks at a bracket, bracket 1's first and each once."""
    blocks = (top or {}).get("brackets") or {}
    return list(dict.fromkeys(row["slug"] for level in sorted(blocks, key=str) for row in blocks[level].get("commanders") or []))
