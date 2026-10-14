import gzip
import json
import uuid
from datetime import datetime, timedelta, timezone

from mtgmeta.previews import (
    FIRST_SEEN_STATE, KEEP_DAYS, WINDOW_DAYS, NewPrintings, build_previews, read_first_seen, read_seen, write_first_seen, write_seen,
)
from mtgmeta.today import write_today

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
LATER = "2026-11-20"


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def printing(name, set="trk", number="1", released=LATER, **extra):
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{set}/{number}/{name}")), "oracle_id": "o-" + name.lower().replace(" ", "-"),
        "name": name, "set": set, "set_name": "Set " + set.upper(), "set_type": "expansion", "collector_number": number,
        "released_at": released, "layout": "normal", "digital": False, "reprint": False, "games": ["paper"], **extra,
    }


def previewed(when):
    return {"preview": {"previewed_at": when, "source": "Mothership", "source_uri": "https://example.test/" + when}}


def run(directory, stream, now=NOW):
    """One whole run over `stream`, as __main__ does it: read the state, watch the stream, write today.json, previews.json and the state."""
    new = NewPrintings(read_seen(directory), read_first_seen(directory), now.date())
    list(new.watch(stream))
    write_today(directory, now, new)
    return json.loads((directory / "previews.json").read_text())


def names(document):
    return [card["name"] for card in document["cards"]]


def test_first_seen_is_recorded_on_the_run_that_finds_a_printing_new_and_kept_after_that(tmp_path):
    old = printing("Old", number="1")
    run(tmp_path, [old])
    later = [old, printing("Fresh", number="2")]
    first = run(tmp_path, later, NOW)
    assert [(card["name"], card["first_seen"]) for card in first["cards"]] == [("Fresh", day(0))]

    tomorrow = NOW + timedelta(days=1)
    second = run(tmp_path, later + [printing("Newer", number="3")], tomorrow)
    assert [(card["name"], card["first_seen"]) for card in second["cards"]] == [("Newer", day(1)), ("Fresh", day(0))]
    assert read_first_seen(tmp_path) == {printing("Fresh", number="2")["id"]: day(0), printing("Newer", number="3")["id"]: day(1)}
    assert read_seen(tmp_path) == {card["id"] for card in later + [printing("Newer", number="3")]}


def test_a_second_run_the_same_day_keeps_the_list(tmp_path):
    run(tmp_path, [printing("Old")])
    stream = [printing("Old"), printing("Fresh", number="2")]
    assert names(run(tmp_path, stream)) == ["Fresh"]
    assert names(run(tmp_path, stream, NOW + timedelta(hours=9))) == ["Fresh"]


def test_the_document_has_its_schema_the_card_fields_and_a_count(tmp_path):
    run(tmp_path, [printing("Old")])
    document = run(tmp_path, [printing("Old"), printing("Fresh", number="2", **previewed(day(-1))), printing("Quiet", number="3")])
    assert {key: document[key] for key in ("schema", "generated_at", "window_days", "count")} == {
        "schema": 1, "generated_at": "2026-10-14T06:00:00Z", "window_days": 7, "count": 2,
    }
    fresh, quiet = document["cards"]
    assert list(fresh) == ["name", "oracle_id", "scryfall_id", "set", "set_name", "collector_number", "released_at", "first_seen", "previewed_at"]
    assert fresh == {
        "name": "Fresh", "oracle_id": "o-fresh", "scryfall_id": printing("Fresh", number="2")["id"], "set": "trk", "set_name": "Set TRK",
        "collector_number": "2", "released_at": LATER, "first_seen": day(0), "previewed_at": day(-1),
    }
    assert quiet["previewed_at"] is None


def test_the_window_includes_the_seventh_day_and_drops_the_eighth(tmp_path):
    cards = [printing(f"Day {age}", number=str(age)) for age in range(9)]
    write_seen(tmp_path, [card["id"] for card in cards])
    write_first_seen(tmp_path, {card["id"]: day(-age) for age, card in enumerate(cards)})
    document = run(tmp_path, cards)
    assert WINDOW_DAYS == 7
    assert names(document) == [f"Day {age}" for age in range(WINDOW_DAYS + 1)]
    assert "Day 8" not in names(document)


def test_a_card_ages_out_of_the_list_as_the_days_go_by(tmp_path):
    run(tmp_path, [printing("Old")])
    stream = [printing("Old"), printing("Fresh", number="2")]
    run(tmp_path, stream)
    for age, expected in ((WINDOW_DAYS, ["Fresh"]), (WINDOW_DAYS + 1, [])):
        assert names(run(tmp_path, stream, NOW + timedelta(days=age))) == expected


def test_only_cards_released_after_today_are_listed_and_the_release_date_does_not_order_them(tmp_path):
    run(tmp_path, [printing("Old")])
    stream = [
        printing("Old"),
        printing("Soon", set="b", number="1", released=day(1)),
        printing("Far", set="a", number="1", released="2027-03-01"),
        printing("Today", set="c", number="1", released=day(0)),
        printing("Yesterday", set="d", number="1", released=day(-1)),
        printing("Undated", set="e", number="1", released=None),
        printing("Garbage", set="f", number="1", released="soon"),
    ]
    assert names(run(tmp_path, stream)) == ["Far", "Soon"]
    assert names(run(tmp_path, list(reversed(stream)))) == ["Far", "Soon"]
    swapped = [printing("Old"), printing("Soon", set="a", number="1", released=day(1)), printing("Far", set="b", number="1", released="2027-03-01")]
    assert names(run(tmp_path, swapped)) == ["Soon", "Far"]


def test_a_card_released_since_it_was_first_seen_leaves_the_list(tmp_path):
    run(tmp_path, [printing("Old")])
    run(tmp_path, [printing("Old"), printing("Fresh", number="2", released=day(2))])
    assert names(run(tmp_path, [printing("Old"), printing("Fresh", number="2", released=day(2))], NOW + timedelta(days=1))) == ["Fresh"]
    assert names(run(tmp_path, [printing("Old"), printing("Fresh", number="2", released=day(2))], NOW + timedelta(days=2))) == []


def test_the_order_is_first_seen_then_previewed_then_set_and_number():
    def tracked(name, first, previewed_at=None, set="trk", number="1", released=LATER):
        return {
            "id": "id-" + name, "name": name, "set": set, "collector_number": number, "released_at": released, "first_seen": first,
            **({"preview": {"previewed_at": previewed_at}} if previewed_at else {}),
        }

    cards = [
        tracked("Old Seen", day(-3), day(-1), released="2026-10-20"),
        tracked("Seen Today B", day(0), day(-2), set="b"),
        tracked("Seen Today Newest Preview", day(0), day(-1), set="z", released="2027-06-01"),
        tracked("Seen Today No Preview", day(0), None, set="a"),
        tracked("Seen Today A10", day(0), day(-2), set="a", number="10"),
        tracked("Seen Today A9", day(0), day(-2), set="a", number="9"),
    ]
    expected = ["Seen Today Newest Preview", "Seen Today A9", "Seen Today A10", "Seen Today B", "Seen Today No Preview", "Old Seen"]
    assert names(build_previews(cards, NOW)) == expected
    assert names(build_previews(list(reversed(cards)), NOW)) == expected


def test_the_bytes_are_the_same_for_the_same_input(tmp_path):
    stream = [printing("Old"), printing("A", number="2"), printing("B", number="3", **previewed(day(-1)))]
    run(tmp_path, [printing("Old")])
    first = run(tmp_path, stream)
    body = (tmp_path / "previews.json").read_bytes()
    state = (tmp_path / FIRST_SEEN_STATE).read_bytes()
    run(tmp_path, stream)
    assert (tmp_path / "previews.json").read_bytes() == body and (tmp_path / FIRST_SEEN_STATE).read_bytes() == state
    assert first["count"] == 2


# ---- Bootstrap


def test_the_bootstrap_makes_every_existing_printing_old_except_unreleased_ones_previewed_in_the_window(tmp_path):
    stream = [
        printing("Old Released", number="1", released="2026-01-01"),
        printing("Old Upcoming Unpreviewed", number="2"),
        printing("Old Upcoming Stale Preview", number="3", **previewed(day(-8))),
        printing("Previewed Yesterday", number="4", **previewed(day(-1))),
        printing("Previewed A Week Ago", number="5", **previewed(day(-7))),
        printing("Previewed Today", number="6", **previewed(day(0))),
        printing("Previewed Released", number="7", released=day(-2), **previewed(day(-3))),
        printing("Previewed Future", number="8", **previewed(day(2))),
        printing("Token Previewed", number="9", layout="token", **previewed(day(-1))),
        printing("Digital Previewed", number="10", digital=True, **previewed(day(-1))),
    ]
    assert read_seen(tmp_path) is None and read_first_seen(tmp_path) is None
    document = run(tmp_path, stream)
    assert [(card["name"], card["first_seen"]) for card in document["cards"]] == [
        ("Previewed Today", day(0)), ("Previewed Yesterday", day(-1)), ("Previewed A Week Ago", day(-7)),
    ]
    assert read_seen(tmp_path) == {card["id"] for card in stream}
    assert set(read_first_seen(tmp_path).values()) == {day(0), day(-1), day(-7)}


def test_after_the_bootstrap_old_printings_stay_old_and_a_preview_date_no_longer_counts(tmp_path):
    stream = [printing("Old", number="1"), printing("Previewed", number="2", **previewed(day(-2)))]
    assert names(run(tmp_path, stream)) == ["Previewed"]
    tomorrow = NOW + timedelta(days=1)
    assert names(run(tmp_path, stream + [printing("Brand New", number="3", **previewed(day(-30)))], tomorrow)) == ["Brand New", "Previewed"]
    assert [card["first_seen"] for card in json.loads((tmp_path / "previews.json").read_text())["cards"]] == [day(1), day(-2)]


def test_a_bootstrap_with_nothing_to_list_still_saves_an_empty_first_seen_so_the_next_run_is_not_a_bootstrap(tmp_path):
    old = printing("Old")
    assert names(run(tmp_path, [old])) == []
    assert read_first_seen(tmp_path) == {}
    late = printing("Late Preview", number="2", **previewed(day(0)))
    assert names(run(tmp_path, [old, late], NOW + timedelta(days=1))) == ["Late Preview"]


def test_with_ids_saved_but_no_first_seen_new_printings_are_dated_today_and_old_ones_use_their_preview(tmp_path):
    old, previewed_old = printing("Old", number="1"), printing("Previewed Old", number="2", **previewed(day(-3)))
    write_seen(tmp_path, [old["id"], previewed_old["id"]])
    fresh = printing("Fresh", number="3", **previewed(day(-5)))
    document = run(tmp_path, [old, previewed_old, fresh])
    assert [(card["name"], card["first_seen"]) for card in document["cards"]] == [("Fresh", day(0)), ("Previewed Old", day(-3))]


def test_an_unreadable_first_seen_file_is_a_bootstrap(tmp_path, caplog):
    write_seen(tmp_path, ["x"])
    for content in (b"not gzip", gzip.compress(b"[1,2]"), gzip.compress(b"nope")):
        (tmp_path / FIRST_SEEN_STATE).write_bytes(content)
        assert read_first_seen(tmp_path) is None
    (tmp_path / FIRST_SEEN_STATE).write_bytes(gzip.compress(json.dumps({"ok": day(-1), "bad": "yesterday", "worse": 5}).encode()))
    assert read_first_seen(tmp_path) == {"ok": day(-1)}


# ---- Pruning


def test_entries_older_than_the_keep_days_are_pruned_but_those_printings_stay_old(tmp_path):
    ancient, recent = printing("Ancient", number="1"), printing("Recent", number="2")
    write_seen(tmp_path, [ancient["id"], recent["id"]])
    write_first_seen(tmp_path, {ancient["id"]: day(-KEEP_DAYS - 1), recent["id"]: day(-KEEP_DAYS)})
    assert names(run(tmp_path, [ancient, recent])) == []
    assert read_first_seen(tmp_path) == {recent["id"]: day(-KEEP_DAYS)}
    assert names(run(tmp_path, [ancient, recent], NOW + timedelta(days=1))) == []
    assert read_first_seen(tmp_path) == {}
    assert ancient["id"] in read_seen(tmp_path)


def test_entries_for_printings_released_long_ago_or_gone_from_scryfall_are_pruned(tmp_path):
    long_ago = printing("Long Ago", number="1", released=day(-KEEP_DAYS - 1))
    just_out = printing("Just Out", number="2", released=day(-KEEP_DAYS))
    vanished = printing("Vanished", number="3")
    write_seen(tmp_path, [long_ago["id"], just_out["id"], vanished["id"]])
    write_first_seen(tmp_path, {card["id"]: day(-1) for card in (long_ago, just_out, vanished)})
    run(tmp_path, [long_ago, just_out])
    assert read_first_seen(tmp_path) == {just_out["id"]: day(-1)}


def test_a_new_printing_released_long_ago_is_not_recorded(tmp_path):
    run(tmp_path, [printing("Old")])
    run(tmp_path, [printing("Old"), printing("Reissue", number="2", released=day(-400))])
    assert read_first_seen(tmp_path) == {}


def test_pruning_never_makes_an_old_printing_new_because_newness_comes_from_the_ids(tmp_path):
    stream = [printing("Old"), printing("A", number="2")]
    run(tmp_path, [printing("Old")])
    run(tmp_path, stream)
    for age in range(1, KEEP_DAYS + 5):
        listed = names(run(tmp_path, stream, NOW + timedelta(days=age)))
        assert listed == (["A"] if age <= WINDOW_DAYS else [])
    assert read_first_seen(tmp_path) == {}
    assert names(run(tmp_path, stream, NOW + timedelta(days=KEEP_DAYS + 6))) == []


# ---- Eligibility


def test_the_list_uses_the_same_eligibility_as_the_preview_pick(tmp_path):
    run(tmp_path, [printing("Old")])
    stream = [
        printing("Old"),
        printing("Real", number="1"),
        printing("Token", number="2", layout="token"),
        printing("Art", number="3", layout="art_series"),
        printing("Emblem", number="4", layout="emblem"),
        printing("Memorabilia", number="5", set_type="memorabilia"),
        printing("Minigame", number="6", set_type="minigame"),
        printing("Token Set", number="7", set_type="token"),
        printing("Oversized", number="8", oversized=True),
        printing("Digital", number="9", digital=True),
        {**printing("Unnamed", number="10"), "name": ""},
        {k: v for k, v in printing("No Id", number="11").items() if k != "id"},
        printing("Reprint", number="12", reprint=True),
    ]
    assert names(run(tmp_path, stream)) == ["Real", "Reprint"]
    assert set(read_first_seen(tmp_path)) == {printing("Real", number="1")["id"], printing("Reprint", number="12", reprint=True)["id"]}


def test_a_partial_read_saves_nothing_and_publishes_no_previews(tmp_path):
    run(tmp_path, [printing("Old")])
    before = {path.name: path.read_bytes() for path in (tmp_path / "state").iterdir()}
    new = NewPrintings(read_seen(tmp_path), read_first_seen(tmp_path), TODAY)
    stream = new.watch(iter([printing("Old"), printing("Fresh", number="2")]))
    next(stream)
    next(stream)
    (tmp_path / "previews.json").unlink()
    assert write_today(tmp_path, NOW, new) == ["today.json"]
    assert not (tmp_path / "previews.json").exists()
    assert {path.name: path.read_bytes() for path in (tmp_path / "state").iterdir() if path.name in before} == before


def test_without_a_watched_stream_previews_json_is_not_written(tmp_path):
    assert write_today(tmp_path, NOW) == ["today.json"]
    assert not (tmp_path / "previews.json").exists()
    assert not (tmp_path / FIRST_SEEN_STATE).exists()
