import hashlib
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import mtgmeta.__main__ as entry
from mtgmeta.manifest import PATH, STATE_PATH, build_manifest, is_explore_path, read_previous, write_manifest

NOW = datetime(2026, 10, 4, 19, 52, 10, tzinfo=timezone.utc)
FORMATS = ["modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "penny_dreadful", "duel_commander"]
# The upload the scrape workflow runs, which lives in the script it calls.
UPLOAD = Path(__file__).resolve().parents[2] / "ops" / "scrape.sh"


def put(directory, path, text="{}"):
    file = directory / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(text.encode("utf-8"))
    return file.read_bytes()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def put_state(directory, files):
    put(directory, STATE_PATH, json.dumps({"schema": 1, "generated_at": "2026-10-03T19:00:00Z", "files": files}))


def listed(directory):
    return json.loads((directory / PATH).read_text())["files"]


def test_each_listed_hash_is_the_sha256_of_that_files_bytes(tmp_path):
    bodies = {
        "explore.json": put(tmp_path, "explore.json", '{"formats":[{"name":"Élan"}]}'),
        "today.json": put(tmp_path, "today.json", '{"schema":1}'),
        "popular-cards/modern.json": put(tmp_path, "popular-cards/modern.json", '{"format":"modern"}'),
        "breakouts/modern.json": put(tmp_path, "breakouts/modern.json", '{"format":"modern","cards":[]}'),
    }
    assert write_manifest(tmp_path, NOW) == ["explore-manifest.json"]
    assert {path: entry["sha256"] for path, entry in listed(tmp_path).items()} == {path: sha(body) for path, body in bodies.items()}
    assert all(re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) for entry in listed(tmp_path).values())
    assert all(list(entry) == ["sha256"] for entry in listed(tmp_path).values())


def test_the_explore_files_are_listed_and_nothing_else(tmp_path):
    for path in ("explore.json", "today.json", "previews.json", "rules/keywords.json", "popular-cards/modern.json", "popular-cards/legacy.json", "breakouts/modern.json", "breakouts/legacy.json"):
        put(tmp_path, path)
    for path in (
        "movers/all.json", "movers/modern.json", "snapshots/modern.json", "archetypes/modern-izzet-prowess.json", "events/66753.json",
        "decks/7966104.json", "cards/lightning-bolt.json", "cards/index.json", "edh/commanders/atraxa.json", "index.json",
        "locator/singapore.json", "premier/schedule.json", "state/deck-ids.json", "state/deck-cards/modern.json",
        "popular-cards/readme.txt", "popular-cards/nested/modern.json", "explore.json.bak", "other/today.json", "breakouts.json",
        "rules/keywords.json.bak", "rules/other.json", "state/rules-keywords.json",
    ):
        put(tmp_path, path)
    write_manifest(tmp_path, NOW)
    assert list(listed(tmp_path)) == [
        "breakouts/legacy.json", "breakouts/modern.json", "explore.json", "popular-cards/legacy.json", "popular-cards/modern.json",
        "previews.json", "rules/keywords.json", "today.json",
    ]


def test_is_explore_path_names_exactly_the_explore_files():
    assert all(is_explore_path(path) for path in ("explore.json", "today.json", "previews.json", "rules/keywords.json", "popular-cards/modern.json", "breakouts/duel_commander.json"))
    assert not any(
        is_explore_path(path)
        for path in ("movers/all.json", "index.json", "snapshots/modern.json", "popular-cards/", "popular-cards/.json", "popular-cards/a/b.json", "breakouts/modern.txt", "state/explore-manifest.json", "explore-manifest.json", "rules/other.json", "rules/keywords.json.bak", "rules/", "")
    )


def test_a_file_the_run_did_not_write_keeps_the_entry_of_the_previous_manifest(tmp_path):
    old = "a" * 64
    put_state(tmp_path, {"explore.json": {"sha256": old}, "breakouts/legacy.json": {"sha256": old}, "popular-cards/modern.json": {"sha256": old}})
    body = put(tmp_path, "popular-cards/modern.json", '{"rewritten":true}')
    put(tmp_path, "breakouts/pauper.json", '{"new":true}')
    write_manifest(tmp_path, NOW)
    files = listed(tmp_path)
    assert files["explore.json"] == {"sha256": old}
    assert files["breakouts/legacy.json"] == {"sha256": old}
    assert files["popular-cards/modern.json"] == {"sha256": sha(body)}
    assert files["breakouts/pauper.json"] == {"sha256": sha(b'{"new":true}')}
    assert list(files) == sorted(files)


def test_the_previous_manifest_brings_only_explore_files_with_well_formed_hashes(tmp_path):
    good = "c" * 64
    put_state(tmp_path, {
        "today.json": {"sha256": good},
        "movers/all.json": {"sha256": good},
        "snapshots/modern.json": {"sha256": good},
        "breakouts/modern.json": {"sha256": good.upper()},
        "breakouts/legacy.json": {"sha256": "abc"},
        "breakouts/pauper.json": {"sha256": 5},
        "breakouts/vintage.json": {},
        "breakouts/premodern.json": "nope",
    })
    assert read_previous(tmp_path) == {"today.json": {"sha256": good}}


def test_the_previous_manifest_brings_the_keyword_rules_entry_when_the_run_wrote_no_rules(tmp_path):
    put_state(tmp_path, {"rules/keywords.json": {"sha256": "f" * 64}, "rules/other.json": {"sha256": "f" * 64}})
    assert read_previous(tmp_path) == {"rules/keywords.json": {"sha256": "f" * 64}}
    put(tmp_path, "today.json")
    write_manifest(tmp_path, NOW)
    assert listed(tmp_path)["rules/keywords.json"] == {"sha256": "f" * 64}


def test_a_rewritten_keyword_rules_file_is_hashed_over_its_previous_entry(tmp_path):
    put_state(tmp_path, {"rules/keywords.json": {"sha256": "f" * 64}})
    body = put(tmp_path, "rules/keywords.json", '{"schema":1,"keywords":{}}')
    write_manifest(tmp_path, NOW)
    assert listed(tmp_path) == {"rules/keywords.json": {"sha256": sha(body)}}


def test_extra_keys_of_a_previous_entry_are_not_carried_over(tmp_path):
    put_state(tmp_path, {"today.json": {"sha256": "d" * 64, "bytes": 12}})
    assert read_previous(tmp_path) == {"today.json": {"sha256": "d" * 64}}


def test_the_state_copy_is_byte_identical_to_the_published_file(tmp_path):
    put(tmp_path, "explore.json")
    put(tmp_path, "breakouts/modern.json")
    write_manifest(tmp_path, NOW)
    assert (tmp_path / STATE_PATH).read_bytes() == (tmp_path / PATH).read_bytes()
    assert STATE_PATH == "state/" + PATH


def test_the_next_run_carries_over_from_the_state_copy_the_run_before_wrote(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    body = put(first, "breakouts/modern.json", '{"format":"modern"}')
    put(first, "today.json")
    write_manifest(first, NOW)
    # The workflow downloads only state/, so the second run starts with the first's copy and one file.
    put(second, STATE_PATH, (first / STATE_PATH).read_text())
    rewritten = put(second, "today.json", '{"schema":1,"again":true}')
    write_manifest(second, NOW)
    assert listed(second) == {"breakouts/modern.json": {"sha256": sha(body)}, "today.json": {"sha256": sha(rewritten)}}


@pytest.mark.parametrize(
    "state",
    [None, b"", b"not json", b"[]", b'{"files":[]}', b'{"files":null}', b'{"schema":1}', b'{"files":{"today.json":null}}', b"\xff\xfe\x00"],
)
def test_a_missing_or_corrupt_state_file_starts_empty(tmp_path, state):
    body = put(tmp_path, "explore.json")
    if state is not None:
        (tmp_path / "state").mkdir()
        (tmp_path / STATE_PATH).write_bytes(state)
    assert read_previous(tmp_path) == {}
    assert write_manifest(tmp_path, NOW) == ["explore-manifest.json"]
    assert listed(tmp_path) == {"explore.json": {"sha256": sha(body)}}


def test_nothing_is_written_when_there_is_no_explore_file(tmp_path):
    put(tmp_path, "movers/all.json")
    put(tmp_path, "snapshots/modern.json")
    put(tmp_path, "index.json")
    assert write_manifest(tmp_path, NOW) == []
    assert not (tmp_path / PATH).exists() and not (tmp_path / STATE_PATH).exists()
    assert write_manifest(tmp_path / "missing", NOW) == []


def test_a_previous_manifest_alone_still_gives_a_manifest(tmp_path):
    put_state(tmp_path, {"today.json": {"sha256": "e" * 64}})
    assert write_manifest(tmp_path, NOW) == ["explore-manifest.json"]
    assert listed(tmp_path) == {"today.json": {"sha256": "e" * 64}}


def test_the_file_is_compact_with_sorted_keys_and_its_time(tmp_path):
    for path in ("today.json", "popular-cards/modern.json", "explore.json", "breakouts/legacy.json"):
        put(tmp_path, path)
    write_manifest(tmp_path, NOW)
    text = (tmp_path / PATH).read_text()
    assert ": " not in text and ", " not in text and "\n" not in text
    document = json.loads(text)
    assert list(document) == ["schema", "generated_at", "files"]
    assert document["schema"] == 1 and document["generated_at"] == "2026-10-04T19:52:10Z"
    assert list(document["files"]) == ["breakouts/legacy.json", "explore.json", "popular-cards/modern.json", "today.json"]
    assert text.startswith('{"schema":1,"generated_at":"2026-10-04T19:52:10Z","files":{"breakouts/legacy.json":{"sha256":"')


def test_the_time_is_utc_whatever_the_zone_it_is_given_in(tmp_path):
    put(tmp_path, "explore.json")
    zone = timezone(timedelta(hours=8))
    assert build_manifest(tmp_path, datetime(2026, 10, 5, 3, 52, 10, tzinfo=zone), {})["generated_at"] == "2026-10-04T19:52:10Z"


def test_a_full_feed_of_21_files_stays_small(tmp_path):
    put(tmp_path, "explore.json", "x" * 1000)
    put(tmp_path, "today.json", "y" * 1000)
    put(tmp_path, "rules/keywords.json", "z" * 1000)
    for format in FORMATS:
        put(tmp_path, f"popular-cards/{format}.json", format * 50)
        put(tmp_path, f"breakouts/{format}.json", format * 70)
    write_manifest(tmp_path, NOW)
    assert len(listed(tmp_path)) == 21
    assert (tmp_path / PATH).stat().st_size < 2350


def test_it_lists_the_explore_file_a_store_run_wrote_by_its_hash(tmp_path):
    from mtgmeta.models import Archetype, Event, EventResult, Meta
    from mtgmeta.store import SnapshotStore

    store = SnapshotStore(tmp_path, ["modern"], history_days=30, now=NOW)
    store.save_meta(Meta("modern", "30d", [Archetype("Eldrazi", 9.4, "modern-eldrazi", 648)]))
    store.save_event(Event("1", "Modern League 2026-10-03", "modern", datetime(2026, 10, 3, tzinfo=timezone.utc), [EventResult("p", "Eldrazi", "5-0", "1")], "url"))
    assert "explore.json" in store.finish()
    write_manifest(tmp_path, NOW)
    assert listed(tmp_path) == {"explore.json": {"sha256": sha((tmp_path / "explore.json").read_bytes())}}


def upload_lines():
    """Each `cp` of the upload step, as (line number, what it copies)."""
    lines = UPLOAD.read_text().splitlines()
    return {match.group(1): number for number, line in enumerate(lines) if (match := re.match(r"\s*cp (work/\S+) ", line))}


def test_the_workflow_uploads_the_manifest_after_the_files_it_lists_and_the_state_and_before_the_index():
    lines = upload_lines()
    manifest = lines["work/explore-manifest.json"]
    for before in ("work/popular-cards", "work/breakouts", "work/today.json", "work/rules/keywords.json", "work/explore.json", "work/state"):
        assert lines[before] < manifest, before
    assert manifest < lines["work/index.json"]
    assert lines["work/index.json"] == max(lines.values())


def test_the_workflow_uploads_the_manifest_only_when_there_is_one_with_a_minute_of_cache():
    lines = UPLOAD.read_text().splitlines()
    number = upload_lines()["work/explore-manifest.json"]
    assert lines[number - 1].strip() == "if [ -f work/explore-manifest.json ]; then"
    assert lines[number + 1].strip() == "fi"
    assert '"$R2/explore-manifest.json" --cache-control "public, max-age=60"' in lines[number]


def test_the_workflow_uploads_the_keyword_rules_only_when_the_run_wrote_them_like_the_other_json_files():
    lines = UPLOAD.read_text().splitlines()
    number = upload_lines()["work/rules/keywords.json"]
    assert lines[number - 1].strip() == "if [ -f work/rules/keywords.json ]; then"
    assert lines[number + 1].strip() == "fi"
    assert '"$R2/rules/keywords.json" --cache-control "public, max-age=300"' in lines[number]
    # The cp wrapper gives every upload the JSON content type.
    assert "--content-type application/json" in next(line for line in lines if line.strip().startswith("cp() {"))
    assert "rules/keywords.json" in UPLOAD.read_text().split("PUBLISH=0: nothing was uploaded")[1]


def written_after_each_step():
    """The functions main() adds to `written`, in the order it calls them."""
    return re.findall(r"written \+= (\w+)\(", inspect.getsource(entry.main))


def test_main_publishes_the_manifest_after_today_and_after_everything_else_it_writes():
    steps = written_after_each_step()
    assert steps.index("publish_localized") == steps.index("publish_today") + 1
    assert steps.index("publish_manifest") == steps.index("publish_localized") + 1
    assert steps[-1] == "publish_manifest" and steps.count("publish_manifest") == 1
    assert steps.count("publish_rules") == 1 and steps.index("publish_rules") < steps.index("publish_today")
    source = inspect.getsource(entry.main)
    assert source.index("publish_today(") < source.index("publish_manifest(") < source.index('logging.info(\n        "Done')


def test_publish_manifest_writes_the_files_and_names_the_one_published(tmp_path):
    put(tmp_path, "explore.json")
    report = SimpleNamespace(errors=[])
    assert entry.publish_manifest(tmp_path, report) == ["explore-manifest.json"]
    assert (tmp_path / PATH).exists() and report.errors == []


def test_publish_manifest_writes_nothing_and_says_nothing_when_there_is_no_explore_file(tmp_path):
    report = SimpleNamespace(errors=[])
    assert entry.publish_manifest(tmp_path, report) == []
    assert report.errors == []


def test_a_failure_in_publish_manifest_is_reported_and_does_not_stop_the_run(tmp_path, monkeypatch):
    import mtgmeta.manifest

    def fail(directory, now):
        raise OSError("disk full")

    monkeypatch.setattr(mtgmeta.manifest, "write_manifest", fail)
    report = SimpleNamespace(errors=[])
    assert entry.publish_manifest(tmp_path, report) == []
    assert report.errors == ["explore manifest: disk full"]
