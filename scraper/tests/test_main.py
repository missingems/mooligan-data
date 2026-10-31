import json
import logging
import sys
from contextlib import contextmanager

import pytest

from mtgmeta import __main__ as entry
from mtgmeta.models import RunReport


def test_a_scryfall_failure_lands_in_the_report(monkeypatch, caplog):
    def broken():
        raise RuntimeError("scryfall is down")

    monkeypatch.setattr(entry, "card_catalog", broken)
    report = RunReport()
    with caplog.at_level(logging.ERROR):
        assert entry.load_catalog(report) == {}
    assert report.errors == ["scryfall catalog: scryfall is down"]


def test_the_catalog_is_returned_and_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(entry, "card_catalog", lambda: {"lightning-bolt": {"oracle_id": "x"}})
    assert entry.load_catalog(RunReport()) == {"lightning-bolt": {"oracle_id": "x"}}
    monkeypatch.setenv("SCRYFALL_CATALOG", "0")
    assert entry.load_catalog(RunReport()) == {}


def test_a_clean_run_exits_zero():
    assert entry.exit_code(RunReport(), 0) == 0


def test_errors_fail_the_run():
    assert entry.exit_code(RunReport(errors=["event 1: boom"]), 0) == 1


def test_one_blocked_run_is_a_warning_the_run_passes():
    report = RunReport(deck_block="HTTP 403, cf-mitigated=challenge", warnings=["Deck downloads blocked after 0"])
    assert entry.exit_code(report, 1) == 0 and report.errors == []


def test_two_blocked_runs_in_a_row_fail_the_run():
    report = RunReport(deck_block="HTTP 403, cf-mitigated=challenge")
    assert entry.exit_code(report, 2) == 1
    assert report.errors == ["deck downloads blocked 2 runs in a row: HTTP 403, cf-mitigated=challenge"]


def test_a_run_that_was_not_blocked_passes_whatever_the_count():
    assert entry.exit_code(RunReport(), 5) == 0


def test_guides_build_the_top_commanders_up_to_the_runs_limit(monkeypatch, tmp_path):
    from mtgmeta import guides
    from mtgmeta.guides import Result

    calls = []

    def run(directory, slugs, source, catalog, **options):
        calls.append((slugs, options["limit"]))
        return Result(written=["edh/commanders/a/guide.json"], failed=["b"])

    monkeypatch.setattr(guides, "run", run)
    monkeypatch.setenv("GUIDES_PER_RUN", "2")
    monkeypatch.setenv("GUIDES_TOP", "2")
    top = {"7d": [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]}
    report = RunReport()

    assert entry.publish_guides(tmp_path, report, top, {"x": {}}, "https://data.example") == ["edh/commanders/a/guide.json"]
    assert calls == [(["a", "b"], 2)] and report.warnings == ["commander guides failed: b"] and not report.errors

    monkeypatch.setenv("GUIDES_PER_RUN", "0")
    assert entry.publish_guides(tmp_path, report, top, {"x": {}}, "https://data.example") == [] and len(calls) == 1


def test_guides_cover_the_top_commanders_and_every_one_a_bracket_ranks(monkeypatch, tmp_path):
    from mtgmeta import guides
    from mtgmeta.guides import Result

    calls = []
    monkeypatch.setattr(guides, "run", lambda directory, slugs, source, catalog, **options: calls.append((slugs, options["polish"])) or Result())
    monkeypatch.setenv("GUIDES_TOP", "2")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    top = {"7d": [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]}
    brackets = {5: {"source": "edhtop16", "rows": [{"slug": "e"}, {"slug": "a"}]}, 2: {"source": "edhrec", "rows": [{"slug": "d"}]}}

    entry.publish_guides(tmp_path, RunReport(), top, {"x": {}}, "https://data.example", brackets)

    # No key, so no polisher: the guides are built and keep their templated summaries.
    assert calls == [(["a", "b", "d", "e"], None)]


def run_main(monkeypatch, root, **env):
    """main() on `root` for Modern, offline: no card catalog, and EDHREC, the first of the files built from every format, fails the test."""
    for name, value in {"SCRYFALL_CATALOG": "0", "FORMATS": "modern", **env}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["mtgmeta", str(root)])
    monkeypatch.setattr(entry, "Edhrec", lambda **kwargs: pytest.fail("the files built from every format were built"))
    return entry.main()


def test_a_format_job_scrapes_its_format_and_builds_none_of_the_files_built_from_every_format(monkeypatch, tmp_path):
    scraped = []

    @contextmanager
    def browser(**kwargs):
        yield "browser"

    monkeypatch.setattr(entry, "open_browser", browser)
    monkeypatch.setattr(entry, "scrape", lambda browser, store, config, report: scraped.append(config.formats))
    assert run_main(monkeypatch, tmp_path, SHARED="0") == 0
    assert scraped == [("modern",)]
    # index.json, written as the sign the run finished, for ops/scrape.sh to leave unpublished.
    assert (tmp_path / "index.json").exists() and not (tmp_path / "explore.json").exists()
    assert json.loads((tmp_path / "state" / "deck-downloads.json").read_text())["blocked_runs"] == 0


def test_a_run_that_does_not_scrape_opens_no_browser_and_leaves_the_blocked_count_as_it_was(monkeypatch, tmp_path):
    # Two format jobs in a row were blocked: the job after them must not reset the count. SHARED=0 keeps EDHREC out.
    blocked = tmp_path / "state" / "deck-downloads.json"
    blocked.parent.mkdir(parents=True)
    blocked.write_text(json.dumps({"blocked_runs": 2, "last_blocked": "2026-11-01T14:30:00+00:00", "detail": "HTTP 429"}))
    monkeypatch.setattr(entry, "open_browser", lambda **kwargs: pytest.fail("MTGGoldfish was read"))
    assert run_main(monkeypatch, tmp_path, SHARED="0", SCRAPE="0") == 0
    assert json.loads(blocked.read_text())["blocked_runs"] == 2
