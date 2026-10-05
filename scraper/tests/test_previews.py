import gzip
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from mtgmeta import movers as movers_module
from mtgmeta.previews import STATE, NewPrintings, pick, read_seen, write_seen
from mtgmeta.today import build_today, write_today
from tests.test_movers import encode

NOW = datetime(2026, 10, 4, 14, 3, tzinfo=timezone.utc)
TODAY = NOW.date()
LATER = "2026-11-20"  # after NOW: not released yet


def printing(name, set="trk", number="1", released=LATER, **extra):
    """A minimal Scryfall card: a paper printing of a normal card, upcoming unless `released` says otherwise, with a stable id from its name, set and number."""
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{set}/{number}/{name}")), "oracle_id": "o-" + name.lower().replace(" ", "-"),
        "name": name, "set": set, "set_name": "Set " + set.upper(), "set_type": "expansion", "collector_number": number,
        "released_at": released, "layout": "normal", "digital": False, "reprint": False, "games": ["paper"], **extra,
    }


def lair(name, set="sld", number="1", **extra):
    return printing(name, set=set, number=number, set_name="Secret Lair Drop", set_type="box", **extra)


def previewed(day, **extra):
    return {"preview": {"previewed_at": day, "source": "Mothership", "source_uri": "https://example.test/" + day, **extra}}


def watched(*cards, seen=("previous",)):
    """A NewPrintings that has watched `cards` go by, with the ids in `seen` known from the last run."""
    new = NewPrintings(set(seen))
    list(new.watch(cards))
    return new


def chosen(*cards):
    return pick(watched(*cards).cards, TODAY)


def ranking(*cards):
    """The names in the order they win the preview: each winner is taken out and the next is picked."""
    left, order = list(cards), []
    while left:
        winner = chosen(*left)
        if winner is None:
            break
        order.append(winner["name"])
        left = [card for card in left if card["name"] != winner["name"]]
    return order


def test_a_first_run_finds_nothing_new_and_saves_every_id_it_saw(tmp_path):
    stream = [printing("A"), printing("B", number="2"), printing("Token", layout="token")]
    new = NewPrintings(read_seen(tmp_path))
    assert new.seen is None
    list(new.watch(stream))
    assert new.cards == [] and new.complete
    assert build_today({}, None, NOW, new.cards)["preview"] == {"card": None}
    assert write_today(tmp_path, NOW, new) == ["today.json"]
    assert json.loads((tmp_path / "today.json").read_text())["preview"] == {"card": None}
    assert read_seen(tmp_path) == {card["id"] for card in stream}


def test_with_a_previous_state_a_printing_not_in_it_is_new_and_one_in_it_is_not():
    old, fresh = printing("Old"), printing("Fresh", number="2")
    new = watched(old, fresh, seen={old["id"]})
    assert [card["id"] for card in new.cards] == [fresh["id"]]
    assert new.ids == {old["id"], fresh["id"]}
    assert watched(old, seen={old["id"]}).cards == []


def test_each_run_finds_what_the_run_before_it_saved_and_then_moves_on(tmp_path):
    first, second = [printing("A"), printing("B", number="2")], [printing("A"), printing("B", number="2"), printing("C", number="3")]
    for stream, expected in ((first, None), (second, "C"), (second, None)):
        new = NewPrintings(read_seen(tmp_path))
        list(new.watch(stream))
        write_today(tmp_path, NOW, new)
        card = json.loads((tmp_path / "today.json").read_text())["preview"]["card"]
        assert (card and card["name"]) == expected
        assert read_seen(tmp_path) == {card["id"] for card in stream}


def test_watch_yields_every_card_unchanged_and_in_order_even_one_with_no_id():
    stream = [printing("A"), {"name": "No Id"}, printing("Token", layout="token"), printing("B", number="2")]
    new = NewPrintings({"previous"})
    out = list(new.watch(iter(stream)))
    assert len(out) == len(stream) and all(card is original for card, original in zip(out, stream))
    assert new.ids == {stream[0]["id"], stream[2]["id"], stream[3]["id"]}


def test_a_new_printing_keeps_only_what_the_pick_needs():
    new = watched(printing("Heavy", prices={"usd": "1.00"}, image_uris={"png": "x"}, legalities={"modern": "legal"}, **previewed("2026-10-01")))
    assert set(new.cards[0]) == {
        "id", "name", "oracle_id", "set", "set_name", "collector_number", "released_at", "reprint", "preview",
    }
    assert "preview" not in watched(printing("Plain")).cards[0]


def test_a_released_printing_next_to_an_upcoming_one_loses_whatever_its_preview_release_or_kind():
    cards = [
        printing("Other", set="mh3", released="2026-10-01", **previewed("2026-10-02")),
        lair("Drop", released="2026-10-03"),
        printing("Headliner", set="new", released=LATER, reprint=True),
    ]
    assert chosen(*cards)["name"] == "Headliner"
    assert ranking(*cards) == ["Headliner"]


def test_a_secret_lair_printing_is_no_different_from_any_other_and_a_released_one_is_not_a_preview():
    assert chosen(lair("Drop", released="2026-10-03")) is None
    assert chosen(lair("Upcoming Drop", released=LATER))["name"] == "Upcoming Drop"
    assert chosen(printing("Countdown", set="slc", set_name="Secret Lair Countdown Kit", set_type="box", released="2026-10-03")) is None


def test_a_card_released_today_is_not_upcoming_and_tomorrow_is_and_the_day_is_the_utc_day():
    assert chosen(printing("Today", set="new", released="2026-10-04")) is None
    assert chosen(printing("Tomorrow", set="new", released="2026-10-05"))["name"] == "Tomorrow"
    # 22:00 on October 4 at UTC-8 is already October 5 in UTC, so a card released on October 5 is released that day.
    late = datetime(2026, 10, 4, 22, tzinfo=timezone(timedelta(hours=-8)))
    new = watched(printing("Fifth", set="new", released="2026-10-05"))
    assert build_today({}, None, late, new.cards)["preview"] == {"card": None}
    assert build_today({}, None, NOW, new.cards)["preview"]["card"]["name"] == "Fifth"


def test_only_released_new_printings_give_no_preview(tmp_path):
    new = watched(
        printing("Yesterday", set="aaa", released="2026-10-03"), printing("Today", set="bbb", released="2026-10-04"),
        printing("Long Ago", set="ccc", released="2025-01-01"), lair("Drop", released="2026-09-01"),
    )
    assert len(new.cards) == 4 and pick(new.cards, TODAY) is None
    assert write_today(tmp_path, NOW, new) == ["today.json"]
    assert json.loads((tmp_path / "today.json").read_text())["preview"] == {"card": None}
    assert read_seen(tmp_path) == new.ids


@pytest.mark.parametrize("released", [None, "", "soon", "2026-13-45", "2026-10", 20261120], ids=repr)
def test_a_printing_with_a_missing_or_unparseable_release_date_is_not_a_preview(released):
    assert chosen(printing("Undated", set="new", released=released)) is None
    assert chosen(printing("Undated", set="new", released=released), printing("Dated", set="zzz", released=LATER))["name"] == "Dated"
    assert chosen({k: v for k, v in printing("Gone", set="new", released=LATER).items() if k != "released_at"}) is None


def test_with_no_new_printings_there_is_no_card():
    assert pick([], TODAY) is None
    assert chosen() is None


def test_among_upcoming_cards_a_first_printing_beats_a_reprint_even_with_a_newer_preview():
    first = printing("First", set="new", released=LATER)
    reprint = printing("Reprint", set="new", released=LATER, reprint=True, **previewed("2026-10-03"))
    assert ranking(reprint, first) == ["First", "Reprint"]


def test_among_upcoming_cards_a_previewed_card_beats_an_unpreviewed_one_and_the_newest_preview_wins():
    plain = printing("Plain", set="aaa", released="2026-12-31")
    older = printing("Older", set="zzz", released=LATER, **previewed("2026-09-20"))
    newer = printing("Newer", set="zzz", released=LATER, **previewed("2026-10-02"))
    assert ranking(plain, older, newer) == ["Newer", "Older", "Plain"]


def test_among_upcoming_cards_without_previews_the_newest_release_wins():
    assert ranking(printing("Soon", set="a", released="2026-10-20"), printing("Later", set="b", released="2026-12-01")) == ["Later", "Soon"]


def test_ties_go_to_the_lower_set_code_then_the_lower_collector_number():
    def tied(*cards):
        return ranking(*(printing(name, set=set, number=number, released=LATER) for name, set, number in cards))

    assert tied(("Zed", "zzz", "1"), ("Abe", "aaa", "1")) == ["Abe", "Zed"]
    assert tied(("Ten", "trk", "10"), ("Nine", "trk", "9"), ("TenA", "trk", "10a"), ("Hundred", "trk", "100")) == ["Nine", "Ten", "TenA", "Hundred"]
    assert tied(("Starred", "trk", "★"), ("Nine", "trk", "9")) == ["Starred", "Nine"]


SKIPPED = {
    "token layout": {"layout": "token"},
    "double-faced token": {"layout": "double_faced_token"},
    "art series": {"layout": "art_series"},
    "emblem": {"layout": "emblem"},
    "token set": {"set_type": "token"},
    "memorabilia": {"set_type": "memorabilia"},
    "minigame": {"set_type": "minigame"},
    "digital only": {"digital": True, "games": ["mtgo"]},
    "oversized": {"oversized": True},
}


@pytest.mark.parametrize("extra", SKIPPED.values(), ids=list(SKIPPED))
def test_what_is_not_a_paper_card_never_becomes_a_preview_but_is_still_recorded(extra, tmp_path):
    skipped = printing("Skipped", set="new", released=LATER, **extra)
    real = printing("Real", set="zzz", number="2")
    new = watched(skipped, real)
    assert [card["name"] for card in new.cards] == ["Real"]
    assert chosen(skipped) is None
    assert skipped["id"] in new.ids
    new.save(tmp_path)
    assert skipped["id"] in read_seen(tmp_path)


def test_a_card_with_no_name_is_never_a_preview():
    assert watched({**printing("Nameless"), "name": ""}).cards == []
    assert watched({"id": "x", "set": "trk", "released_at": LATER}).cards == []


def test_the_published_card_has_these_keys_in_this_order():
    card = chosen(printing("Fresh Face", set="trk", number="7", released=LATER))
    assert list(card) == ["name", "oracle_id", "scryfall_id", "set", "set_name", "released_at"]
    assert card == {
        "name": "Fresh Face", "oracle_id": "o-fresh-face", "scryfall_id": printing("Fresh Face", number="7")["id"], "set": "trk",
        "set_name": "Set TRK", "released_at": LATER,
    }


def test_the_preview_credit_is_published_only_when_scryfall_has_it():
    full = chosen(printing("Full", released=LATER, **previewed("2026-10-01")))
    assert list(full) == ["name", "oracle_id", "scryfall_id", "set", "set_name", "released_at", "previewed_at", "source", "source_uri"]
    assert (full["previewed_at"], full["source"], full["source_uri"]) == ("2026-10-01", "Mothership", "https://example.test/2026-10-01")
    partial = chosen(printing("Partial", released=LATER, preview={"previewed_at": "2026-10-01", "source": "", "source_uri": None, "other": 1}))
    assert list(partial)[6:] == ["previewed_at"]
    assert not {"previewed_at", "source", "source_uri", "preview"} & set(chosen(printing("None")))
    assert not {"previewed_at", "source", "source_uri", "preview"} & set(chosen(printing("Empty", preview={})))


def test_the_oracle_id_comes_from_the_first_face_when_the_card_has_none():
    card = printing("Front // Back", oracle_id=None, card_faces=[{"oracle_id": "o-front"}, {"oracle_id": "o-back"}])
    assert chosen(card)["oracle_id"] == "o-front"
    assert chosen(printing("Plain"))["oracle_id"] == "o-plain"


def test_the_state_round_trips_and_is_a_gzipped_sorted_compact_json_array(tmp_path):
    write_seen(tmp_path, {"b-2", "a-1", "c-3"})
    raw = (tmp_path / STATE).read_bytes()
    assert gzip.decompress(raw) == b'["a-1","b-2","c-3"]'
    assert raw[4:8] == bytes(4)  # no time in the gzip header
    assert read_seen(tmp_path) == {"a-1", "b-2", "c-3"}
    # The same ids give the same bytes, whatever order they come in.
    write_seen(tmp_path, ["c-3", "a-1", "b-2"])
    assert (tmp_path / STATE).read_bytes() == raw


def test_a_missing_state_file_is_none_and_not_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert read_seen(tmp_path) is None
    assert caplog.records == []


def test_a_state_file_that_cannot_be_read_is_none_with_a_warning_not_an_exception(tmp_path, caplog):
    good = gzip.compress(b'["a-1","b-2"]')
    broken = {
        "not gzip": b"nope",
        "empty file": b"",
        "cut short": good[: len(good) // 2],
        "bad body": good[:10] + b"\xff" * 20,
        "not json": gzip.compress(b"{oops"),
        "not a list": gzip.compress(b'{"a-1": 1}'),
        "not ids": gzip.compress(b"[[1],[2]]"),
    }
    (tmp_path / "state").mkdir()
    for label, data in broken.items():
        (tmp_path / STATE).write_bytes(data)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert read_seen(tmp_path) is None, label
        assert len(caplog.records) == 1, label
    (tmp_path / STATE).write_bytes(gzip.compress(b"[]"))
    assert read_seen(tmp_path) is None


def test_write_seen_creates_the_state_directory(tmp_path):
    assert not (tmp_path / "state").exists()
    write_seen(tmp_path, ["a-1"])
    assert (tmp_path / STATE).exists()


def failing(cards):
    yield from cards
    raise OSError("connection reset")


def test_a_stream_that_fails_partway_is_not_complete_and_leaves_the_state_alone(tmp_path):
    write_seen(tmp_path, [printing("Old")["id"]])
    before = (tmp_path / STATE).read_bytes()
    new = NewPrintings(read_seen(tmp_path))
    with pytest.raises(OSError):
        list(new.watch(failing([printing("A"), printing("B", number="2")])))
    assert not new.complete
    assert len(new.cards) == 2  # found, but a partial read must not publish or save anything
    assert write_today(tmp_path, NOW, new) == ["today.json"]
    assert json.loads((tmp_path / "today.json").read_text())["preview"] == {"card": None}
    assert (tmp_path / STATE).read_bytes() == before


def test_a_stream_the_consumer_stops_reading_is_not_complete():
    new = NewPrintings({"previous"})
    stream = new.watch(iter([printing("A"), printing("B", number="2")]))
    next(stream)
    assert not new.complete


def test_without_printings_the_state_is_left_alone_and_none_is_made(tmp_path):
    assert write_today(tmp_path, NOW) == ["today.json"]
    assert json.loads((tmp_path / "today.json").read_text())["preview"] == {"card": None}
    assert not (tmp_path / "state").exists()
    write_seen(tmp_path, ["a-1"])
    before = (tmp_path / STATE).read_bytes()
    write_today(tmp_path, NOW)
    write_today(tmp_path, NOW, None)
    assert (tmp_path / STATE).read_bytes() == before


def test_the_state_moves_on_only_after_the_file_is_written(tmp_path):
    (tmp_path / "today.json").write_text("{}")
    write_seen(tmp_path, ["old"])
    new = watched(printing("Fresh"), seen={"old"})
    new.complete = False
    write_today(tmp_path, NOW, new)
    assert read_seen(tmp_path) == {"old"}
    new.complete = True
    write_today(tmp_path, NOW, new)
    assert read_seen(tmp_path) == new.ids
    assert json.loads((tmp_path / "today.json").read_text())["preview"]["card"]["name"] == "Fresh"


def test_movers_passes_scryfalls_stream_through_watch(monkeypatch):
    stream = [printing("A"), printing("B", number="2"), printing("Token", layout="token")]
    monkeypatch.setattr(movers_module, "_bulk_download_uri", lambda url: "https://example.test/default-cards.jsonl")
    monkeypatch.setattr(movers_module, "bulk_cards", lambda download: iter(stream))
    monkeypatch.setattr(movers_module, "fetch_history", lambda url: encode([]))
    new = NewPrintings({stream[0]["id"]})
    files = movers_module.movers("https://example.test/history.bin.gz", NOW, new.watch)
    assert new.complete and new.ids == {card["id"] for card in stream}
    assert [card["name"] for card in new.cards] == ["B"]
    assert files == movers_module.movers("https://example.test/history.bin.gz", NOW)
