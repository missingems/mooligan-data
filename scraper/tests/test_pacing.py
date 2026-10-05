import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from mtgmeta.browser import BlockedError, Fetched
from mtgmeta.pacing import (
    BACKOFF,
    DWELL,
    GROUP_SIZE,
    LONG_PAUSE,
    MAX_BACKOFF,
    DeckPacing,
    Pacer,
    Visit,
    build_plan,
    deck_path,
    note_deck_block,
    run_downloads,
)

NOW = datetime(2026, 10, 5, 14, tzinfo=timezone.utc)


class Clock:
    """A clock that only moves when something sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def make_pacer(seed=1, **pacing_values):
    clock = Clock()
    return Pacer(DeckPacing(**pacing_values), random.Random(seed), sleep=clock.sleep, clock=clock), clock


@dataclass
class Deck:
    deck_id: str
    format: str = "modern"
    event_id: Optional[str] = None
    archetype_id: Optional[str] = None


def test_gap_stays_within_its_clamp_apart_from_long_pauses():
    pacer, clock = make_pacer(delay=2.0)
    gaps = [pacer.gap() for _ in range(2000)]
    assert gaps == clock.slept
    short = [gap for gap in gaps if gap <= 10.0]
    assert all(0.8 <= gap <= 10.0 for gap in short)
    # A long pause adds 20 to 60 seconds to a gap of at least 0.8.
    assert all(gap >= LONG_PAUSE[0] + 0.8 for gap in gaps if gap > 10.0)
    assert 0.02 < sum(gap > 10.0 for gap in gaps) / len(gaps) < 0.07
    median = sorted(short)[len(short) // 2]
    assert 1.7 < median < 2.4


def test_no_delay_means_no_sleeping():
    pacer, clock = make_pacer(delay=0)
    assert (pacer.gap(), pacer.dwell()) == (0.0, 0.0) and clock.slept == []


def test_dwell_is_a_few_seconds():
    pacer, clock = make_pacer()
    assert all(DWELL[0] <= pacer.dwell() <= DWELL[1] for _ in range(50)) and len(clock.slept) == 50


def test_backoff_doubles_from_thirty_seconds_with_jitter():
    pacer, _ = make_pacer()
    for refusals, base in ((1, 30), (2, 60), (3, 120)):
        for _ in range(20):
            assert 0.8 * base <= pacer.backoff_seconds(refusals) <= 1.2 * base


def test_backoff_follows_a_larger_retry_after_and_is_capped():
    pacer, _ = make_pacer()
    assert pacer.backoff_seconds(1, 200) == 200
    assert pacer.backoff_seconds(1, 5) <= 1.2 * BACKOFF
    assert pacer.backoff_seconds(1, 5000) == MAX_BACKOFF
    assert pacer.backoff_seconds(10) == MAX_BACKOFF


def test_the_budget_runs_down_with_the_clock():
    pacer, clock = make_pacer(minutes=2)
    assert pacer.time_left() == 120
    clock.sleep(45)
    assert (pacer.elapsed(), pacer.time_left()) == (45, 75)


def newest_first(format, events, per_event, featured=0):
    """A format's decks in plan order: `featured` archetype decks, then events of `per_event` decks, newest first."""
    decks = [Deck(f"{format}-f{i}", format, None, f"{format}-arch{i}") for i in range(featured)]
    for event in range(events):
        decks += [Deck(f"{format}-e{event}-{i}", format, f"{format}{event}", f"{format}-arch{i % 3}") for i in range(per_event)]
    return decks


def test_every_deck_appears_once_and_visits_are_by_source_page():
    wanted = {
        "modern": newest_first("modern", 5, 20, featured=3),
        "legacy": newest_first("legacy", 3, 15) + [Deck("legacy-x", "legacy"), Deck("legacy-y", "legacy", None, "legacy-arch9")],
    }
    plan = build_plan(wanted, DeckPacing(per_run=10_000), random.Random(3))
    ids = [deck.deck_id for visit in plan for deck in visit.decks]
    assert sorted(ids) == sorted(deck.deck_id for decks in wanted.values() for deck in decks)
    for visit in plan:
        for deck in visit.decks:
            expected = (
                f"/tournament/{deck.event_id}" if deck.event_id
                else f"/archetype/{deck.archetype_id}" if deck.archetype_id
                else f"/metagame/{deck.format}"
            )
            assert visit.path == expected
    assert {"/metagame/legacy", "/archetype/legacy-arch9", "/tournament/modern0"} <= {visit.path for visit in plan}


def test_visit_sizes_stay_within_the_group_size_apart_from_a_remainder():
    plan = build_plan({"modern": newest_first("modern", 6, 40)}, DeckPacing(per_run=10_000), random.Random(5))
    per_path = {}
    for visit in plan:
        per_path.setdefault(visit.path, []).append(len(visit.decks))
    for sizes in per_path.values():
        assert sum(sizes) == 40
        assert all(GROUP_SIZE[0] <= size <= GROUP_SIZE[1] for size in sizes[:-1])
        assert 1 <= sizes[-1] <= GROUP_SIZE[1]


def test_the_plan_is_cut_to_the_per_run_allowance():
    wanted = {"modern": newest_first("modern", 10, 20), "legacy": newest_first("legacy", 10, 20)}
    plan = build_plan(wanted, DeckPacing(per_run=77), random.Random(9))
    assert sum(len(visit.decks) for visit in plan) == 77
    assert build_plan(wanted, DeckPacing(per_run=0), random.Random(9)) == []


def test_formats_take_turns_one_visit_at_a_time():
    formats = ("modern", "standard", "pioneer")
    wanted = {name: newest_first(name, 4, 30) for name in formats}
    plan = build_plan(wanted, DeckPacing(per_run=10_000), random.Random(2))
    assert [visit.decks[0].format for visit in plan[:3]] == list(formats)
    assert [visit.decks[0].format for visit in plan[3:6]] == list(formats)


def test_a_format_that_runs_out_drops_from_the_turns():
    wanted = {"modern": newest_first("modern", 1, 6), "legacy": newest_first("legacy", 4, 30)}
    plan = build_plan(wanted, DeckPacing(per_run=10_000), random.Random(2))
    assert sum(len(v.decks) for v in plan if v.decks[0].format == "modern") == 6
    assert {v.decks[0].format for v in plan[-3:]} == {"legacy"}


def test_featured_decks_are_in_a_formats_first_visits():
    for seed in range(20):
        wanted = {"modern": newest_first("modern", 6, 30, featured=1)}
        plan = build_plan(wanted, DeckPacing(per_run=10_000), random.Random(seed))
        # The next event ranks right after it, so it can swap places with at most that one visit.
        assert "modern-f0" in [deck.deck_id for visit in plan[:2] for deck in visit.decks]


def test_newest_decks_come_before_the_oldest():
    wanted = {"modern": newest_first("modern", 12, 30)}
    order = [deck.deck_id for visit in build_plan(wanted, DeckPacing(per_run=10_000), random.Random(4)) for deck in visit.decks]
    place = {deck_id: index for index, deck_id in enumerate(order)}
    newest = [deck.deck_id for deck in wanted["modern"][:120]]
    oldest = [deck.deck_id for deck in wanted["modern"][-120:]]
    assert sum(place[d] for d in newest) / 120 < sum(place[d] for d in oldest) / 120 - 100
    # And not strictly in order.
    assert order != [deck.deck_id for deck in wanted["modern"]]


def test_visits_of_one_page_keep_their_order():
    decks = [Deck(f"d{i}", "modern", "7") for i in range(60)]
    for seed in range(20):
        plan = build_plan({"modern": decks}, DeckPacing(per_run=10_000), random.Random(seed))
        # Each visit holds a consecutive slice of the page's decks, and the slices come in order.
        spans = [sorted(int(deck.deck_id[1:]) for deck in visit.decks) for visit in plan]
        assert [span[0] for span in spans] == sorted(span[0] for span in spans)


class FakeBrowser:
    """Answers deck downloads from a script: a list of statuses per path, one per request, 200 once used up."""

    def __init__(self, script=None, page_errors=None):
        self.script = script or {}
        self.page_errors = list(page_errors or [])  # what successive page() calls raise (None for none)
        self.pages = []
        self.batches = []
        self.events = []

    def page(self, path):
        self.pages.append(path)
        self.events.append("page")
        if self.page_errors:
            error = self.page_errors.pop(0)
            if error is not None:
                raise error
        return "<html></html>"

    def fetch_batch(self, paths):
        self.batches.append(list(paths))
        self.events.append("batch")
        answers = []
        for path in paths:
            statuses = self.script.get(path, [])
            status = statuses.pop(0) if statuses else 200
            body = "<title>Just a moment...</title>" if status == 403 else "4 Lightning Bolt"
            retry = 120.0 if status == 429 else None
            answers.append(Fetched(path, status, body, retry, "challenge" if status == 403 else ""))
        return answers


def visits_of(*groups):
    return [Visit(path, [Deck(deck_id) for deck_id in ids]) for path, ids in groups]


def download(browser, visits, concurrency=2, **pacing_values):
    pacer, clock = make_pacer(concurrency=concurrency, **pacing_values)
    handled = []
    outcome = run_downloads(browser, visits, pacer, lambda visit, fetched: handled.extend(f.path for f in fetched))
    return outcome, handled, clock


def test_everything_downloads_in_batches_after_a_visit_to_the_page():
    browser = FakeBrowser()
    outcome, handled, clock = download(browser, visits_of(("/tournament/1", ["a", "b", "c"]), ("/tournament/2", ["d"])))
    assert browser.pages == ["/tournament/1", "/tournament/2"]
    assert browser.batches == [[deck_path("a"), deck_path("b")], [deck_path("c")], [deck_path("d")]]
    assert handled == [deck_path(d) for d in "abcd"]
    assert (outcome.downloaded_attempted, outcome.left, outcome.reason, outcome.refusal) == (4, 0, "done", None)
    # A dwell on each page and a gap after each batch but the last.
    assert len(clock.slept) == 2 + 2


def test_a_refused_batch_waits_revisits_the_page_and_retries_only_the_refused():
    browser = FakeBrowser({deck_path("b"): [403]})
    outcome, handled, clock = download(browser, visits_of(("/tournament/1", ["a", "b", "c", "d"])))
    assert browser.batches == [[deck_path("a"), deck_path("b")], [deck_path("b")], [deck_path("c"), deck_path("d")]]
    # Nothing was sent between the refusal and the second visit.
    assert browser.events == ["page", "batch", "page", "batch", "batch"]
    assert any(24 <= seconds <= 36 for seconds in clock.slept)
    assert sorted(handled) == sorted(deck_path(d) for d in "abcd")
    assert (outcome.downloaded_attempted, outcome.left, outcome.reason, outcome.refusals_total) == (4, 0, "done", 1)


def test_a_success_resets_the_count_of_refusals():
    script = {deck_path(d): [403] for d in "bdf"}  # three refusals, a success between each
    outcome, _, _ = download(FakeBrowser(script), visits_of(("/tournament/1", list("abcdefg"))))
    assert (outcome.reason, outcome.left, outcome.refusals_total) == ("done", 0, 3)


def test_three_refusals_in_a_row_end_the_phase_and_log_it_once(caplog):
    browser = FakeBrowser({deck_path(d): [403] * 10 for d in "abcdef"})
    with caplog.at_level(logging.DEBUG):
        outcome, handled, clock = download(browser, visits_of(("/tournament/1", list("abcd")), ("/tournament/2", list("ef"))))
    assert outcome.reason == "blocked" and outcome.refusals_total == 3
    assert (outcome.downloaded_attempted, outcome.left, handled) == (0, 6, [])
    assert outcome.refusal.startswith("HTTP 403, cf-mitigated=challenge") and "Just a moment" in outcome.refusal
    assert len(browser.batches) == 3 and "/tournament/2" not in browser.pages
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "HTTP 403" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR] and not any(r.exc_info for r in caplog.records)
    # Waits of about 30 s and 60 s; the third refusal ends it without waiting again.
    waits = [s for s in clock.slept if s > DWELL[1]]
    assert len(waits) == 2 and 24 <= waits[0] <= 36 and 48 <= waits[1] <= 72


def test_a_page_the_site_blocks_counts_as_a_refusal():
    browser = FakeBrowser(page_errors=[BlockedError("Blocked on a")])
    outcome, _, _ = download(browser, visits_of(("/tournament/1", ["a"])))
    # Blocked, waited, visited again, then downloaded.
    assert (outcome.reason, outcome.refusals_total, outcome.downloaded_attempted) == ("done", 1, 1)
    assert outcome.refusal == "Blocked on a"
    stuck = FakeBrowser(page_errors=[BlockedError("Blocked on a")] * 5)
    outcome, _, _ = download(stuck, visits_of(("/tournament/1", ["a", "b"])))
    assert (outcome.reason, outcome.left, outcome.refusals_total, stuck.batches) == ("blocked", 2, 3, [])


def test_another_error_visiting_a_page_does_not_stop_the_downloads():
    browser = FakeBrowser(page_errors=[RuntimeError("503 on /tournament/1")])
    outcome, handled, _ = download(browser, visits_of(("/tournament/1", ["a"])))
    assert (outcome.reason, outcome.downloaded_attempted) == ("done", 1) and handled == [deck_path("a")]


def test_a_deck_that_is_not_there_is_an_answer_not_a_refusal():
    browser = FakeBrowser({deck_path("a"): [404]})
    outcome, handled, _ = download(browser, visits_of(("/tournament/1", ["a"])))
    assert (outcome.reason, outcome.refusals_total, outcome.downloaded_attempted) == ("done", 0, 1)
    assert handled == [deck_path("a")]


def test_the_time_budget_ends_the_phase():
    # Each dwell and gap takes a few seconds, so a minute allows only a few visits.
    visits = visits_of(*[(f"/tournament/{i}", [f"{i}-{j}" for j in range(4)]) for i in range(40)])
    outcome, handled, clock = download(FakeBrowser(), visits, minutes=1)
    assert outcome.reason == "time" and 0 < outcome.downloaded_attempted < 160
    assert outcome.left == 160 - outcome.downloaded_attempted == 160 - len(handled)
    assert clock.now - 1000 < 60 + 70  # stops at the first check after the budget, not long after


def test_a_wait_longer_than_the_time_left_ends_the_phase_at_once():
    browser = FakeBrowser({deck_path("a"): [429]})  # Retry-After: 120 s
    outcome, _, clock = download(browser, visits_of(("/tournament/1", ["a", "b"])), minutes=1)
    assert (outcome.reason, outcome.left, outcome.refusals_total) == ("blocked", 1, 1)  # b was answered; a was not
    assert outcome.refusal.startswith("HTTP 429") and "retry-after=120s" in outcome.refusal
    # Only the dwell was slept: it did not wait for a minute it does not have.
    assert max(clock.slept) <= DWELL[1] and len(browser.batches) == 1


def test_a_run_with_no_delay_never_sleeps_for_dwell_or_gaps():
    outcome, _, clock = download(FakeBrowser(), visits_of(("/tournament/1", list("abcd"))), delay=0)
    assert outcome.reason == "done" and clock.slept == []


def test_the_block_counter_counts_runs_in_a_row_and_resets(tmp_path):
    path = tmp_path / "state" / "deck-downloads.json"
    assert note_deck_block(path, True, "HTTP 403", NOW) == 1
    assert note_deck_block(path, True, "HTTP 429", NOW) == 2
    assert json.loads(path.read_text()) == {"blocked_runs": 2, "last_blocked": NOW.isoformat(), "detail": "HTTP 429"}
    assert note_deck_block(path, False, None, NOW) == 0
    saved = json.loads(path.read_text())
    assert (saved["blocked_runs"], saved["last_blocked"]) == (0, NOW.isoformat())


def test_a_missing_or_corrupt_counter_file_starts_from_zero(tmp_path):
    path = tmp_path / "deck-downloads.json"
    assert note_deck_block(path, True, "x", NOW) == 1
    path.write_text("{not json")
    assert note_deck_block(path, True, "x", NOW) == 1
    path.write_text('{"blocked_runs": "many"}')
    assert note_deck_block(path, False, None, NOW) == 0
