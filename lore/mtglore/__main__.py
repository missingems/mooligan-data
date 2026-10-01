"""Entry point: `python -m mtglore {scrape,extract,build} [--data DIR]`. See lore/README.md."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["scrape", "extract", "build"])
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--refresh", action="store_true", help="scrape: fetch pages already saved again")
    parser.add_argument("--limit", type=int, help="extract: at most this many pages in the batch")
    parser.add_argument("--effort", default=os.environ.get("LORE_EFFORT", "medium"), help="extract: low, medium, high, xhigh or max")
    parser.add_argument("--wait", type=float, default=float(os.environ.get("LORE_WAIT_SECONDS", "18000")), help="extract: seconds to wait for the batch")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.step == "scrape":
        from .site import Site, scrape

        site = Site(delay=float(os.environ.get("LORE_DELAY", "1.0")))
        report = scrape(site, args.data, site.discover(), refresh=args.refresh)
        logging.info("Saved %d pages, %d already saved, %d failed", report["saved"], report["skipped"], len(report["failed"]))
        for failure in report["failed"]:
            logging.error("  %s", failure)
        return 1 if report["failed"] and not report["saved"] else 0

    if args.step == "extract":
        import anthropic

        from .extract import run

        outcome, report = run(anthropic.Anthropic(), args.data, args.limit, args.effort, args.wait)
        logging.info("Extract: %s %s", outcome, json.dumps(report.get("failed") and {**report, "failed": len(report["failed"])} or report))
        for failure in report.get("failed", []):
            logging.error("  %s", failure)
        return 0

    from .build import build

    build(args.data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
