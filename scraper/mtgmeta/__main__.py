"""Entry point: `python -m mtgmeta DIR`. Settings come from the environment (see README).

DIR holds the previous snapshots and deck id list on the way in, and the files
to publish on the way out.

`python -m mtgmeta clusters DIR ...` is instead a dry run of archetype merging (see clusters.py).
`python -m mtgmeta guides DIR --top 5` builds the top commanders' guides by hand, `--polish` having Claude write their summaries (see guides.py).
`python -m mtgmeta guide-combos DIR --top 5` adds Commander Spellbook's combos to the top commanders' guides (see guide_combos.py).
`python -m mtgmeta primers DIR` has Claude write the archetype primers that are missing or stale, `--publish` putting them on api.mooligan.com (see primers.py).
`python -m mtgmeta set-art DIR` writes sets/art.json, Wizards' art for each set (see setart.py).
`python -m mtgmeta set-tints DIR` writes sets/tints.json, one tint colour per set for its icon tile (see settints.py).
`python -m mtgmeta set-products DIR` writes sets/products/{code}.json, each recent set's sealed products (see setproducts.py).
`python -m mtgmeta set-mechanics DIR` writes sets/mechanics.json, the mechanics each set introduced (see setmechanics.py).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .browser import open_browser
from .edhrec import Edhrec
from .locator import Locator, place_page
from .models import RunReport
from .pacing import DeckPacing, note_deck_block
from .previews import NewPrintings, read_first_seen, read_seen
from .published import fetch_published_decks
from .scryfall import card_catalog
from .scrape import ScrapeConfig, scrape
from .store import SnapshotStore
from .top import top_slugs, write_top
from .top_brackets import bracket_slugs


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
    from .premier_formats import fetch_article, make_client, read_cache, tag_formats, write_cache

    agent = os.environ.get("LOCATOR_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)")
    try:
        html = fetch_schedule(agent)
        events = premier_events(calendar_from_html(html))
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Premier schedule failed")
        report.errors.append(f"premier schedule: {error}")
        return []
    try:
        client = make_client()
        if client is None:
            logging.info("Premier formats: no ANTHROPIC_API_KEY, so only the rules and overrides tag events")
        write_cache(directory, tag_formats(events, read_cache(directory), client, lambda url: fetch_article(url, agent)))
    except Exception as error:  # noqa: BLE001 - the schedule is still published, with the rules' formats
        logging.warning("Premier formats failed", exc_info=True)
        report.warnings.append(f"premier formats: {error}")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = directory / "premier" / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule_page(events, stamp), ensure_ascii=False, separators=(",", ":")))
    logging.info("Premier schedule: %d upcoming events %s", len(events), by_type(events))
    return ["premier/schedule.json"]


def published_bracket_slugs(data_url: str) -> list:
    """The commanders the published edh/top.json ranks at a bracket, whose pages the commander refresh keeps a week fresh."""
    from .guides import http_json

    try:
        return bracket_slugs(http_json(f"{data_url}/edh/top.json"))
    except Exception:  # noqa: BLE001 - the refresh goes on without them
        logging.warning("The published edh/top.json could not be read", exc_info=True)
        return []


def rank_brackets(directory: Path, report, edhrec: Edhrec, top: dict) -> dict:
    """The 50 commanders most played at each Commander Bracket, for edh/top.json (see top_brackets.py).

    Brackets 1 to 4 rank EDHREC's top 300 of the past month by their decks at the bracket; cEDH ranks EDHTop16's
    tournament entries. Ranking fails soft: top.json is then written without `brackets`.
    """
    if not top:
        return {}
    from .guides import edhrec_json
    from .top_brackets import rank_brackets as rank

    try:
        candidates = top_slugs(top) + [row["slug"] for row in edhrec.more_top_commanders("30d", pages=2)]
        return rank(
            directory, candidates, datetime.now(timezone.utc), fetch_edhrec=edhrec_json,
            limit=int(os.environ.get("BRACKET_PAGES_PER_RUN", "150")), delay=float(os.environ.get("EDHREC_DELAY", "0.4")),
        )
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Bracket rankings failed", exc_info=True)
        report.warnings.append(f"bracket rankings: {error}")
        return {}


def publish_top(directory: Path, report, top: dict, catalog: Optional[dict] = None, brackets: Optional[dict] = None) -> list:
    """EDHREC's ranked top commanders of the past week and month, and each bracket's, as edh/top.json.

    `top` is what `Edhrec.top_commanders` read before `store.finish`. A window it could not read is left out, and when it
    read none the file stays published as it was.
    """
    try:
        return write_top(directory, top, datetime.now(timezone.utc), catalog, brackets)
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("EDHREC top commanders failed")
        report.errors.append(f"edhrec top commanders: {error}")
        return []


def publish_guides(directory: Path, report, top: dict, catalog: Optional[dict], data_url: str, brackets: Optional[dict] = None) -> list:
    """The commander guides of the top commanders, built from EDHREC and Commander Spellbook, as edh/commanders/{slug}/guide.json.

    The commanders are the first GUIDES_TOP (100) of the windows and every one a bracket ranks. It reads the commander pages
    `store.finish` wrote this run (else the published ones at `data_url`) and builds the guides that are due, at most
    GUIDES_PER_RUN of them, so a run asks EDHREC for a few hundred pages and the rest come round on later runs. With
    ANTHROPIC_API_KEY set, the guides whose facts changed are polished by Claude as one Message Batch (see guide_polish.py).
    A guide that fails stays published as it was; that is a warning, not an error, so the run passes.
    """
    limit = int(os.environ.get("GUIDES_PER_RUN", "60"))
    if limit <= 0 or not catalog:
        return []
    from .guide_polish import make_polisher
    from .guides import Source, run as build_guides

    ranked = [row["slug"] for _, block in sorted((brackets or {}).items()) for row in block["rows"]]
    slugs = list(dict.fromkeys(top_slugs(top)[: int(os.environ.get("GUIDES_TOP", "100"))] + ranked))
    try:
        polish = make_polisher()
    except Exception:  # noqa: BLE001 - the guides are still built, templated
        logging.warning("The guide polisher could not be made", exc_info=True)
        polish = None
    if polish is None:
        logging.info("Commander guides: not polished (no ANTHROPIC_API_KEY, or GUIDE_POLISH=0)")
    try:
        result = build_guides(
            directory, slugs, Source(directory, data_url), catalog, limit=limit, delay=float(os.environ.get("GUIDE_DELAY", "1.0")),
            polish=polish,
        )
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Commander guides failed", exc_info=True)
        report.warnings.append(f"commander guides: {error}")
        return []
    logging.info(
        "Commander guides of %d commanders: %d written, %d unchanged, %d left for the next run, %d failed; %d polished, %d kept their polish",
        len(slugs), len(result.written), len(result.unchanged), len(result.deferred), len(result.failed), len(result.polished), len(result.carried),
    )
    if result.failed:
        report.warnings.append(f"commander guides failed: {', '.join(result.failed)}")
    return result.written


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


def publish_rules(directory: Path, report) -> list:
    """The Comprehensive Rules, read once: their keyword actions, keyword abilities and ability words as
    rules/keywords.json, and the whole book as rules/comprehensive.json.

    A file is not written when its rules are the same as the last run's, or when Wizards' site cannot be read or the
    file's part of the rules cannot be parsed: it stays published as it was, and the other file is still written. That
    is a warning, not an error, so the run passes.
    """
    if os.environ.get("KEYWORD_RULES", "1") != "1":
        return []
    from .rules import fetch, read_rules, write_comprehensive_rules, write_rules

    user_agent = os.environ.get("LOCATOR_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)")
    try:
        text, url = read_rules(lambda address: fetch(address, user_agent))
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Comprehensive Rules could not be read", exc_info=True)
        report.warnings.append(f"rules: {error}")
        return []
    now = datetime.now(timezone.utc)
    written = []
    for name, write in (("keyword rules", write_rules), ("comprehensive rules", write_comprehensive_rules)):
        try:
            written += write(directory, now, text, url)
        except Exception as error:  # noqa: BLE001 - the other file and the rest of the run still publish
            logging.warning("%s failed", name.capitalize(), exc_info=True)
            report.warnings.append(f"{name}: {error}")
    return written


def publish_set_art(directory: Path, report) -> list:
    """Wizards' art for each set, by Scryfall set code, as sets/art.json.

    Nothing is written when Wizards' sitemap or Scryfall's sets cannot be read: the file stays published as it was.
    That is a warning, not an error, so the run passes.
    """
    if os.environ.get("SET_ART", "1") != "1":
        return []
    from .setart import DELAY, USER_AGENT, Paced, fetch, scryfall_fetch, write_set_art

    agent = os.environ.get("SET_ART_USER_AGENT", USER_AGENT)
    get = Paced(lambda url, last_byte=None: fetch(url, last_byte, agent), float(os.environ.get("SET_ART_DELAY", str(DELAY))))
    try:
        return write_set_art(directory, datetime.now(timezone.utc), get, lambda url: scryfall_fetch(url, agent))
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Set art failed", exc_info=True)
        report.warnings.append(f"set art: {error}")
        return []


def publish_set_tints(directory: Path, report, data_url: str) -> list:
    """One tint colour for each set's icon tile, by Scryfall set code, as sets/tints.json.

    It reads sets/art.json from `directory` when `publish_set_art` wrote it this run, else the published file at `data_url`,
    so it runs after `publish_set_art`. Nothing is written when Scryfall's sets cannot be read: the file stays published as it was.
    That is a warning, not an error, so the run passes.
    """
    if os.environ.get("SET_TINTS", "1") != "1":
        return []
    try:
        from .settints import ART_PATH, DELAY, USER_AGENT, paced_get, write_set_tints

        get = paced_get(os.environ.get("SET_TINTS_USER_AGENT", USER_AGENT), float(os.environ.get("SET_TINTS_DELAY", str(DELAY))))
        return write_set_tints(directory, datetime.now(timezone.utc), get, f"{data_url}/{ART_PATH}")
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Set tints failed", exc_info=True)
        report.warnings.append(f"set tints: {error}")
        return []


def publish_set_products(directory: Path, report) -> list:
    """The sealed products of each recent set, by Scryfall set code, as sets/products/{code}.json.

    Nothing is written when TCGCSV or Scryfall's sets cannot be read: the files stay published as they were.
    That is a warning, not an error, so the run passes.
    """
    if os.environ.get("SET_PRODUCTS", "1") != "1":
        return []
    from .setart import Paced, Response, scryfall_fetch
    from .setproducts import DELAY, USER_AGENT, fetch, image_loads, write_set_products

    agent = os.environ.get("SET_PRODUCTS_USER_AGENT", USER_AGENT)
    paced = Paced(lambda url, last_byte=None: Response("", fetch(url, agent)), float(os.environ.get("SET_PRODUCTS_DELAY", str(DELAY))))
    try:
        return write_set_products(
            directory, datetime.now(timezone.utc), lambda url: paced(url).body, lambda url: scryfall_fetch(url, agent),
            lambda url: image_loads(url, agent),
        )
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Set products failed", exc_info=True)
        report.warnings.append(f"set products: {error}")
        return []


def publish_set_mechanics(directory: Path, report, data_url: str) -> list:
    """The mechanics each set introduced, by Scryfall set code, as sets/mechanics.json.

    It reads rules/keywords.json from `directory` when `publish_rules` wrote it this run, else the published file at `data_url`,
    so it runs after `publish_rules`. Nothing is written when Scryfall's cards, its catalogs or the rules cannot be read: the file
    stays published as it was. That is a warning, not an error, so the run passes.
    """
    if os.environ.get("SET_MECHANICS", "1") != "1":
        return []
    from .scryfall import DEFAULT_CARDS_URL, _bulk_download_uri, bulk_cards
    from .setmechanics import RULES_PATH, USER_AGENT, fetch, load_rules, write_set_mechanics

    agent = os.environ.get("SET_MECHANICS_USER_AGENT", USER_AGENT)
    try:
        return write_set_mechanics(
            directory, datetime.now(timezone.utc), bulk_cards(_bulk_download_uri(DEFAULT_CARDS_URL)), lambda url: fetch(url, agent),
            lambda: load_rules(directory, lambda url: fetch(url, agent), f"{data_url}/{RULES_PATH}"),
        )
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.warning("Set mechanics failed", exc_info=True)
        report.warnings.append(f"set mechanics: {error}")
        return []


def publish_movers(directory: Path, report, data_url: str, watch=None) -> list:
    """The cards whose price moved most, from the published price catalog, as movers/{format}.json.

    `watch` sees Scryfall's printings on the way (see `movers`).
    """
    if os.environ.get("MOVERS", "1") != "1":
        return []
    from .movers import movers

    try:
        files = movers(os.environ.get("MOVERS_PRICES_URL", f"{data_url}/catalog/prices/history.bin.gz"), datetime.now(timezone.utc), watch)
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Price movers failed")
        report.errors.append(f"price movers: {error}")
        return []
    (directory / "movers").mkdir(parents=True, exist_ok=True)
    for format, document in files.items():
        (directory / "movers" / f"{format}.json").write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return [f"movers/{format}.json" for format in files]


def publish_today(directory: Path, report, new_printings: Optional[NewPrintings] = None, catalog: Optional[dict] = None) -> list:
    """One response for Explore's Today widgets, from the breakouts and movers written above, as today.json.

    It also reads the EDHREC commander state and pages this run's `store.finish` wrote (`state/edhrec-commanders.json`,
    `edh/commanders/{slug}.json`) to find the uprising commander, and keeps its counts in `state/today-commanders.json`
    for the next run, so it runs after `finish`.

    `new_printings` is what the movers' read of Scryfall's printings found new, for its preview and for previews.json.
    `catalog` is the card catalog the run loaded, for the oracle ids of the commander and its cards.
    """
    from .today import write_today

    try:
        return write_today(directory, datetime.now(timezone.utc), new_printings, catalog)
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Today failed")
        report.errors.append(f"today: {error}")
        return []


def publish_localized(directory: Path, report) -> list:
    """The printed names and pictures of the cards in today.json and explore.json, as their `localized` map; it adds no files.

    It rewrites those two files, so it runs after the last step that writes them. A failure is a warning, not an
    error: the files stay as they were (or carry the last good run's cards, see `localized.localize`).
    """
    if os.environ.get("LOCALIZE", "1") != "1":
        return []
    from .localized import localize

    try:
        problems = localize(directory, os.environ.get("LOCALIZE_ALL_CARDS_URL") or None)
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Localized failed")
        report.warnings.append(f"localized: {error}")
        return []
    report.warnings.extend(problems)
    return []


def publish_manifest(directory: Path, report) -> list:
    """The SHA-256 of each Explore file written above or carried over from the last run, as explore-manifest.json."""
    from .manifest import write_manifest

    try:
        return write_manifest(directory, datetime.now(timezone.utc))
    except Exception as error:  # noqa: BLE001 - the rest of the run still publishes
        logging.exception("Explore manifest failed")
        report.errors.append(f"explore manifest: {error}")
        return []


def load_catalog(report: RunReport) -> dict:
    """Every card Magic has: oracle ids for the card pages, and the Commander rotation.

    A failure goes in the report and the run carries on without the catalog.
    """
    if os.environ.get("SCRYFALL_CATALOG", "1") != "1":
        return {}
    try:
        return card_catalog()
    except Exception as error:  # noqa: BLE001 - the run still publishes without it
        logging.exception("Could not read Scryfall's card catalog")
        report.errors.append(f"scryfall catalog: {error}")
        return {}


def exit_code(report: RunReport, blocked_runs: int) -> int:
    """1 when the run logged errors, or when MTGGoldfish blocked the deck downloads this run and the run before."""
    if report.errors:
        return 1
    if report.deck_block is not None and blocked_runs >= 2:
        report.errors.append(f"deck downloads blocked {blocked_runs} runs in a row: {report.deck_block}")
        return 1
    return 0


def main() -> int:
    if sys.argv[1:2] == ["clusters"]:
        from .clusters import main as clusters

        return clusters(sys.argv[2:])
    if sys.argv[1:2] == ["guides"]:
        from .guides import main as guides

        return guides(sys.argv[2:])
    if sys.argv[1:2] == ["primers"]:
        from .primers import main as primers

        return primers(sys.argv[2:])
    if sys.argv[1:2] == ["guide-combos"]:
        from .guide_combos import main as guide_combos

        return guide_combos(sys.argv[2:])
    if sys.argv[1:2] == ["set-art"]:
        from .setart import main as set_art

        return set_art(sys.argv[2:])
    if sys.argv[1:2] == ["set-tints"]:
        from .settints import main as set_tints

        return set_tints(sys.argv[2:])
    if sys.argv[1:2] == ["set-products"]:
        from .setproducts import main as set_products

        return set_products(sys.argv[2:])
    if sys.argv[1:2] == ["set-mechanics"]:
        from .setmechanics import main as set_mechanics

        return set_mechanics(sys.argv[2:])
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
        recheck_days=int(os.environ.get("RECHECK_DAYS", "7")),
        max_search_pages=int(os.environ.get("MAX_SEARCH_PAGES", "25")),
        history_days=int(os.environ.get("HISTORY_DAYS", "30")),
        max_archetype_pages=int(os.environ.get("MAX_ARCHETYPE_PAGES", "20")),
        # The decklists are paced like a reader: see pacing.py. CONCURRENCY and REQUEST_DELAY are for the other pages.
        deck_pacing=DeckPacing(
            concurrency=int(os.environ.get("DECK_CONCURRENCY", "2")),
            delay=float(os.environ.get("DECK_DELAY", "2")),
            minutes=float(os.environ.get("DECK_MINUTES", "40")),
            per_run=int(os.environ.get("DECKS_PER_RUN", "800")),
        ),
    )
    report = RunReport()
    catalog = load_catalog(report)
    store = SnapshotStore(args.directory, config.formats, config.history_days, catalog=catalog)
    headless = os.environ.get("HEADLESS", "0" if sys.platform.startswith("linux") else "1") == "1"
    with open_browser(
        headless=headless,
        delay=float(os.environ.get("REQUEST_DELAY", "1.5")),
        concurrency=int(os.environ.get("CONCURRENCY", "6")),
    ) as browser:
        scrape(browser, store, config, report=report)
    blocked_runs = note_deck_block(
        args.directory / "state" / "deck-downloads.json", report.deck_block is not None, report.deck_block, datetime.now(timezone.utc)
    )
    data_url = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")
    # EDHREC is read with their permission: a slice of the cards each run, at a low rate.
    edhrec = Edhrec(
        user_agent=os.environ.get("EDHREC_USER_AGENT", "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"),
        delay=float(os.environ.get("EDHREC_DELAY", "0.4")),
    )
    commander_limit = int(os.environ.get("EDHREC_COMMANDERS_PER_RUN", "150"))
    # Read first: the commanders it ranks go to the front of the commander refresh below, then those the last run's
    # top.json ranked at a bracket, a week apart.
    top = edhrec.top_commanders() if commander_limit > 0 else {}
    weekly = published_bracket_slugs(data_url) if commander_limit > 0 else []
    written = store.finish(
        fetch_decks=lambda ids: fetch_published_decks(data_url, ids),
        fetch_edh=edhrec.cards,
        edh_limit=int(os.environ.get("EDHREC_CARDS_PER_RUN", "800")),
        catalog=catalog,
        fetch_commanders=edhrec.commanders,
        commander_limit=commander_limit,
        deck_resolve_limit=int(os.environ.get("DECK_RESOLVE_PER_RUN", "300")),
        priority_commanders=top_slugs(top),
        weekly_commanders=weekly,
    )
    logging.info("Wrote %s", ", ".join(written) or "no snapshots")
    brackets = rank_brackets(args.directory, report, edhrec, top)
    written += publish_top(args.directory, report, top, catalog, brackets)
    written += publish_guides(args.directory, report, top, catalog, data_url, brackets)
    written += publish_locator(args.directory, report)
    written += publish_premier(args.directory, report)
    written += publish_rules(args.directory, report)
    written += publish_set_art(args.directory, report)
    written += publish_set_tints(args.directory, report, data_url)
    written += publish_set_products(args.directory, report)
    written += publish_set_mechanics(args.directory, report, data_url)
    # The printings the last run saw, so the movers' read of the default-cards file also finds the new ones for today.json's preview and previews.json.
    new_printings = NewPrintings(read_seen(args.directory), read_first_seen(args.directory), datetime.now(timezone.utc).date())
    written += publish_movers(args.directory, report, data_url, watch=new_printings.watch)
    written += publish_today(args.directory, report, new_printings, catalog)
    written += publish_localized(args.directory, report)
    # Last, after every file it lists.
    written += publish_manifest(args.directory, report)

    # Blocked deck downloads are a warning; two runs in a row fail the run (see exit_code).
    code = exit_code(report, blocked_runs)
    logging.info(
        "Done: %d meta, %d archetypes, %d events, %d decks written, %d already stored, %d decks left for the next run, %d errors",
        len(report.meta), len(report.archetypes), len(report.events), report.decks_written, report.decks_skipped,
        report.decks_deferred, len(report.errors),
    )
    for warning in report.warnings:
        logging.warning("%s", warning)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning::{warning}", flush=True)
    for error in report.errors:
        logging.error("  %s", error)
    # A partial run still publishes what it saved; the exit code flags the errors.
    return code


if __name__ == "__main__":
    sys.exit(main())
