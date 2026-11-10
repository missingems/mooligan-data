"""Reads mtgo.com's decklists and MTGTop8's events, names the decks, and builds the metagame from what is stored."""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple
from urllib.parse import urlsplit

from . import mtgo, mtgtop8
from .http import Fetched, is_refusal
from .models import Archetype, ArchetypeHistory, ArchetypeResult, Deck, Event, EventResult, Meta, RunReport
from .naming import name_event, name_from_top8
from .parsing import ParseError, event_kind, parse_decklist, place
from .store import Store

log = logging.getLogger(__name__)

MTGO_HOST = urlsplit(mtgo.BASE_URL).hostname
TOP8_HOST = urlsplit(mtgtop8.BASE_URL).hostname
WINDOWS = (7, 14, 30)
DECK_ATTEMPTS = 2
LEAGUE_PLACE = 9

_SIZE = re.compile(r"\b(16|32|64)\b")


class Client(Protocol):
    refusals: Dict[str, str]

    def get(self, url: str) -> Optional[Fetched]: ...
    def budget_left(self) -> bool: ...
    def stopped(self, host: str) -> bool: ...


@dataclass
class ScrapeConfig:
    formats: Sequence[str] = ("modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "duel_commander")
    history_days: int = 30
    max_mtgtop8_pages: int = 10
    top8_lag_days: int = 2


def scrape(
    client: Client,
    store: Store,
    config: ScrapeConfig,
    now: Optional[datetime] = None,
    report: Optional[RunReport] = None,
    catalog: Optional[Dict[str, dict]] = None,
) -> RunReport:
    """Reads the new mtgo.com events and MTGTop8's paper events of every format, then builds each format's metagame.

    Adds to `report` when the caller already has one.
    """
    report = report or RunReport()
    run = _Run(client, store, config, now or datetime.now(timezone.utc), report, catalog or {})
    formats = [format for format in config.formats if _supported(format)]
    for format in formats:
        run.mtgo_events(format)
    for format in formats:
        run.paper_events(format)
    for format in formats:
        run.metagame(format)
    for host, detail in client.refusals.items():
        if host in client.refused:
            report.warnings.append(f"{host} refused requests ({detail}); the run kept what it had read")
        else:
            report.warnings.append(f"{host} failed twice in a row ({detail}); the run kept what it had read")
    if client.refusals:
        report.deck_block = "; ".join(f"{host}: {detail}" for host, detail in client.refusals.items())
    log.info(
        "Named %d decks by MTGTop8, %d by lists and %d by colours",
        report.named_by_top8, report.named_by_lists, report.named_by_colors,
    )
    if not client.budget_left():
        log.info("The time budget ended the run; what is left comes next run")
    return report


def _supported(format: str) -> bool:
    if format in mtgo.MTGO_FORMATS and format in mtgtop8.FORMAT_CODES:
        return True
    log.warning("%s is on neither mtgo.com nor MTGTop8; skipped", format)
    return False


class _Run:
    def __init__(
        self, client: Client, store: Store, config: ScrapeConfig, now: datetime, report: RunReport, catalog: Dict[str, dict]
    ) -> None:
        self.client = client
        self.store = store
        self.config = config
        self.now = now
        self.report = report
        self.catalog = catalog
        self.cutoff = now - timedelta(days=config.history_days)
        self.months: Dict[Tuple[int, int], Optional[List[mtgo.EventRef]]] = {}
        self.top8_events: Dict[str, Optional[mtgtop8.Top8Event]] = {}
        self.listings: Dict[str, List[mtgtop8.Listing]] = {}
        self.listed: Set[str] = set()

    def online(self, host: str) -> bool:
        return self.client.budget_left() and not self.client.stopped(host)

    def get(self, url: str) -> Optional[Fetched]:
        fetched = self.client.get(url)
        if fetched is None or is_refusal(fetched.status):
            return None
        if fetched.status != 200:
            log.info("%s answered HTTP %d", url, fetched.status)
        return fetched

    def warn(self, message: str) -> None:
        log.warning(message)
        self.report.warnings.append(message)

    # ---- mtgo.com events

    def mtgo_events(self, format: str) -> None:
        refs = self.new_refs(format)
        listings = self.top8_listings(format, refs)
        self.listings[format] = listings
        if format not in self.listed:
            if refs:
                log.info("%s: MTGTop8 did not answer, so its %d new mtgo.com events wait for names", format, len(refs))
            return
        read: List[Tuple[Event, List[Deck], Optional[mtgtop8.Top8Event]]] = []
        for ref in refs:
            if not self.online(MTGO_HOST):
                break
            candidates = self.candidates(ref, listings)
            if not candidates and self.recent(ref):
                log.info("%s waits for MTGTop8: it has no copy yet", ref.slug)
                continue
            found = self.read_mtgo_event(format, ref, candidates)
            if found:
                read.append(found)
        if not read:
            return
        reference = self.store.reference_decks(format, self.cutoff)
        for event, decks, top8 in read:
            if top8 is not None:
                self.report.named_by_top8 += name_from_top8(event, decks, top8, format)
                reference.extend(deck for deck in decks if deck.archetype_id)
        for event, decks, _ in read:
            self.save_mtgo_event(event, decks, reference)

    def new_refs(self, format: str) -> List[mtgo.EventRef]:
        refs = [
            ref
            for month in self.month_numbers()
            for ref in self.month(*month) or []
            if ref.format == format and ref.date >= self.cutoff
        ]
        stored = self.store.existing_event_ids(mtgo.event_id(ref) for ref in refs)
        fresh = [ref for ref in refs if mtgo.event_id(ref) not in stored]
        return sorted(fresh, key=lambda ref: (ref.date, ref.event_id), reverse=True)

    def month_numbers(self) -> List[Tuple[int, int]]:
        months = []
        year, month = self.cutoff.year, self.cutoff.month
        while (year, month) <= (self.now.year, self.now.month):
            months.append((year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return months[::-1]

    def month(self, year: int, month: int) -> Optional[List[mtgo.EventRef]]:
        if (year, month) not in self.months:
            fetched = self.get(f"{mtgo.BASE_URL}/decklists/{year}/{month:02d}")
            refs = None
            if fetched and fetched.status == 200:
                try:
                    refs = mtgo.parse_month(fetched.text())
                except Exception as error:  # noqa: BLE001 - every format's job reads it first
                    self.warn(f"mtgo.com month {year}-{month:02d}: {error}")
            self.months[(year, month)] = refs
        return self.months[(year, month)]

    def recent(self, ref: mtgo.EventRef) -> bool:
        return (self.now.date() - ref.date.date()).days <= self.config.top8_lag_days

    def candidates(self, ref: mtgo.EventRef, listings: List[mtgtop8.Listing]) -> List[mtgtop8.Listing]:
        day = ref.date.date()
        league = ref.kind == "mtgo_league"
        size = _SIZE.search(ref.name)
        found = []
        for listing in listings:
            theirs = _SIZE.search(listing.name)
            if (
                "mtgo" in listing.name.lower()
                and ("league" in listing.name.lower()) == league
                and not (size and theirs and size.group(1) != theirs.group(1))
                and abs((listing.date - day).days) <= 1
            ):
                found.append(listing)
        return sorted(found, key=lambda listing: (abs((listing.date - day).days), -int(listing.event_id)))

    def read_mtgo_event(
        self, format: str, ref: mtgo.EventRef, candidates: List[mtgtop8.Listing]
    ) -> Optional[Tuple[Event, List[Deck], Optional[mtgtop8.Top8Event]]]:
        """The event and its decks, with MTGTop8's copy when one matches; None when it is not ready or waits for names."""
        fetched = self.get(f"{mtgo.BASE_URL}/decklist/{ref.slug}")
        if fetched is None or fetched.status != 200:
            return None
        try:
            event, decks = mtgo.parse_event(fetched.text(), ref)
        except Exception as error:  # noqa: BLE001 - one odd page must not stop the format
            self.warn(f"mtgo.com event {ref.slug}: {error}")
            return None
        if not decks:
            log.info("%s has no decklists yet", ref.slug)
            return None
        top8 = self.matching_copy(format, ref, event, candidates)
        if top8 is None and not all(listing.event_id in self.top8_events for listing in candidates):
            log.info("%s waits for MTGTop8: it did not answer", ref.slug)
            return None
        if top8 is None and self.recent(ref):
            log.info("%s waits for MTGTop8: no copy matches yet", ref.slug)
            return None
        return event, decks, top8

    def save_mtgo_event(self, event: Event, decks: List[Deck], reference: List[Deck]) -> None:
        """Names what MTGTop8 left, by the nearest named list of the window and then by colours, and saves the event."""
        top8_named = sum(1 for deck in decks if deck.archetype_id)
        stats = name_event(event.format, event, decks, None, reference, self.catalog)
        stats.top8 = top8_named
        known = {deck.deck_id for deck in reference}
        reference.extend(deck for deck in decks if deck.archetype_id and deck.deck_id not in known)
        stored = self.store.existing_deck_ids(deck.deck_id for deck in decks)
        fresh = [deck for deck in decks if deck.deck_id not in stored]
        if self.save(f"event {event.event_id}", lambda: (self.store.save_decks(fresh), self.store.save_event(event))):
            self.report.events.append(event.event_id)
            self.report.decks_written += len(fresh)
            self.report.decks_skipped += len(decks) - len(fresh)
            self.report.named_by_lists += stats.lists
            self.report.named_by_colors += stats.colors
            log.info(
                "Saved %s (%d decks: %d named by MTGTop8, %d by lists, %d by colours)",
                event.event_id, len(decks), stats.top8, stats.lists, stats.colors,
            )

    def matching_copy(
        self, format: str, ref: mtgo.EventRef, event: Event, candidates: List[mtgtop8.Listing]
    ) -> Optional[mtgtop8.Top8Event]:
        players = [result.player for result in event.results]
        for listing in candidates:
            copy = self.top8_event(format, listing.event_id)
            found = mtgtop8.match_event(players, ref.date.date(), [copy]) if copy else None
            if found:
                return found
        return None

    # ---- MTGTop8

    def top8_listings(self, format: str, refs: List[mtgo.EventRef]) -> List[mtgtop8.Listing]:
        """Page 1 of the format, then older pages while one has paper events not yet known, or does not reach back to the oldest new mtgo.com event."""
        first_day = self.cutoff.date()
        reach = min((ref.date.date() for ref in refs), default=None)
        found: List[mtgtop8.Listing] = []
        for page in range(1, self.config.max_mtgtop8_pages + 1):
            fetched = self.get(mtgtop8.BASE_URL + mtgtop8.format_path(format, page))
            if fetched is None or fetched.status != 200:
                break
            try:
                listings, has_next = mtgtop8.parse_format_events(_text(fetched))
            except Exception as error:  # noqa: BLE001
                self.warn(f"MTGTop8 {format} page {page}: {error}")
                break
            if page == 1:
                self.listed.add(format)
            found.extend(listings)
            if not has_next or not listings:
                break
            oldest = min(listing.date for listing in listings)
            if oldest < first_day:
                break
            if not (self.unknown_paper(format, listings) or (reach and oldest >= reach - timedelta(days=1))):
                break
        return [listing for listing in found if listing.date >= first_day]

    def unknown_paper(self, format: str, listings: List[mtgtop8.Listing]) -> List[mtgtop8.Listing]:
        paper = [listing for listing in listings if not listing.name.startswith("MTGO")]
        stored = self.store.existing_event_ids(f"t8-{listing.event_id}" for listing in paper)
        seen = self.store.source_state(format)["seen"]
        return [listing for listing in paper if f"t8-{listing.event_id}" not in stored and listing.event_id not in seen]

    def top8_event(self, format: str, event_id: str) -> Optional[mtgtop8.Top8Event]:
        if event_id not in self.top8_events:
            fetched = self.get(mtgtop8.BASE_URL + mtgtop8.event_path(event_id, format))
            if fetched is None:
                return None
            copy = None
            if fetched.status == 200:
                try:
                    copy = mtgtop8.parse_event(_text(fetched), event_id)
                except Exception as error:  # noqa: BLE001
                    self.warn(f"MTGTop8 event {event_id}: {error}")
            self.top8_events[event_id] = copy
        return self.top8_events[event_id]

    # ---- paper events

    def paper_events(self, format: str) -> None:
        state = self.store.source_state(format)
        for event in self.store.events_since(format, self.cutoff):
            if event.event_id.startswith("t8-") and self.online(TOP8_HOST):
                self.read_decks(format, event.event_id, event.results, state)
        for listing in sorted(self.unknown_paper(format, self.listings.get(format, [])), key=lambda item: item.date, reverse=True):
            if not self.online(TOP8_HOST):
                return
            self.read_paper_event(format, listing, state)

    def read_paper_event(self, format: str, listing: mtgtop8.Listing, state: dict) -> None:
        copy = self.top8_event(format, listing.event_id)
        if copy is None:
            return
        if not copy.decks and copy.source != mtgo.SOURCE and (self.now.date() - listing.date).days <= self.config.top8_lag_days:
            log.info("MTGTop8 event %s has no decks yet", listing.event_id)
            return
        if copy.source == mtgo.SOURCE or not copy.decks:
            state["seen"][listing.event_id] = f"{listing.date:%Y-%m-%d}"
            return
        kind = event_kind(copy.name, copy.source)
        published = f"t8-{copy.event_id}"
        try:
            results = [
                EventResult(
                    player=deck.player,
                    archetype=deck.archetype,
                    finish=mtgtop8.finish(deck.place, kind == "mtgo_league"),
                    deck_id=f"t8-{deck.deck_id}",
                    archetype_id=mtgtop8.archetype_id(format, deck.archetype),
                )
                for deck in copy.decks
            ]
        except ValueError as error:
            self.warn(f"MTGTop8 event {copy.event_id}: {error}")
            state["seen"][listing.event_id] = f"{listing.date:%Y-%m-%d}"
            return
        event = Event(
            event_id=published,
            event_name=copy.name,
            format=format,
            date=datetime(copy.date.year, copy.date.month, copy.date.day, tzinfo=timezone.utc),
            results=results,
            url=mtgtop8.BASE_URL + mtgtop8.event_path(copy.event_id, format),
            kind=kind,
            source=copy.source,
        )
        if self.read_decks(format, published, results, state):
            if self.save(f"event {published}", lambda: self.store.save_event(event)):
                self.report.events.append(published)
                log.info("Saved %s %s (%d decks)", published, event.event_name, len(results))

    def read_decks(self, format: str, event_id: str, results: List[EventResult], state: dict) -> bool:
        """Downloads the event's decks not yet stored and not given up on, and saves them. False when the run ran out before the last."""
        stored = self.store.existing_deck_ids(result.deck_id for result in results)
        fresh: List[Deck] = []
        complete = True
        for result in results:
            deck_id = result.deck_id
            if deck_id in stored or state["failed"].get(deck_id, 0) >= DECK_ATTEMPTS:
                continue
            if not self.online(TOP8_HOST):
                complete = False
                break
            fetched = self.get(mtgtop8.BASE_URL + mtgtop8.deck_path(deck_id[len("t8-"):]))
            if fetched is None:
                complete = False
                break
            try:
                if fetched.status != 200:
                    raise ParseError(f"HTTP {fetched.status}")
                mainboard, sideboard = parse_decklist(_text(fetched))
            except ParseError as error:
                state["failed"][deck_id] = state["failed"].get(deck_id, 0) + 1
                log.info("Deck %s could not be read (attempt %d): %s", deck_id, state["failed"][deck_id], error)
                continue
            fresh.append(Deck(deck_id, result.player, result.archetype, mainboard, sideboard, format, event_id, result.archetype_id))
        if fresh and self.save(f"{len(fresh)} decks of {event_id}", lambda: self.store.save_decks(fresh)):
            self.report.decks_written += len(fresh)
        return complete

    # ---- metagame

    def metagame(self, format: str) -> None:
        events = self.store.events_since(format, self.cutoff)
        published = self.store.existing_deck_ids(result.deck_id for event in events for result in event.results)
        rows = [(event, result) for event in events for result in event.results]
        for days in WINDOWS:
            start = self.now - timedelta(days=days)
            window = [(event, result) for event, result in rows if event.date >= start]
            meta = Meta(format, f"{days}d", self.archetypes(window, published))
            if self.save(f"meta {meta.doc_id}", lambda: self.store.save_meta(meta)):
                self.report.meta.append(meta.doc_id)
        for archetype_id, group in _by_archetype(rows).items():
            history = _history(format, archetype_id, group, published)
            if history.results and self.save(f"archetype {history.doc_id}", lambda: self.store.save_archetype(history)):
                self.report.archetypes.append(history.doc_id)

    def archetypes(self, window: List[Tuple[Event, EventResult]], published: set) -> List[Archetype]:
        archetypes = []
        for archetype_id, group in _by_archetype(window).items():
            featured = _featured(group, published)
            archetypes.append(
                Archetype(
                    name=_name(group),
                    percentage=round(len(group) / len(window) * 100, 1),
                    id=archetype_id,
                    deck_count=len(group),
                    deck_id=featured[1].deck_id if featured else None,
                )
            )
        return sorted(archetypes, key=lambda archetype: (-archetype.percentage, archetype.name))

    # ---- saving

    def save(self, what: str, write) -> bool:
        try:
            write()
            return True
        except Exception as error:  # noqa: BLE001
            log.exception("Failed on saving %s", what)
            self.report.errors.append(f"saving {what}: {error}")
            return False


def _text(fetched: Fetched) -> str:
    try:
        return fetched.body.decode("utf-8")
    except UnicodeDecodeError:
        return fetched.body.decode("latin-1")


def _by_archetype(rows: List[Tuple[Event, EventResult]]) -> Dict[str, List[Tuple[Event, EventResult]]]:
    groups: Dict[str, List[Tuple[Event, EventResult]]] = {}
    for event, result in rows:
        if result.archetype_id:
            groups.setdefault(result.archetype_id, []).append((event, result))
    return groups


def _name(group: List[Tuple[Event, EventResult]]) -> str:
    return Counter(result.archetype for _, result in group).most_common(1)[0][0]


def _place(finish: str) -> int:
    found = place(finish)
    return LEAGUE_PLACE if found is None else found


def _featured(group: List[Tuple[Event, EventResult]], published: set) -> Optional[Tuple[Event, EventResult]]:
    """The best-placed deck of the group, the newest of those; a League's 5-0 counts as the lowest Top 16 place."""
    decks = [(event, result) for event, result in group if result.deck_id in published]
    return min(decks, key=lambda row: (_place(row[1].finish), -row[0].date.timestamp()), default=None)


def _history(format: str, archetype_id: str, group: List[Tuple[Event, EventResult]], published: set) -> ArchetypeHistory:
    featured = _featured(group, published)
    return ArchetypeHistory(
        format=format,
        archetype_id=archetype_id,
        name=_name(group),
        deck_id=featured[1].deck_id if featured else None,
        featured_player=featured[1].player if featured else None,
        results=[
            ArchetypeResult(result.deck_id, event.date, result.player, event.event_id, event.event_name, result.finish)
            for event, result in group
            if result.deck_id in published
        ],
    )
