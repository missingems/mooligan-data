import io
import json
import urllib.error
from datetime import datetime, timezone

import pytest
from PIL import Image

import mtgmeta.__main__ as entry
import mtgmeta.settints as settints
from mtgmeta.models import RunReport
from mtgmeta.settints import (
    ART_PATH, SETS_URL, build, dominant, read_state, readable, root_of, to_hex, tint_of, write_set_tints,
)

NOW = datetime(2026, 10, 23, 14, 10, 0, tzinfo=timezone.utc)
PUBLISHED_ART = "https://data.example/sets/art.json"
TRK_ART = "https://images.ctfassets.net/x/trk/trk_art.jpg"
SEARCH = "https://api.scryfall.com/cards/search?q=e%3A{code}%20order%3Aedhrec&unique=cards"


def picture(*colours, fmt="PNG"):
    """A picture of horizontal stripes, one per colour."""
    image = Image.new("RGB", (64, 64 * len(colours)))
    for index, colour in enumerate(colours):
        image.paste(colour, (0, 64 * index, 64, 64 * (index + 1)))
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


def cards(art_crop, faces=False):
    card = {"card_faces": [{"image_uris": {"art_crop": art_crop}}, {}]} if faces else {"image_uris": {"art_crop": art_crop}}
    return json.dumps({"object": "list", "data": [card]}).encode()


def scryfall(*sets):
    data = []
    for code, parent, count in sets:
        row = {"code": code, "name": code.upper(), "card_count": count}
        if parent:
            row["parent_set_code"] = parent
        data.append(row)
    return json.dumps({"object": "list", "data": data}).encode()


SETS = scryfall(("trk", None, 300), ("trc", "trk", 50), ("ttrc", "trc", 10), ("abc", None, 5), ("dfc", None, 2), ("old", None, 0), ("gone", None, 4), ("tabc", "abc", 1))


def art_document(**urls):
    return json.dumps({"schema": 1, "sets": {code: {"url": url, "width": 1200, "height": 630} for code, url in urls.items()}}).encode()


class Net:
    """Stands in for Scryfall, Wizards' CDN and the published data: pictures and JSON by URL, and a record of what was asked for."""

    def __init__(self, sets=SETS):
        self.files = {
            SETS_URL: sets,
            PUBLISHED_ART: art_document(trk=TRK_ART),
            TRK_ART + "?w=96": picture((200, 40, 40)),
            SEARCH.format(code="abc"): cards("https://cards.example/abc.jpg"),
            "https://cards.example/abc.jpg": picture((40, 40, 200)),
            SEARCH.format(code="dfc"): cards("https://cards.example/dfc.jpg", faces=True),
            "https://cards.example/dfc.jpg": picture((40, 200, 40)),
            SEARCH.format(code="gone"): urllib.error.HTTPError("u", 404, "Not Found", {}, None),
        }
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        found = self.files[url]
        if isinstance(found, Exception):
            raise found
        return found


def run(tmp_path, net):
    return write_set_tints(tmp_path, NOW, net, PUBLISHED_ART)


def tints(tmp_path):
    return json.loads((tmp_path / "sets" / "tints.json").read_text())


def test_a_solid_colour_is_its_own_dominant_colour():
    assert dominant(Image.open(io.BytesIO(picture((255, 0, 0))))) == pytest.approx((1.0, 0.0, 0.0), abs=0.01)
    assert dominant(Image.open(io.BytesIO(picture((10, 120, 220))))) == pytest.approx((10 / 255, 120 / 255, 220 / 255), abs=0.01)


def test_the_hue_with_the_most_saturation_and_brightness_wins():
    image = Image.open(io.BytesIO(picture((0, 0, 255), (0, 0, 255), (0, 0, 255), (255, 0, 0))))
    assert dominant(image) == pytest.approx((0.0, 0.0, 1.0), abs=0.01)


def test_greys_and_darks_do_not_count_and_a_picture_of_them_is_its_mean():
    mixed = Image.open(io.BytesIO(picture((128, 128, 128), (20, 20, 20), (255, 255, 255), (0, 200, 0))))
    red, green, blue = dominant(mixed)
    assert green > 0.7 and red < 0.1 and blue < 0.1
    grey = Image.open(io.BytesIO(picture((100, 100, 100), (200, 200, 200))))
    assert dominant(grey) == pytest.approx((150 / 255,) * 3, abs=0.01)
    dark = Image.open(io.BytesIO(picture((20, 0, 0))))
    assert dominant(dark) == pytest.approx((20 / 255, 0.0, 0.0), abs=0.01)


def luminance(colour):
    linear = [settints.decode(x) for x in colour]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_a_light_colour_is_made_darker_and_a_dark_one_lighter_until_a_white_symbol_reads():
    assert luminance(readable((1.0, 1.0, 0.6))) == pytest.approx(0.24, abs=1e-6)
    assert luminance(readable((0.05, 0.02, 0.1))) == pytest.approx(0.06, abs=1e-6)
    inside = (0.5, 0.2, 0.3)
    assert luminance(inside) == pytest.approx(luminance(readable(inside)), abs=1e-6)
    assert readable(inside) == pytest.approx(inside, abs=1e-6)


def test_black_becomes_a_dark_grey_and_the_hue_is_kept_when_clamping():
    assert readable((0.0, 0.0, 0.0)) == (0.2, 0.2, 0.24)
    red, green, blue = readable((1.0, 0.8, 0.0))
    assert red > green > blue


def test_a_colour_is_written_as_sRGB_hex():
    assert to_hex((1.0, 0.5, 0.0)) == "#ff8000"
    assert to_hex((0.0, 0.0, 0.0)) == "#000000"
    assert tint_of(picture((60, 60, 200))) == to_hex(readable((60 / 255, 60 / 255, 200 / 255)))


def test_the_file_has_the_main_sets_colour_and_each_child_has_its_roots(tmp_path):
    assert run(tmp_path, Net()) == ["sets/tints.json"]
    document = tints(tmp_path)
    assert document["schema"] == 1 and document["generated_at"] == "2026-10-23T14:10:00Z"
    assert list(document["sets"]) == sorted(document["sets"])
    assert document["sets"]["trk"]["source"] == "wizards" and document["sets"]["abc"]["source"] == "card" and document["sets"]["dfc"]["source"] == "card"
    assert {code: tint["source"] for code, tint in document["sets"].items() if tint["source"] == "parent"} == {"trc": "parent", "ttrc": "parent", "tabc": "parent"}
    assert all(set(tint) == {"tint", "source"} for tint in document["sets"].values())


def test_the_exact_shape_of_the_file(tmp_path):
    run(tmp_path, Net())
    red = tint_of(picture((200, 40, 40)))
    blue = tint_of(picture((40, 40, 200)))
    green = tint_of(picture((40, 200, 40)))
    assert tints(tmp_path) == {
        "schema": 1,
        "generated_at": "2026-10-23T14:10:00Z",
        "sets": {
            "abc": {"tint": blue, "source": "card"},
            "dfc": {"tint": green, "source": "card"},
            "tabc": {"tint": blue, "source": "parent"},
            "trc": {"tint": red, "source": "parent"},
            "trk": {"tint": red, "source": "wizards"},
            "ttrc": {"tint": red, "source": "parent"},
        },
    }


def test_a_grandchild_has_the_colour_of_the_root_through_a_two_level_chain():
    sets = [{"code": "root"}, {"code": "mid", "parent_set_code": "root"}, {"code": "leaf", "parent_set_code": "mid"}, {"code": "orphan", "parent_set_code": "nowhere"}]
    state = {"root": {"source": "card", "url": "u", "tint": "#112233"}}
    assert build(sets, state, NOW)["sets"] == {
        "root": {"tint": "#112233", "source": "card"},
        "mid": {"tint": "#112233", "source": "parent"},
        "leaf": {"tint": "#112233", "source": "parent"},
    }
    assert root_of("leaf", {"leaf": "mid", "mid": "root"}) == "root"
    assert root_of("a", {"a": "b", "b": "a"}) is None


def test_a_child_does_not_cost_a_request_and_a_root_without_a_colour_leaves_its_children_out(tmp_path):
    net = Net()
    run(tmp_path, net)
    assert not any("tabc" in url or "trc" in url for url in net.asked)
    assert "gone" not in tints(tmp_path)["sets"] and "old" not in tints(tmp_path)["sets"]


def test_wizards_art_is_fetched_small_and_beats_the_card(tmp_path):
    net = Net()
    run(tmp_path, net)
    assert TRK_ART + "?w=96" in net.asked and SEARCH.format(code="trk") not in net.asked
    assert SEARCH.format(code="old") not in net.asked


def test_a_second_run_reads_only_the_sets_and_the_art_list_and_no_picture(tmp_path):
    run(tmp_path, Net())
    first = tints(tmp_path)
    again = Net()
    run(tmp_path, again)
    assert again.asked == [SETS_URL, PUBLISHED_ART]
    assert tints(tmp_path) == first


def test_a_set_with_no_cards_is_searched_again_only_when_its_card_count_changes(tmp_path):
    run(tmp_path, Net())
    grown = Net(scryfall(("gone", None, 7)))
    grown.files[SEARCH.format(code="gone")] = cards("https://cards.example/gone.jpg")
    grown.files["https://cards.example/gone.jpg"] = picture((200, 200, 40))
    run(tmp_path, grown)
    assert SEARCH.format(code="gone") in grown.asked
    assert tints(tmp_path)["sets"]["gone"]["source"] == "card"


def test_new_wizards_art_for_a_cached_set_is_read_again(tmp_path):
    run(tmp_path, Net())
    changed = Net()
    new_art = "https://images.ctfassets.net/x/trk/trk_art_2.jpg"
    changed.files[PUBLISHED_ART] = art_document(trk=new_art, abc="https://images.ctfassets.net/x/abc/abc.jpg")
    changed.files[new_art + "?w=96"] = picture((40, 200, 40))
    changed.files["https://images.ctfassets.net/x/abc/abc.jpg?w=96"] = picture((200, 200, 40))
    run(tmp_path, changed)
    document = tints(tmp_path)["sets"]
    assert document["trk"] == {"tint": tint_of(picture((40, 200, 40))), "source": "wizards"}
    assert document["abc"] == {"tint": tint_of(picture((200, 200, 40))), "source": "wizards"}
    assert document["trc"]["tint"] == document["trk"]["tint"]
    assert new_art + "?w=96" in changed.asked and "https://cards.example/dfc.jpg" not in changed.asked


def test_art_in_the_directory_is_read_before_the_published_file(tmp_path):
    (tmp_path / "sets").mkdir()
    (tmp_path / ART_PATH).write_bytes(art_document(trk=TRK_ART))
    net = Net()
    run(tmp_path, net)
    assert PUBLISHED_ART not in net.asked


def test_when_the_art_cannot_be_read_a_wizards_colour_is_kept(tmp_path):
    run(tmp_path, Net())
    first = tints(tmp_path)["sets"]["trk"]
    without = Net()
    without.files[PUBLISHED_ART] = OSError("down")
    run(tmp_path, without)
    assert tints(tmp_path)["sets"]["trk"] == first
    assert TRK_ART + "?w=96" not in without.asked


def test_a_picture_that_fails_is_skipped_and_tried_again_next_run(tmp_path, caplog):
    net = Net()
    net.files["https://cards.example/abc.jpg"] = OSError("HTTP 500")
    run(tmp_path, net)
    assert "abc" not in tints(tmp_path)["sets"] and "tabc" not in tints(tmp_path)["sets"]
    assert "trk" in tints(tmp_path)["sets"]
    assert "abc failed" in caplog.text
    retry = Net()
    run(tmp_path, retry)
    assert tints(tmp_path)["sets"]["abc"]["source"] == "card"


def test_wizards_art_that_fails_falls_back_to_the_card(tmp_path):
    net = Net()
    net.files[TRK_ART + "?w=96"] = OSError("HTTP 500")
    net.files[SEARCH.format(code="trk")] = cards("https://cards.example/trk.jpg")
    net.files["https://cards.example/trk.jpg"] = picture((200, 200, 40))
    run(tmp_path, net)
    assert tints(tmp_path)["sets"]["trk"]["source"] == "card"


def test_failing_sets_list_writes_nothing_and_leaves_the_published_file(tmp_path):
    net = Net()
    net.files[SETS_URL] = OSError("HTTP 503")
    with pytest.raises(OSError):
        run(tmp_path, net)
    assert not (tmp_path / "sets").exists() and not (tmp_path / "state").exists()


def test_the_state_keeps_the_url_and_colour_by_set_code_and_only_for_current_sets(tmp_path):
    run(tmp_path, Net())
    state = read_state(tmp_path)
    assert state["trk"] == {"source": "wizards", "url": TRK_ART, "tint": tint_of(picture((200, 40, 40)))}
    assert state["abc"]["url"] == "https://cards.example/abc.jpg"
    assert "trc" not in state
    run(tmp_path, Net(scryfall(("trk", None, 300))))
    assert set(read_state(tmp_path)) == {"trk"}


def test_publish_set_tints_names_the_file_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(settints, "write_set_tints", lambda directory, now, get, url: ["sets/tints.json"])
    assert entry.publish_set_tints(tmp_path, RunReport(), "https://data.example") == ["sets/tints.json"]


def test_set_tints_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SET_TINTS", "0")
    monkeypatch.setattr(settints, "write_set_tints", lambda *args: pytest.fail("ran"))
    assert entry.publish_set_tints(tmp_path, RunReport(), "https://data.example") == []


def test_a_failure_in_publish_set_tints_is_a_warning_the_run_passes(tmp_path, monkeypatch):
    def boom(*args):
        raise OSError("HTTP 500")

    monkeypatch.setattr(settints, "write_set_tints", boom)
    report = RunReport()
    assert entry.publish_set_tints(tmp_path, report, "https://data.example") == []
    assert report.errors == [] and report.warnings == ["set tints: HTTP 500"]
