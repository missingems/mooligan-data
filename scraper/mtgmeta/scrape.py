"""Walks formats, archetypes, events and decklists, writing each record as soon as it is parsed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, Union

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
from .parsing import (
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


class Browser(Protocol):
    def page(self, path: str) -> str: ...
    def metagame(self, format: str, days: str) -> Tuple[str, bool]: ...
    def fetch_pages(self, paths: Sequence[str]) -> Dict[str, Union[str, Exception]]: ...


@dataclass
class ScrapeConfig:
    formats: Sequence[str] = (
        "modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "penny_dreadful", "duel_commander",
    )
    meta_days: Sequence[str] = ("30",)
    # The tournaments list only ever shows the latest 10.
    events_per_format: int = 10
    # Pages of the tournament search read per format, 20 events each, newest
    # first, until the window is covered. Modern's 30 days is about 7 pages.
    max_search_pages: int = 25
    # Events not yet stored (from the search or archetype lists) read per format per run.
    max_new_events: int = 150
    # Per format. Decks never change once published, so each run only downloads
    # new ones; the cap keeps a first run (or a backlog) from hammering the site.
    max_new_decks: int = 400
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


def scrape(browser: Browser, store: Store, config: ScrapeConfig, now: Optional[datetime] = None) -> RunReport:
    report = RunReport()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config.history_days)
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

        # Each format has its own allowance, so one big backlog can't starve the others.
        left = _download_decks(browser, store, _wanted_decks(format, histories, events), config.max_new_decks, report)
        if left <= 0:
            log.warning("Stopped %s at the limit of %d new decks; the rest come next run", format, config.max_new_decks)
    return report


def _read_metas(browser: Browser, format: str, meta_days: Sequence[str], report: RunReport) -> List[Meta]:
    metas = []
    for days in meta_days:
        try:
            html, windowed = browser.metagame(format, days)
            meta = parse_meta(html, format, f"{days}d")
            log.info("Read meta %s (%d archetypes)", meta.doc_id, len(meta.archetypes))
            metas.append(meta)
            if not windowed:
                # One unwindowed page: publishing it again under other windows would repeat it.
                log.info("The %s metagame has one window only; skipping %s", format, ", ".join(meta_days[1:]))
                break
        except Exception as error:  # noqa: BLE001 - one failed page must not stop the run
            _fail(report, f"meta {format} {days}d", error)
    return metas


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
        recent = parse_tournament_list(browser.page(f"/tournaments/{format}"))[: config.events_per_format]
    except Exception as error:  # noqa: BLE001
        _fail(report, f"tournaments {format}", error)
        recent = []

    ignored = store.ignored_event_ids()
    recent = [summary for summary in recent if summary.event_id not in ignored]
    seen = {summary.event_id for summary in recent} | ignored

    # Every event of the format in the window, from the tournament search: the
    # only listing that goes past the latest ten, and the one that has the Pro
    # Tours, Regional Championships and RCQs.
    candidates: Dict[str, EventSummary] = {}
    if cutoff and now:
        for summary in _search_events(browser, format, cutoff, now, config.max_search_pages, report):
            if summary.event_id not in seen:
                candidates.setdefault(summary.event_id, summary)
    # Plus the events the archetype lists mention, which cover multi-format events.
    for history in histories:
        for result in history.results:
            if result.event_id and result.event_id not in seen:
                candidates.setdefault(result.event_id, EventSummary(result.event_id, result.event_name, result.date))
    stored = store.existing_event_ids(candidates) if candidates else set()
    older = sorted(
        (s for s in candidates.values() if s.event_id not in stored),
        key=lambda s: s.date or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if len(older) > config.max_new_events:
        log.info("%d older %s events wait for the next run", len(older) - config.max_new_events, format)

    summaries = recent + older[: config.max_new_events]
    pages = browser.fetch_pages([f"/tournament/{summary.event_id}" for summary in summaries])
    events = []
    for summary in summaries:
        try:
            html = _body(pages[f"/tournament/{summary.event_id}"])
            event = parse_tournament(html, summary.event_id, format, summary)
            log.info("Read event %s %s (%d results)", event.event_id, event.event_name, len(event.results))
            events.append(event)
        except Exception as error:  # noqa: BLE001
            _fail(report, f"event {summary.event_id}", error)
    return events


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


def _download_decks(browser: Browser, store: Store, wanted: List[_WantedDeck], budget: int, report: RunReport) -> int:
    existing = store.existing_deck_ids(deck.deck_id for deck in wanted)
    report.decks_skipped += len(existing)
    gone = store.missing_deck_ids()
    todo = [want for want in wanted if want.deck_id not in existing and want.deck_id not in gone][: max(budget, 0)]
    missing: List[str] = []
    # Downloaded in chunks and saved after each, so a crash or timeout keeps what was fetched.
    for start in range(0, len(todo), 50):
        chunk = todo[start : start + 50]
        texts = browser.fetch_pages([f"/deck/download/{want.deck_id}" for want in chunk])
        pending: List[Deck] = []
        for want in chunk:
            try:
                mainboard, sideboard = parse_decklist(_body(texts[f"/deck/download/{want.deck_id}"]))
            except ParseError:
                # MTGGoldfish redirects a deleted deck to its metagame page.
                log.info("Deck %s is no longer on MTGGoldfish", want.deck_id)
                missing.append(want.deck_id)
                continue
            except Exception as error:  # noqa: BLE001
                _fail(report, f"deck {want.deck_id}", error)
                continue
            budget -= 1
            pending.append(
                Deck(
                    want.deck_id, want.player, want.archetype, mainboard, sideboard, want.format, want.event_id, want.archetype_id
                )
            )
        _flush_decks(store, pending, report)
    if missing:
        store.mark_missing_decks(missing)
        log.info("%d decks are no longer on MTGGoldfish; later runs skip them", len(missing))
    return budget


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
