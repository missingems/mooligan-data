"""Entry point: `python -m mtglore {scrape,scrape-cards,scrape-archive,scrape-wiki,extract,ingest,prompt,recheck,bio-input,bio-ingest,era-ingest,build,publish,app} [--data DIR]`. See lore/README.md."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["scrape", "extract", "ingest", "prompt", "recheck", "bio-input", "bio-ingest", "scrape-cards", "scrape-archive", "scrape-wiki", "scrape-scryfall", "era-ingest", "build", "publish", "app"])
    parser.add_argument("page", nargs="?", help='ingest, prompt: the page, as "stories/<slug>" or "profiles/<slug>"')
    parser.add_argument("raw", nargs="?", type=Path, help="ingest: a JSON file in the extraction schema")
    parser.add_argument("--model", default="claude-code-session", help="ingest: who made the extraction")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "site" / "dist" / "data", help="publish: where to write the site's data")
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--refresh", action="store_true", help="scrape: fetch pages already saved again")
    parser.add_argument("--limit", type=int, help="extract: at most this many pages in the batch")
    parser.add_argument("--effort", default=os.environ.get("LORE_EFFORT", "medium"), help="extract: low, medium, high, xhigh or max")
    parser.add_argument("--wait", type=float, default=float(os.environ.get("LORE_WAIT_SECONDS", "18000")), help="extract: seconds to wait for the batch")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.step == "app":
        from .app import export

        out = args.out if args.out != parser.get_default("out") else Path(__file__).resolve().parent.parent / "site" / "dist" / "app"
        logging.info("App feed: %s", json.dumps(export(args.data, out)))
        return 0

    if args.step == "publish":
        from .publish import publish

        logging.info("Published %s", json.dumps(publish(args.data, args.out)))
        return 0

    if args.step == "scrape":
        from .site import Site, scrape

        site = Site(delay=float(os.environ.get("LORE_DELAY", "1.0")))
        report = scrape(site, args.data, site.discover(), refresh=args.refresh)
        logging.info("Saved %d pages, %d already saved, %d failed", report["saved"], report["skipped"], len(report["failed"]))
        for failure in report["failed"]:
            logging.error("  %s", failure)
        return 1 if report["failed"] and not report["saved"] else 0

    if args.step in ("scrape-cards", "scrape-archive", "scrape-wiki", "scrape-scryfall"):
        from .extract import load_pages
        from .sources import Fetcher, scrape_archive, scrape_cards, scrape_scryfall, scrape_wiki

        fetcher = Fetcher(delay=float(os.environ.get("LORE_DELAY", "1.0")))
        if args.step == "scrape-cards":
            report = scrape_cards(fetcher, args.data)
        elif args.step == "scrape-scryfall":
            report = scrape_scryfall(fetcher, args.data)
        elif args.step == "scrape-archive":
            known = {page["title"].strip().lower() for page in load_pages(args.data).values()}
            minutes = float(os.environ.get("LORE_ARCHIVE_MINUTES", "300"))
            report = scrape_archive(fetcher, args.data, known, deadline=time.time() + minutes * 60)
        else:
            report = scrape_wiki(fetcher, args.data, depth=int(os.environ.get("LORE_WIKI_DEPTH", "3")), limit=args.limit)
        failed = report.get("failed", [])
        logging.info("%s: %s", args.step, json.dumps({**report, "failed": len(failed)}))
        for failure in failed[:50]:
            logging.error("  %s", failure)
        return 0

    if args.step == "extract":
        import anthropic

        from .extract import run

        outcome, report = run(anthropic.Anthropic(), args.data, args.limit, args.effort, args.wait)
        logging.info("Extract: %s %s", outcome, json.dumps(report.get("failed") and {**report, "failed": len(report["failed"])} or report))
        for failure in report.get("failed", []):
            logging.error("  %s", failure)
        return 0

    if args.step == "prompt":
        # What the batch sends Claude for one page, for making an extraction by other means.
        from .extract import SYSTEM, load_pages, page_prompt

        print(SYSTEM + "\n\n---\n\n" + page_prompt(load_pages(args.data)[args.page]))
        return 0

    if args.step == "ingest":
        from .extract import load_pages, save

        checked = save(args.data, args.page, load_pages(args.data)[args.page], json.loads(args.raw.read_text()), args.model, None)
        print(json.dumps({"page": args.page, "entities": len(checked["entities"]), "events": len(checked["events"]),
                          "relations": len(checked["relations"]), "rejected": [(r["kind"], r["reason"], r["quote"][:60]) for r in checked["rejected"]]}))
        return 0

    if args.step == "bio-input":
        from .bios import INSTRUCTIONS, material

        print(INSTRUCTIONS + "\n\n---\n\n" + material(args.data / "index", args.page))
        return 0

    if args.step == "bio-ingest":
        from .bios import ingest

        checked = ingest(args.data, args.page, json.loads(args.raw.read_text()), args.model)
        print(json.dumps({"id": args.page, "bio": len(checked["bio"]), "summary": bool(checked["summary"]),
                          "status": bool(checked["status"]), "rejected": [(r["part"], r.get("text", "")[:60]) for r in checked["rejected"]]}))
        return 0

    if args.step == "era-ingest":
        from .eras import ingest

        report = ingest(args.data, json.loads(args.raw.read_text() if args.raw else Path(args.page).read_text()))
        print(json.dumps({"saved": report["saved"], "bad": report["bad"][:20], "bad_count": len(report["bad"])}))
        return 0

    if args.step == "recheck":
        from .extract import recheck

        print(json.dumps(recheck(args.data)))
        return 0

    from .build import build

    build(args.data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
