"""Walks formats, archetypes, events and decklists, writing each record as soon as it is parsed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

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
    parse_archetype,
    parse_archetype_decks,
    parse_decklist,
    parse_meta,
    parse_tournament,
    parse_tournament_list,
)
from .store import Store

log = logging.getLogger(__name__)


class Browser(Protocol):
    def page(self, path: str) -> str: ...
    def metagame(self, format: str, days: str) -> str: ...
    def deck_text(self, deck_id: str) -> str: ...


@dataclass
class ScrapeConfig:
    formats: Sequence[str] = ("modern", "standard", "pioneer")
    meta_days: Sequence[str] = ("30",)
    # The tournaments list only ever shows the latest 10.
    events_per_format: int = 10
    # Older events found through archetype deck lists, read per format per run.
    max_new_events: int = 60
    # Decks never change once published, so each run only downloads new ones;
    # the cap keeps a first run (or a backlog) from hammering the site.
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


def scrape(browser: Browser, store: Store, config: ScrapeConfig, now: Optional[datetime] = None) -> RunReport:
    report = RunReport()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config.history_days)
    deck_budget = config.max_new_decks
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
        events = _read_events(browser, store, format, histories, config, report)
        for event in events:
            for result in event.results:
                if result.deck_id in canonical:
                    result.archetype, result.archetype_id = canonical[result.deck_id]
            if _save(report, f"event {event.event_id}", lambda: store.save_event(event)):
                report.events.append(event.event_id)

        wanted = _wanted_decks(format, histories, events)
        deck_budget = _download_decks(browser, store, wanted, deck_budget, report)
    if deck_budget <= 0:
        log.warning("Stopped at the limit of %d new decks; the rest come next run", config.max_new_decks)
    return report


def _read_metas(browser: Browser, format: str, meta_days: Sequence[str], report: RunReport) -> List[Meta]:
    metas = []
    for days in meta_days:
        try:
            meta = parse_meta(browser.metagame(format, days), format, f"{days}d")
            log.info("Read meta %s (%d archetypes)", meta.doc_id, len(meta.archetypes))
            metas.append(meta)
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
    histories = []
    for archetype in archetypes:
        try:
            featured = parse_archetype(browser.page(f"/archetype/{archetype.id}"), archetype.id)
        except Exception as error:  # noqa: BLE001
            _fail(report, f"archetype {archetype.id}", error)
            featured = None
        try:
            known = store.load_archetype_results(format, archetype.id)
            fresh = _new_archetype_results(
                browser, archetype.id, {r.deck_id for r in known}, store.ignored_event_ids(), cutoff, config.max_archetype_pages
            )
        except Exception as error:  # noqa: BLE001
            _fail(report, f"archetype decks {archetype.id}", error)
            continue
        fresh_ids = {result.deck_id for result in fresh}
        # A stable sort keeps MTGGoldfish's order among decks of the same day.
        results = sorted(
            (result for result in fresh + [r for r in known if r.deck_id not in fresh_ids] if result.date >= cutoff),
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
            log.info("Saved archetype %s (%d results, %d new)", history.doc_id, len(results), len(fresh))
        histories.append(history)
    return histories


def _new_archetype_results(
    browser: Browser, archetype_id: str, known: set, ignored_events: set, cutoff: datetime, max_pages: int
) -> List[ArchetypeResult]:
    """Reads the archetype's deck pages until a page holds nothing new or reaches past the cutoff."""
    fresh: List[ArchetypeResult] = []
    for page in range(1, max_pages + 1):
        rows, has_next = parse_archetype_decks(browser.page(f"/archetype/{archetype_id}/decks?page={page}"), archetype_id)
        new_rows = [
            row for row in rows if row.deck_id not in known and row.event_id not in ignored_events and row.date >= cutoff
        ]
        fresh.extend(new_rows)
        # Rows are newest first, but an event can be posted days late, so a
        # page is only "caught up" once none of its rows are new.
        if not new_rows or not has_next or (rows and rows[-1].date < cutoff):
            break
    return fresh


def _read_events(
    browser: Browser, store: Store, format: str, histories: List[ArchetypeHistory], config: ScrapeConfig, report: RunReport
) -> List[Event]:
    try:
        recent = parse_tournament_list(browser.page(f"/tournaments/{format}"))[: config.events_per_format]
    except Exception as error:  # noqa: BLE001
        _fail(report, f"tournaments {format}", error)
        recent = []

    # Events the archetype lists mention but that are not stored yet, newest first.
    ignored = store.ignored_event_ids()
    recent = [summary for summary in recent if summary.event_id not in ignored]
    seen = {summary.event_id for summary in recent} | ignored
    mentioned: Dict[str, EventSummary] = {}
    for history in histories:
        for result in history.results:
            if result.event_id and result.event_id not in seen and result.event_id not in mentioned:
                mentioned[result.event_id] = EventSummary(result.event_id, result.event_name, result.date)
    stored = store.existing_event_ids(mentioned) if mentioned else set()
    older = sorted((s for s in mentioned.values() if s.event_id not in stored), key=lambda s: s.date, reverse=True)

    events = []
    for summary in recent + older[: config.max_new_events]:
        try:
            event = parse_tournament(browser.page(f"/tournament/{summary.event_id}"), summary.event_id, format, summary)
            log.info("Read event %s %s (%d results)", event.event_id, event.event_name, len(event.results))
            events.append(event)
        except Exception as error:  # noqa: BLE001
            _fail(report, f"event {summary.event_id}", error)
    if len(older) > config.max_new_events:
        log.info("%d older %s events wait for the next run", len(older) - config.max_new_events, format)
    return events


def _wanted_decks(format: str, histories: List[ArchetypeHistory], events: List[Event]) -> List[_WantedDeck]:
    """Featured decks first, then every result, newest first."""
    wanted: Dict[str, _WantedDeck] = {}
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    for history in histories:
        if history.deck_id:
            wanted[history.deck_id] = _WantedDeck(
                history.deck_id, far_future, history.featured_player or "", history.name, format, None
            )
    for history in histories:
        for result in history.results:
            wanted.setdefault(
                result.deck_id,
                _WantedDeck(result.deck_id, result.date, result.player, history.name, format, result.event_id),
            )
    for event in events:
        for result in event.results:
            wanted.setdefault(
                result.deck_id,
                _WantedDeck(result.deck_id, event.date, result.player, result.archetype, format, event.event_id),
            )
    return sorted(wanted.values(), key=lambda deck: deck.date, reverse=True)


def _download_decks(browser: Browser, store: Store, wanted: List[_WantedDeck], budget: int, report: RunReport) -> int:
    existing = store.existing_deck_ids(deck.deck_id for deck in wanted)
    report.decks_skipped += len(existing)
    pending: List[Deck] = []
    for want in wanted:
        if want.deck_id in existing:
            continue
        if budget <= 0:
            break
        try:
            mainboard, sideboard = parse_decklist(browser.deck_text(want.deck_id))
        except Exception as error:  # noqa: BLE001
            _fail(report, f"deck {want.deck_id}", error)
            continue
        budget -= 1
        pending.append(Deck(want.deck_id, want.player, want.archetype, mainboard, sideboard, want.format, want.event_id))
        # Save in small batches so a crash or timeout keeps what was downloaded.
        if len(pending) >= 25:
            _flush_decks(store, pending, report)
    _flush_decks(store, pending, report)
    return budget


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
