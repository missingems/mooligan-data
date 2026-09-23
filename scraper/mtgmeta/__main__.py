"""Entry point: `python -m mtgmeta DIR`. Settings come from the environment (see README).

DIR holds the previous snapshots and deck id list on the way in, and the files
to publish on the way out.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .browser import open_browser
from .edhrec import Edhrec
from .published import fetch_published_decks
from .scrape import ScrapeConfig, scrape
from .store import SnapshotStore


def _list(name: str, default: str):
    return tuple(item.strip().lower() for item in os.environ.get(name, default).split(",") if item.strip())


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
        max_new_events=int(os.environ.get("MAX_NEW_EVENTS", "60")),
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
    written = store.finish(
        fetch_decks=lambda ids: fetch_published_decks(data_url, ids),
        fetch_edh=edhrec.cards,
        edh_limit=int(os.environ.get("EDHREC_CARDS_PER_RUN", "800")),
    )
    logging.info("Wrote %s", ", ".join(written) or "no snapshots")

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
