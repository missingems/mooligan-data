"""Entry point: `python -m mtgmeta [--dry-run DIR]`. Settings come from the environment (see README)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .browser import open_browser
from .scrape import ScrapeConfig, scrape
from .store import FirestoreStore, JsonFileStore


def _list(name: str, default: str):
    return tuple(item.strip().lower() for item in os.environ.get(name, default).split(",") if item.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", metavar="DIR", type=Path, help="write JSON files to DIR instead of Firestore")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = ScrapeConfig(
        formats=_list("FORMATS", "modern,standard,pioneer"),
        meta_days=_list("META_DAYS", "30"),
        events_per_format=int(os.environ.get("EVENTS_PER_FORMAT", "10")),
        max_new_decks=int(os.environ.get("MAX_NEW_DECKS", "400")),
        archetype_decks=int(os.environ.get("ARCHETYPE_DECKS", "100")),
    )
    store = JsonFileStore(args.dry_run) if args.dry_run else FirestoreStore(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    headless = os.environ.get("HEADLESS", "0" if sys.platform.startswith("linux") else "1") == "1"
    with open_browser(headless=headless, delay=float(os.environ.get("REQUEST_DELAY", "1.5"))) as browser:
        report = scrape(browser, store, config)

    logging.info(
        "Done: %d meta, %d events, %d decks written, %d already stored, %d errors",
        len(report.meta), len(report.events), report.decks_written, report.decks_skipped, len(report.errors),
    )
    for error in report.errors:
        logging.error("  %s", error)
    # A partial run still keeps what it saved; fail the job so Cloud Run surfaces it.
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
