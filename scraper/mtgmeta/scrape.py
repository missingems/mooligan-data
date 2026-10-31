"""Walks formats, archetypes, events and decklists, writing each record as soon as it is parsed."""
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple, Union

from .models import (
    Archetype,
    ArchetypeHistory,
    ArchetypeResult,
    Deck,
    Event,
    EventSummary,
    Meta,
    RunReport,
)
from .browser import BlockedError, Fetched
from .pacing import DeckPacing, Pacer, Visit, build_plan, deck_path, run_downloads
from .parsing import (
    event_kind,
    ParseError,
    parse_archetype,
    parse_archetype_decks,
    parse_decklist,
    parse_meta,
    parse_tournament,
    parse_tournament_list,
    parse_tournament_search,
)
from .store import Store

log = logging.getLogger(__name__)

_FALLBACK_NAME = re.compile(r"^Tournament \d+$")


class Browser(Protocol):
    def page(self, path: str) -> str: ...
    def metagame(self, format: str, days: str) -> Tuple[str, bool]: ...
    def fetch_pages(self, paths: Sequence[str]) -> Dict[str, Union[str, Exception]]: ...
    def fetch_batch(self, paths: Sequence[str]) -> List[Fetched]: ...


@dataclass
class ScrapeConfig:
    formats: Sequence[str] = (
        "modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "penny_dreadful", "duel_commander",
    )
    meta_days: Sequence[str] = ("30",)
    # The tournaments list only ever shows the latest 10; they are listings like the search's.
    events_per_format: int = 10
    # Pages of the tournament search read per format, 20 events each, newest
    # first, until the window is covered. Modern's 30 days is about 7 pages.
    max_search_pages: int = 25
    # Events not yet stored (from the search or archetype lists) read per format per run.
    max_new_events: int = 150
    # Events dated within this many days of the run are read again every run, stored or not.
    recheck_days: int = 7
    # Per format per run, for older events. Stored events whose name is the "Tournament <id>" fallback, or that a listing now
    # names differently or shows with more results, are read again.
    max_reread_events: int = 20
    # Per format. Decks never change once published, so each run only downloads
    # new ones; the cap keeps one format's backlog from starving the others.
    max_new_decks: int = 400
    # How the downloads move, and how many a run may take in all formats together.
    deck_pacing: DeckPacing = field(default_factory=DeckPacing)
    # Archetypes per format, most played first, whose results and featured deck are kept.
    archetype_decks: int = 100
    # How far back each archetype's results go.
    history_days: int = 30
    # Pages of 50 decks read per archetype per run. A first run needs about one
    # page per 50 decks in the history window; later runs usually need one.
    max_archetype_pages: int = 20


@dataclass
class _WantedDeck:
    deck_id: str
    date: datetime
    player: str
    archetype: str
    format: str
    event_id: Optional[str]
    archetype_id: Optional[str] = None


def scrape(
    browser: Browser,
    store: Store,
    config: ScrapeConfig,
    now: Optional[datetime] = None,
    pacer: Optional[Pacer] = None,
    report: Optional[RunReport] = None,
) -> RunReport:
    """Reads every format, then downloads the new decks. Adds to `report` when the caller already has one."""
    report = report or RunReport()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config.history_days)
    wanted: Dict[str, List[_WantedDeck]] = {}
    for format in config.formats:
        metas = _read_metas(browser, format, config.meta_days, report)
        histories = _read_archetypes(browser, store, format, _ranked_archetypes(metas)[: config.archetype_decks], config, cutoff, report)
        featured = {history.archetype_id: history.deck_id for history in histories if history.deck_id}
        for meta in metas:
            for archetype in meta.archetypes:
                archetype.deck_id = featured.get(archetype.id)
            if _save(report, f"meta {meta.doc_id}", lambda: store.save_meta(meta)):
                report.meta.append(meta.doc_id)

        # Every deck of a tracked archetype, so event results can use the archetype's name.
        canonical: Dict[str, Tuple[str, str]] = {
            result.deck_id: (history.name, history.archetype_id) for history in histories for result in history.results
        }
        events = _read_events(browser, store, format, histories, config, report, cutoff, now or datetime.now(timezone.utc))
        for event in events:
            for result in event.results:
                if result.deck_id in canonical:
                    result.archetype, result.archetype_id = canonical[result.deck_id]
            if _save(report, f"event {event.event_id}", lambda: store.save_event(event)):
                report.events.append(event.event_id)
        wanted[format] = _wanted_decks(format, histories, events)
    if config.formats and config.meta_days and not report.meta:
        # One format's windows failing is a warning; none read in any format means the pages changed or are blocked.
        report.errors.append(f"meta: no window read in any of {len(config.formats)} formats")

    # The decks come last, once every format's pages are read, so the pace is set by the deck phase alone.
    _download_decks(browser, store, wanted, config, report, pacer)
    return report


def _read_metas(browser: Browser, format: str, meta_days: Sequence[str], report: RunReport) -> List[Meta]:
    """The format's metagame windows that could be read.

    A window that cannot be read is a warning, not an error: the snapshot keeps the last one read, with its own
    last_updated, and the other formats publish as usual.
    """
    metas = []
    for days in meta_days:
        try:
            meta, windowed = _read_meta(browser, format, days)
        except Exception as error:  # noqa: BLE001 - one failed window must not stop the run, or fail it
            log.warning("Could not read meta %s %sd", format, days, exc_info=True)
            report.warnings.append(f"meta {format} {days}d: {error} (the snapshot keeps the last {days}d window read)")
            continue
        log.info("Read meta %s (%d archetypes)", meta.doc_id, len(meta.archetypes))
        metas.append(meta)
        if not windowed:
            # One unwindowed page: publishing it again under other windows would repeat it.
            log.info("The %s metagame has one window only; skipping %s", format, ", ".join(meta_days[1:]))
            break
    return metas


def _read_meta(browser: Browser, format: str, days: str) -> Tuple[Meta, bool]:
    """One metagame window, loaded once more after a browser error such as a hung script or a switch that never came.

    A page that loads but has no tiles is not loaded again: it would show the same. Nor is a blocked one, which
    has had its attempts already.
    """
    try:
        html, windowed = browser.metagame(format, days)
    except BlockedError:
        raise
    except Exception:  # noqa: BLE001 - Modern's 14 days on 16 October 2026 hung once, then read fine on the next run
        log.warning("Could not read meta %s %sd; loading it again", format, days, exc_info=True)
        html, windowed = browser.metagame(format, days)
    return parse_meta(html, format, f"{days}d"), windowed


def _ranked_archetypes(metas: List[Meta]) -> List[Archetype]:
    """Every archetype in any window, once, most played first."""
    best: Dict[str, Archetype] = {}
    for meta in metas:
        for archetype in meta.archetypes:
            if archetype.id not in best or archetype.percentage > best[archetype.id].percentage:
                best[archetype.id] = archetype
    return sorted(best.values(), key=lambda archetype: archetype.percentage, reverse=True)


def _read_archetypes(
    browser: Browser,
    store: Store,
    format: str,
    archetypes: List[Archetype],
    config: ScrapeConfig,
    cutoff: datetime,
    report: RunReport,
) -> List[ArchetypeHistory]:
    featured_pages = browser.fetch_pages([f"/archetype/{archetype.id}" for archetype in archetypes])
    fresh, failed = _new_archetype_results(browser, store, format, archetypes, cutoff, config.max_archetype_pages, report)
    histories = []
    for archetype in archetypes:
        if archetype.id in failed:
            continue
        featured = None
        try:
            featured = parse_archetype(_body(featured_pages[f"/archetype/{archetype.id}"]), archetype.id)
        except ParseError as error:
            # A catch-all archetype such as "Other" has no featured deck of its own.
            log.info("No featured deck for %s: %s", archetype.id, error)
        except Exception as error:  # noqa: BLE001
            _fail(report, f"archetype {archetype.id}", error)
        known = store.load_archetype_results(format, archetype.id)
        fresh_ids = {result.deck_id for result in fresh[archetype.id]}
        # A stable sort keeps MTGGoldfish's order among decks of the same day.
        results = sorted(
            (result for result in fresh[archetype.id] + [r for r in known if r.deck_id not in fresh_ids] if result.date >= cutoff),
            key=lambda result: result.date,
            reverse=True,
        )
        history = ArchetypeHistory(
            format=format,
            archetype_id=archetype.id,
            name=archetype.name,
            deck_id=featured.deck_id if featured else None,
            featured_player=featured.player if featured else None,
            # Bounds the snapshot's size if an archetype takes over the format.
            results=results[:3000],
        )
        if _save(report, f"archetype {history.doc_id}", lambda: store.save_archetype(history)):
            report.archetypes.append(history.doc_id)
            log.info("Saved archetype %s (%d results, %d new)", history.doc_id, len(results), len(fresh[archetype.id]))
        histories.append(history)
    return histories


def _new_archetype_results(
    browser: Browser,
    store: Store,
    format: str,
    archetypes: List[Archetype],
    cutoff: datetime,
    max_pages: int,
    report: RunReport,
) -> Tuple[Dict[str, List[ArchetypeResult]], set]:
    """Reads every archetype's deck pages a page number at a time, all archetypes together.

    An archetype stops once a page holds nothing new or reaches past the cutoff.
    Returns the new rows per archetype, and the archetypes whose pages failed.
    """
    ignored = store.ignored_event_ids()
    known = {a.id: {r.deck_id for r in store.load_archetype_results(format, a.id)} for a in archetypes}
    fresh: Dict[str, List[ArchetypeResult]] = {a.id: [] for a in archetypes}
    failed = set()
    active = [a.id for a in archetypes]
    for page in range(1, max_pages + 1):
        if not active:
            break
        pages = browser.fetch_pages([f"/archetype/{archetype_id}/decks?page={page}" for archetype_id in active])
        still_active = []
        for archetype_id in active:
            try:
                rows, has_next = parse_archetype_decks(_body(pages[f"/archetype/{archetype_id}/decks?page={page}"]), archetype_id)
            except Exception as error:  # noqa: BLE001
                _fail(report, f"archetype decks {archetype_id} page {page}", error)
                failed.add(archetype_id)
                continue
            new_rows = [
                row for row in rows if row.deck_id not in known[archetype_id] and row.event_id not in ignored and row.date >= cutoff
            ]
            fresh[archetype_id].extend(new_rows)
            # Rows are newest first, but an event can be posted days late, so a
            # page is only "caught up" once none of its rows are new.
            if new_rows and has_next and not (rows and rows[-1].date < cutoff):
                still_active.append(archetype_id)
        active = still_active
    return fresh, failed


def _read_events(
    browser: Browser,
    store: Store,
    format: str,
    histories: List[ArchetypeHistory],
    config: ScrapeConfig,
    report: RunReport,
    cutoff: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> List[Event]:
    try:
        latest = parse_tournament_list(browser.page(f"/tournaments/{format}"))[: config.events_per_format]
    except Exception as error:  # noqa: BLE001
        _fail(report, f"tournaments {format}", error)
        latest = []

    ignored = store.ignored_event_ids()
    stored_events = {summary.event_id: summary for summary in store.stored_events(format)}
    # Every event of the format in the window, from the tournament search: the
    # only listing that goes past the latest ten, and the one that has the Pro
    # Tours, Regional Championships and RCQs.
    searched = _search_events(browser, format, cutoff, now, config.max_search_pages, report) if cutoff and now else []
    # The search comes first for the decklist count it gives.
    listed: Dict[str, EventSummary] = {}
    for summary in searched + latest:
        listed.setdefault(summary.event_id, summary)
    # Plus the events the archetype lists mention, which cover multi-format events.
    for history in histories:
        for result in history.results:
            if result.event_id:
                listed.setdefault(result.event_id, EventSummary(result.event_id, result.event_name, result.date))
    # Listed, but nothing to read.
    listed = {
        event_id: summary
        for event_id, summary in listed.items()
        if event_id not in ignored and (summary.decklists != 0 or event_id in stored_events)
    }
    anywhere = store.existing_event_ids(listed)

    # Everything dated within the last few days is read again, stored or not, since results keep arriving.
    horizon = (now or datetime.now(timezone.utc)) - timedelta(days=config.recheck_days)
    recheck: Dict[str, EventSummary] = {
        event_id: summary
        for event_id, summary in listed.items()
        if (event_id in stored_events or event_id not in anywhere) and (summary.date is None or summary.date >= horizon)
    }
    for event_id, kept in stored_events.items():
        if event_id not in ignored and event_id not in recheck and kept.date >= horizon:
            recheck[event_id] = EventSummary(event_id, "", kept.date)
    recent = sorted(recheck.values(), key=lambda s: s.date or datetime.max.replace(tzinfo=timezone.utc), reverse=True)

    older = sorted(
        (s for event_id, s in listed.items() if event_id not in recheck and event_id not in anywhere),
        key=lambda s: s.date or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if len(older) > config.max_new_events:
        log.info("%d older %s events wait for the next run", len(older) - config.max_new_events, format)
    # Stored events read before their source was kept are re-read with whatever room is left.
    room = max(config.max_new_events - len(older), 0)
    seen = set(recheck) | ignored
    reread = _events_to_reread(stored_events, listed, seen, cutoff)[: config.max_reread_events]
    taken = seen | {summary.event_id for summary in reread}
    refresh = [EventSummary(event_id, "", None) for event_id in store.events_missing_source(format) if event_id not in taken][:room]

    summaries = recent + older[: config.max_new_events] + reread + refresh
    pages = browser.fetch_pages([f"/tournament/{summary.event_id}" for summary in summaries])
    events = []
    empty = []
    for summary in summaries:
        try:
            html = _body(pages[f"/tournament/{summary.event_id}"])
            event = parse_tournament(html, summary.event_id, format, summary)
            kept = stored_events.get(summary.event_id)
            if _FALLBACK_NAME.match(event.event_name) and kept and not _FALLBACK_NAME.match(kept.event_name):
                event.event_name = kept.event_name
                event.kind = event_kind(kept.event_name, event.source)
            log.info("Read event %s %s (%d results)", event.event_id, event.event_name, len(event.results))
            events.append(event)
        except ParseError as error:
            # An event with no decklists has no results table; there is nothing to come back for.
            log.info("Event %s has nothing to read: %s", summary.event_id, error)
            empty.append(summary.event_id)
        except Exception as error:  # noqa: BLE001
            _fail(report, f"event {summary.event_id}", error)
    if empty:
        store.mark_empty_events(empty)
    return events


def _events_to_reread(
    stored: Dict[str, EventSummary], listed: Dict[str, EventSummary], skip: Set[str], cutoff: Optional[datetime]
) -> List[EventSummary]:
    """Stored events in the window that were read badly or have changed, newest first.

    Each comes with its listing's summary when there is one, so its name can come from there.
    """
    found = []
    for event_id, kept in stored.items():
        if event_id in skip or (cutoff and kept.date < cutoff):
            continue
        listing = listed.get(event_id)
        named = listing is not None and bool(listing.event_name) and not _FALLBACK_NAME.match(listing.event_name)
        renamed = named and listing.event_name != kept.event_name
        grown = listing is not None and (listing.decklists or 0) > (kept.decklists or 0)
        if _FALLBACK_NAME.match(kept.event_name) or renamed or grown:
            found.append(listing if named else EventSummary(event_id, "", kept.date))
    return sorted(found, key=lambda summary: summary.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def _search_events(
    browser: Browser, format: str, cutoff: datetime, now: datetime, max_pages: int, report: RunReport
) -> List[EventSummary]:
    """Walks the tournament search for the format, newest first, until it reaches the cutoff."""
    query = urlencode(
        {
            "tournament_search[name]": "",
            "tournament_search[format]": format,
            "tournament_search[date_range]": f"{cutoff:%m/%d/%Y} - {now:%m/%d/%Y}",
            "commit": "Search",
        }
    )
    found: List[EventSummary] = []
    for page in range(1, max_pages + 1):
        path = f"/tournament_searches/create?{query}&page={page}"
        try:
            events, has_next = parse_tournament_search(_body(browser.fetch_pages([path])[path]))
        except Exception as error:  # noqa: BLE001
            _fail(report, f"tournament search {format} page {page}", error)
            break
        found.extend(event for event in events if event.date is None or event.date >= cutoff)
        if not has_next or not events or (events[-1].date and events[-1].date < cutoff):
            break
    log.info("Tournament search: %d %s events in the window", len(found), format)
    return found


def _wanted_decks(format: str, histories: List[ArchetypeHistory], events: List[Event]) -> List[_WantedDeck]:
    """Featured decks first, then every result, newest first."""
    wanted: Dict[str, _WantedDeck] = {}
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    for history in histories:
        if history.deck_id:
            wanted[history.deck_id] = _WantedDeck(
                history.deck_id, far_future, history.featured_player or "", history.name, format, None, history.archetype_id
            )
    for history in histories:
        for result in history.results:
            wanted.setdefault(
                result.deck_id,
                _WantedDeck(
                    result.deck_id, result.date, result.player, history.name, format, result.event_id, history.archetype_id
                ),
            )
    for event in events:
        for result in event.results:
            wanted.setdefault(
                result.deck_id,
                _WantedDeck(
                    result.deck_id, event.date, result.player, result.archetype, format, event.event_id, result.archetype_id
                ),
            )
    return sorted(wanted.values(), key=lambda deck: deck.date, reverse=True)


def _download_decks(
    browser: Browser,
    store: Store,
    wanted: Dict[str, List[_WantedDeck]],
    config: ScrapeConfig,
    report: RunReport,
    pacer: Optional[Pacer] = None,
) -> None:
    """Downloads the new decks of every format the way a reader would, saving each batch as it comes."""
    everything = [want for decks in wanted.values() for want in decks]
    existing = store.existing_deck_ids(want.deck_id for want in everything)
    report.decks_skipped += len(existing)
    gone = store.missing_deck_ids()
    allowance = max(config.max_new_decks, 0)
    # Each format has its own allowance, so one big backlog can't starve the others.
    todo: Dict[str, List[_WantedDeck]] = {}
    chosen: Set[str] = set()
    over_allowance = 0
    for format, decks in wanted.items():
        fresh = [want for want in decks if want.deck_id not in existing and want.deck_id not in gone and want.deck_id not in chosen]
        todo[format] = fresh[:allowance]
        chosen.update(want.deck_id for want in todo[format])
        if len(fresh) > allowance:
            over_allowance += len(fresh) - allowance
            log.info("%d %s decks wait past the limit of %d new decks a format; they come next run", len(fresh) - allowance, format, allowance)
    if not chosen:
        return

    pacer = pacer or Pacer(config.deck_pacing, random.Random())
    plan = build_plan(todo, pacer.pacing, pacer.rng)
    planned = sum(len(visit.decks) for visit in plan)
    over_run = len(chosen) - planned
    if over_run:
        log.info("%d decks wait past the limit of %d new decks a run; they come next run", over_run, pacer.pacing.per_run)
    by_path = {deck_path(want.deck_id): want for decks in todo.values() for want in decks}
    missing: List[str] = []

    def handle(visit: Visit, fetched: List[Fetched]) -> None:
        pending: List[Deck] = []
        for answer in fetched:
            want = by_path[answer.path]
            if answer.status != 200:
                # Not inside an except, so logged without a traceback.
                log.error("Failed on deck %s: HTTP %d", want.deck_id, answer.status)
                report.errors.append(f"deck {want.deck_id}: HTTP {answer.status} on {answer.path}")
                continue
            try:
                mainboard, sideboard = parse_decklist(answer.body)
            except ParseError:
                # MTGGoldfish redirects a deleted deck to its metagame page.
                log.info("Deck %s is no longer on MTGGoldfish", want.deck_id)
                missing.append(want.deck_id)
                continue
            pending.append(
                Deck(want.deck_id, want.player, want.archetype, mainboard, sideboard, want.format, want.event_id, want.archetype_id)
            )
        _flush_decks(store, pending, report)

    outcome = run_downloads(browser, plan, pacer, handle)
    if missing:
        store.mark_missing_decks(missing)
        log.info("%d decks are no longer on MTGGoldfish; later runs skip them", len(missing))

    report.decks_deferred = over_allowance + over_run + outcome.left
    minutes = pacer.elapsed() / 60
    if outcome.reason == "blocked":
        report.deck_block = outcome.refusal
        warning = (
            f"Deck downloads blocked after {outcome.downloaded_attempted} ({outcome.refusal}); "
            f"{report.decks_deferred} left for the next run"
        )
        report.warnings.append(warning)
    elif outcome.reason == "time":
        log.info(
            "Deck downloads stopped at the %.0f-minute budget after %d; %d left for the next run",
            pacer.pacing.minutes, outcome.downloaded_attempted, report.decks_deferred,
        )
    else:
        log.info("Downloaded %d new decks in %.0f min; %d wait for the next run", report.decks_written, minutes, report.decks_deferred)


def _body(result: Union[str, Exception]) -> str:
    if isinstance(result, Exception):
        raise result
    return result


def _flush_decks(store: Store, pending: List[Deck], report: RunReport) -> None:
    if not pending:
        return
    if _save(report, f"{len(pending)} decks", lambda: store.save_decks(pending)):
        report.decks_written += len(pending)
        log.info("Saved %d decks", len(pending))
    pending.clear()


def _save(report: RunReport, what: str, write) -> bool:
    try:
        write()
        return True
    except Exception as error:  # noqa: BLE001
        _fail(report, f"saving {what}", error)
        return False


def _fail(report: RunReport, what: str, error: Exception) -> None:
    log.exception("Failed on %s", what)
    report.errors.append(f"{what}: {error}")
