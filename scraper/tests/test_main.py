import logging

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
