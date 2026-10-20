import gzip
import json
from types import SimpleNamespace

from mtgmeta import __main__ as entry
from mtgmeta import localized

ORACLE = "11111111-1111-1111-1111-111111111111"


def printing(id, lang, **extra):
    card = {
        "id": id, "oracle_id": ORACLE, "lang": lang, "set": "aaa", "collector_number": "1", "released_at": "2026-01-01",
        "layout": "normal", "games": ["paper"], "image_status": "highres_scan",
        "image_uris": {"normal": f"https://cards.scryfall.io/normal/front/{id}.jpg"},
    }
    card.update(extra)
    return card


def bulk(tmp_path):
    rows = [
        printing("e1", "en"),
        printing("j1", "ja", printed_name="日本", printed_type_line="クリーチャー", printed_text="てきすと"),
    ]
    path = tmp_path / "all.jsonl.gz"
    with gzip.open(path, "wb") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False).encode() + b"\n")
    return path.as_uri()


def write_feed(directory):
    (directory / "today.json").write_text(json.dumps({"breakouts": [{"oracle_id": ORACLE}]}))
    (directory / "explore.json").write_text(json.dumps({"formats": [{"cards": [{"oracle_id": ORACLE}]}]}))


def test_a_good_run_writes_the_state_with_text(tmp_path):
    write_feed(tmp_path)
    assert localized.localize(tmp_path, bulk(tmp_path)) == []
    saved = json.loads(gzip.decompress((tmp_path / localized.STATE).read_bytes()))
    assert saved[ORACLE]["ja"]["name"] == "日本" and saved[ORACLE]["ja"]["text"] == "てきすと"
    today = json.loads((tmp_path / "today.json").read_text())
    explore = json.loads((tmp_path / "explore.json").read_text())
    assert today["localized"][ORACLE]["ja"]["type_line"] == "クリーチャー"
    assert "type_line" not in explore["localized"][ORACLE]["ja"]


def test_a_file_that_cannot_be_read_falls_back_to_the_state_and_returns_a_problem(tmp_path):
    write_feed(tmp_path)
    localized.localize(tmp_path, bulk(tmp_path))
    good = {name: (tmp_path / name).read_text() for name in ("today.json", "explore.json")}
    write_feed(tmp_path)
    problems = localized.localize(tmp_path, (tmp_path / "missing.jsonl.gz").as_uri())
    assert len(problems) == 1 and "last good run" in problems[0]
    assert {name: (tmp_path / name).read_text() for name in good} == good


def test_a_file_that_cannot_be_read_with_no_state_raises_and_leaves_the_files(tmp_path):
    write_feed(tmp_path)
    before = (tmp_path / "today.json").read_text()
    try:
        localized.localize(tmp_path, (tmp_path / "missing.jsonl.gz").as_uri())
    except OSError:
        pass
    else:
        raise AssertionError("expected an error")
    assert (tmp_path / "today.json").read_text() == before


def test_publish_localized_reports_a_failure_as_a_warning_not_an_error(tmp_path, monkeypatch):
    write_feed(tmp_path)
    monkeypatch.setenv("LOCALIZE_ALL_CARDS_URL", (tmp_path / "missing.jsonl.gz").as_uri())
    report = SimpleNamespace(errors=[], warnings=[])
    assert entry.publish_localized(tmp_path, report) == []
    assert report.errors == [] and len(report.warnings) == 1 and report.warnings[0].startswith("localized: ")


def test_localize_can_be_turned_off(tmp_path, monkeypatch):
    write_feed(tmp_path)
    monkeypatch.setenv("LOCALIZE", "0")
    report = SimpleNamespace(errors=[], warnings=[])
    assert entry.publish_localized(tmp_path, report) == []
    assert "localized" not in json.loads((tmp_path / "today.json").read_text())
