"""Entry point: `python -m mtgmeta DIR`. Settings come from the environment (see README).

DIR holds the previous snapshots and deck id list on the way in, and the files
to publish on the way out.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .browser import open_browser
from .edhrec import Edhrec
from .locator import Locator, place_page
from .published import fetch_published_decks
from .scryfall import card_catalog
from .scrape import ScrapeConfig, scrape
from .store import SnapshotStore


def _list(name: str, default: str):
    return tuple(item.strip().lower() for item in os.environ.get(name, default).split(",") if item.strip())


def _centre(events: list) -> dict:
    """The median coordinates of a place's events, which sits on the place itself."""
    lats = sorted(e["latitude"] for e in events if isinstance(e.get("latitude"), (int, float)))
    lngs = sorted(e["longitude"] for e in events if isinstance(e.get("longitude"), (int, float)))
    if not lats or not lngs:
        return {}
    return {"latitude": round(lats[len(lats) // 2], 4), "longitude": round(lngs[len(lngs) // 2], 4)}


def publish_premier(directory: Path, report) -> list:
    """The premier play calendar from magic.gg, as premier/schedule.json."""
    if os.environ.get("PREMIER_SCHEDULE", "1") != "1":
        return []
    from .premier import by_type, calendar_from_html, fetch_schedule, premier_events, schedule_page

    try:
        html = fetch_schedule(os.environ.get("LOCATOR_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"))
        events = premier_events(calendar_from_html(html))
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Premier schedule failed")
        report.errors.append(f"premier schedule: {error}")
        return []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = directory / "premier" / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule_page(events, stamp), ensure_ascii=False, separators=(",", ":")))
    logging.info("Premier schedule: %d upcoming events %s", len(events), by_type(events))
    return ["premier/schedule.json"]


def publish_locator(directory: Path, report) -> list:
    """Upcoming events near each configured place, from Wizards' locator, as locator/<place>.json."""
    places = [place.strip() for place in os.environ.get("LOCATOR_PLACES", "").split(";") if place.strip()]
    if not places:
        return []
    locator = Locator(
        user_agent=os.environ.get("LOCATOR_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"),
        delay=float(os.environ.get("LOCATOR_DELAY", "1.0")),
    )
    distance = int(os.environ.get("LOCATOR_DISTANCE_MILES", "15"))
    days = int(os.environ.get("LOCATOR_DAYS", "14"))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written, index = [], {}
    for place in places:
        try:
            events = locator.events(place, distance, days)
        except Exception as error:  # noqa: BLE001 - one place must not stop the others
            logging.exception("Locator failed for %s", place)
            report.errors.append(f"locator {place}: {error}")
            continue
        page = place_page(place, distance, days, events, stamp)
        path = directory / "locator" / f"{page['slug']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")))
        index[page["slug"]] = {
            "place": place,
            "events": len(events),
            "distance_miles": distance,
            "days_ahead": days,
            # The place's own coordinates, for an app choosing the nearest published place.
            **_centre(events),
        }
        written.append(f"locator/{page['slug']}.json")
        logging.info("Locator: %d events in the next %d days near %s", len(events), days, place)
    if index:
        (directory / "locator" / "index.json").write_text(json.dumps({"schema": 1, "generated_at": stamp, "places": index}, indent=2))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="data directory, mirroring the R2 bucket")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = ScrapeConfig(
        formats=_list("FORMATS", "modern,standard,pioneer,legacy,pauper,vintage,premodern,penny_dreadful,duel_commander"),
        meta_days=_list("META_DAYS", "30"),
        events_per_format=int(os.environ.get("EVENTS_PER_FORMAT", "10")),
        max_new_decks=int(os.environ.get("MAX_NEW_DECKS", "400")),
        archetype_decks=int(os.environ.get("ARCHETYPE_DECKS", "100")),
        max_new_events=int(os.environ.get("MAX_NEW_EVENTS", "150")),
        max_search_pages=int(os.environ.get("MAX_SEARCH_PAGES", "25")),
        history_days=int(os.environ.get("HISTORY_DAYS", "30")),
        max_archetype_pages=int(os.environ.get("MAX_ARCHETYPE_PAGES", "20")),
    )
    store = SnapshotStore(args.directory, config.formats, config.history_days)
    headless = os.environ.get("HEADLESS", "0" if sys.platform.startswith("linux") else "1") == "1"
    with open_browser(
        headless=headless,
        delay=float(os.environ.get("REQUEST_DELAY", "1.5")),
        concurrency=int(os.environ.get("CONCURRENCY", "6")),
    ) as browser:
        report = scrape(browser, store, config)
    data_url = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")
    # EDHREC is read with their permission: a slice of the cards each run, at a low rate.
    edhrec = Edhrec(
        user_agent=os.environ.get("EDHREC_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"),
        delay=float(os.environ.get("EDHREC_DELAY", "0.4")),
    )
    # Every card Magic has: oracle ids for the card pages, and the Commander rotation.
    try:
        catalog = card_catalog() if os.environ.get("SCRYFALL_CATALOG", "1") == "1" else {}
    except Exception as error:  # noqa: BLE001 - the run still publishes without it
        logging.exception("Could not read Scryfall's card catalog")
        report.errors.append(f"scryfall catalog: {error}")
        catalog = {}
    written = store.finish(
        fetch_decks=lambda ids: fetch_published_decks(data_url, ids),
        fetch_edh=edhrec.cards,
        edh_limit=int(os.environ.get("EDHREC_CARDS_PER_RUN", "800")),
        catalog=catalog,
        fetch_commanders=edhrec.commanders,
        commander_limit=int(os.environ.get("EDHREC_COMMANDERS_PER_RUN", "150")),
    )
    logging.info("Wrote %s", ", ".join(written) or "no snapshots")
    written += publish_locator(args.directory, report)
    written += publish_premier(args.directory, report)

    logging.info(
        "Done: %d meta, %d archetypes, %d events, %d decks written, %d already stored, %d errors",
        len(report.meta), len(report.archetypes), len(report.events), report.decks_written, report.decks_skipped, len(report.errors),
    )
    for error in report.errors:
        logging.error("  %s", error)
    # A partial run still publishes what it saved; the exit code flags the errors.
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
