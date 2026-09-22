"""Walks formats, events and decklists, writing each record as soon as it is parsed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Protocol, Sequence

from .models import Deck, RunReport
from .parsing import parse_decklist, parse_meta, parse_tournament, parse_tournament_list
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
    events_per_format: int = 10
    # Decks never change once published, so each run only downloads new ones;
    # the cap keeps a first run (or a backlog) from hammering the site.
    max_new_decks: int = 400


def scrape(browser: Browser, store: Store, config: ScrapeConfig) -> RunReport:
    report = RunReport()
    deck_budget = config.max_new_decks
    for format in config.formats:
        for days in config.meta_days:
            try:
                meta = parse_meta(browser.metagame(format, days), format, f"{days}d")
                store.save_meta(meta)
                report.meta.append(meta.doc_id)
                log.info("Saved meta %s (%d archetypes)", meta.doc_id, len(meta.archetypes))
            except Exception as error:  # noqa: BLE001 - one failed page must not stop the run
                _fail(report, f"meta {format} {days}d", error)

        try:
            summaries = parse_tournament_list(browser.page(f"/tournaments/{format}"))[: config.events_per_format]
        except Exception as error:  # noqa: BLE001
            _fail(report, f"tournaments {format}", error)
            continue

        for summary in summaries:
            try:
                event = parse_tournament(browser.page(f"/tournament/{summary.event_id}"), summary.event_id, format, summary)
                store.save_event(event)
                report.events.append(event.event_id)
                log.info("Saved event %s %s (%d results)", event.event_id, event.event_name, len(event.results))
            except Exception as error:  # noqa: BLE001
                _fail(report, f"event {summary.event_id}", error)
                continue

            existing = store.existing_deck_ids(result.deck_id for result in event.results)
            report.decks_skipped += len(existing)
            decks: List[Deck] = []
            for result in event.results:
                if result.deck_id in existing or any(deck.deck_id == result.deck_id for deck in decks):
                    continue
                if deck_budget <= 0:
                    break
                try:
                    mainboard, sideboard = parse_decklist(browser.deck_text(result.deck_id))
                except Exception as error:  # noqa: BLE001
                    _fail(report, f"deck {result.deck_id}", error)
                    continue
                deck_budget -= 1
                decks.append(
                    Deck(
                        deck_id=result.deck_id,
                        player=result.player,
                        archetype=result.archetype,
                        mainboard=mainboard,
                        sideboard=sideboard,
                        format=format,
                        event_id=event.event_id,
                    )
                )
            if decks:
                store.save_decks(decks)
                report.decks_written += len(decks)
                log.info("Saved %d decks from event %s", len(decks), event.event_id)
    if deck_budget <= 0:
        log.warning("Stopped at the limit of %d new decks; the rest come next run", config.max_new_decks)
    return report


def _fail(report: RunReport, what: str, error: Exception) -> None:
    log.exception("Failed on %s", what)
    report.errors.append(f"{what}: {error}")
