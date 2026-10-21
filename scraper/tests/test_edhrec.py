import json
from datetime import datetime, timezone

from mtgmeta.edhrec import Edhrec, due_commanders, due_slugs, edhrec_slug
from mtgmeta.top import build_top, top_slugs, write_top

CARD_JSON = {
    "container": {
        "json_dict": {
            "card": {"num_decks": 562775, "potential_decks": 5011429, "salt": 0.176470588},
            "cardlists": [
                {"tag": "topcards", "cardviews": [{"name": "Not a commander", "sanitized": "x", "num_decks": 5}]},
                {
                    "tag": "topcommanders",
                    "cardviews": [
                        {"name": "Vivi Ornitier", "sanitized": "vivi-ornitier", "num_decks": 23169, "potential_decks": 40779},
                        {"name": "No count", "sanitized": "no-count"},
                    ],
                },
            ],
        }
    }
}


def test_slugs_match_edhrecs_own():
    assert edhrec_slug("Y'shtola, Night's Blessed") == "yshtola-nights-blessed"
    assert edhrec_slug("Sol Ring") == "sol-ring"
    # A double-faced card is listed under its front face.
    assert edhrec_slug("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki") == "fable-of-the-mirror-breaker"


def test_a_card_entry_keeps_the_commanders_and_the_inclusion(monkeypatch):
    from mtgmeta import edhrec as module

    class Response:
        def read(self):
            return json.dumps(CARD_JSON).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda request, timeout=None: Response())
    entry = Edhrec("test").card("lightning-bolt")
    assert entry["decks"] == 562775 and entry["of_decks"] == 5011429
    assert entry["salt"] == 0.18 and entry["url"] == "https://edhrec.com/cards/lightning-bolt"
    # Only the commander list is kept, and only its usable rows.
    assert entry["commanders"] == [
        {"name": "Vivi Ornitier", "slug": "vivi-ornitier", "decks": 23169, "of_decks": 40779}
    ]


def test_a_commander_entry_keeps_its_colour_identity_and_scryfall_id(monkeypatch):
    from mtgmeta import edhrec as module

    def page(card):
        return {"container": {"json_dict": {"card": card, "cardlists": [
            {"tag": "topcards", "cardviews": [{"name": "Brainstorm", "num_decks": 28385, "synergy": 0.281}]}]}}}

    bodies = {
        "https://json.edhrec.com/pages/commanders/vivi-ornitier.json": {
            **page({"num_decks": 40779, "color_identity": ["U", "R"], "id": "ecc1027a-8c07-44a0-bdde-fa2844cff694"}),
            "tag_counts": [{"count": 300, "slug": "storm", "value": "Storm"}, {"count": 2100, "slug": "spellslinger", "value": "Spellslinger"}],
            "bracket_counts": {"4": 900, "3": 1200, "2": 400, "1": 9, "5": 70},
            "land": 33,
            "basic": 9,
        },
        "https://json.edhrec.com/pages/commanders/no-identity.json": page({"num_decks": 12}),
    }

    class Response:
        def __init__(self, body):
            self._body = body

        def read(self):
            return json.dumps(self._body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda request, timeout=None: Response(bodies.get(request.full_url, {})))
    vivi = Edhrec("test").commander("vivi-ornitier")
    assert vivi["color_identity"] == ["U", "R"] and vivi["scryfall_id"] == "ecc1027a-8c07-44a0-bdde-fa2844cff694"
    # Its themes, most decks first, and how its decks split by bracket, for the guides.
    assert [theme["slug"] for theme in vivi["themes"]] == ["spellslinger", "storm"]
    assert vivi["themes"][0] == {"slug": "spellslinger", "name": "Spellslinger", "decks": 2100}
    assert vivi["bracket_decks"] == {"1": 9, "2": 400, "3": 1200, "4": 900, "5": 70}
    assert (vivi["lands"], vivi["basics"]) == (33, 9)
    # EDHREC without either leaves them null, not missing.
    bare = Edhrec("test").commander("no-identity")
    assert bare["color_identity"] is None and bare["scryfall_id"] is None
    assert bare["themes"] == [] and bare["bracket_decks"] == {} and bare["lands"] is None


def test_a_card_edhrec_does_not_have_is_none(monkeypatch):
    from mtgmeta import edhrec as module

    def raise_403(request, timeout=None):
        raise module.urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", raise_403)
    assert Edhrec("test").card("not-a-card") is None


def test_the_longest_unchecked_cards_come_first():
    known = {"a": {"checked_at": "2026-09-20T00:00:00Z"}, "b": {"checked_at": "2026-09-22T00:00:00Z"}}
    wanted = {"card-a": "a", "card-b": "b", "card-c": "c"}
    assert due_slugs(known, wanted, 2) == [("card-c", "c"), ("card-a", "a")]
    assert due_slugs(known, wanted, 0) == []


def _top_page(*views):
    return {"container": {"json_dict": {"cardlists": [{"tag": "pastweek", "header": "Top Commanders (Past Week)", "cardviews": list(views)}]}}}


def _view(rank, name, slug, decks, trend=1.0):
    return {"id": f"id-{rank}", "name": name, "sanitized": slug, "slug": slug, "url": f"/commanders/{slug}", "num_decks": decks, "potential_decks": 0, "rank": rank, "trend_zscore": trend}


WEEK = _top_page(
    _view(1, "Jace, Multiverse Architect", "jace-multiverse-architect", 3000, 50.397),
    _view(2, "Kraum, Ludevic's Opus // Tymna the Weaver", "kraum-ludevics-opus-tymna-the-weaver", 1000, 2.04),
    {"name": "No count", "sanitized": "no-count"},
    _view(3, "Unlisted Commander", "unlisted-commander", 2000, None),
)
MONTH = _top_page(_view(1, "Jace, Multiverse Architect", "jace-multiverse-architect", 9000, 50.397))
CATALOG = {
    "jace-multiverse-architect": {"name": "Jace, Multiverse Architect", "oracle_id": "jace-oracle", "scryfall_id": "jace-printing", "color_identity": ["U"]},
    "kraum-ludevic-s-opus": {"name": "Kraum, Ludevic's Opus", "oracle_id": "kraum-oracle", "scryfall_id": "kraum-printing", "color_identity": ["U", "B"]},
    "tymna-the-weaver": {"name": "Tymna the Weaver", "oracle_id": "tymna-oracle", "color_identity": ["W", "B"]},
}
NOW = datetime(2026, 10, 19, 14, 5, tzinfo=timezone.utc)


def _serve(monkeypatch, pages):
    from mtgmeta import edhrec as module

    class Response:
        def __init__(self, body):
            self._body = body

        def read(self):
            return json.dumps(self._body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout=None):
        body = pages.get(request.full_url)
        if body is None:
            raise module.urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        return Response(body)

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)


def test_the_top_pages_give_each_windows_ranked_commanders(monkeypatch):
    _serve(monkeypatch, {
        "https://json.edhrec.com/pages/commanders/week.json": WEEK,
        "https://json.edhrec.com/pages/commanders/month.json": MONTH,
    })
    windows = Edhrec("test", delay=0).top_commanders()
    assert list(windows) == ["7d", "30d"]
    assert windows["7d"][0] == {"rank": 1, "slug": "jace-multiverse-architect", "name": "Jace, Multiverse Architect", "decks": 3000, "trend": 50.4}
    # A row with no deck count is skipped, and a missing z-score is a null trend.
    assert [row["slug"] for row in windows["7d"]] == ["jace-multiverse-architect", "kraum-ludevics-opus-tymna-the-weaver", "unlisted-commander"]
    assert windows["7d"][2]["trend"] is None


def test_a_window_that_fails_is_left_out_and_two_failures_leave_nothing(monkeypatch, tmp_path):
    _serve(monkeypatch, {"https://json.edhrec.com/pages/commanders/month.json": MONTH})
    windows = Edhrec("test", delay=0).top_commanders()
    assert list(windows) == ["30d"]
    assert list(build_top(windows, NOW)["windows"]) == ["30d"]

    _serve(monkeypatch, {})
    assert Edhrec("test", delay=0).top_commanders() == {}
    assert build_top({}, NOW) is None
    assert write_top(tmp_path, {}, NOW) == []
    assert not (tmp_path / "edh" / "top.json").exists()


def test_the_file_has_each_windows_deck_total_and_shares_of_it(monkeypatch, tmp_path):
    _serve(monkeypatch, {
        "https://json.edhrec.com/pages/commanders/week.json": WEEK,
        "https://json.edhrec.com/pages/commanders/month.json": MONTH,
    })
    windows = Edhrec("test", delay=0).top_commanders()
    assert write_top(tmp_path, windows, NOW, CATALOG) == ["edh/top.json"]
    document = json.loads((tmp_path / "edh" / "top.json").read_text())
    assert document["schema"] == 1 and document["generated_at"] == "2026-10-19T14:05:00Z"
    week = document["windows"]["7d"]
    assert week["decks"] == 6000
    assert [(row["rank"], row["decks"], row["share"]) for row in week["commanders"]] == [(1, 3000, 50.0), (2, 1000, 16.7), (3, 2000, 33.3)]
    assert document["windows"]["30d"] == {"decks": 9000, "commanders": [{
        "rank": 1, "slug": "jace-multiverse-architect", "name": "Jace, Multiverse Architect", "decks": 9000, "share": 100.0,
        "color_identity": ["U"], "oracle_id": "jace-oracle", "scryfall_id": "jace-printing", "trend": 50.4,
    }]}


def test_commanders_take_their_ids_and_colours_from_the_catalog():
    windows = {"7d": [
        {"rank": 1, "slug": "jace", "name": "Jace, Multiverse Architect", "decks": 3, "trend": 1.0},
        {"rank": 2, "slug": "pair", "name": "Kraum, Ludevic's Opus // Tymna the Weaver", "decks": 2, "trend": 1.0},
        {"rank": 3, "slug": "half", "name": "Kraum, Ludevic's Opus // Nobody Known", "decks": 1, "trend": 1.0},
        {"rank": 4, "slug": "new", "name": "Unlisted Commander", "decks": 1, "trend": 1.0},
    ]}
    jace, pair, half, unknown = build_top(windows, NOW, CATALOG)["windows"]["7d"]["commanders"]
    assert (jace["color_identity"], jace["oracle_id"], jace["scryfall_id"]) == (["U"], "jace-oracle", "jace-printing")
    # A pair is no one card: no ids, and both halves' colours in WUBRG order.
    assert (pair["color_identity"], pair["oracle_id"], pair["scryfall_id"]) == (["W", "U", "B"], None, None)
    assert (half["color_identity"], half["oracle_id"]) == (None, None)
    assert (unknown["color_identity"], unknown["oracle_id"], unknown["scryfall_id"]) == (None, None, None)
    assert build_top(windows, NOW)["windows"]["7d"]["commanders"][0]["oracle_id"] is None


def test_a_double_faced_commander_in_the_catalog_keeps_its_own_ids():
    catalog = {"frodo-adventurous-hobbit": {"name": "Frodo, Adventurous Hobbit // Sam, Loyal Attendant", "oracle_id": "frodo-oracle", "color_identity": ["W"]}}
    windows = {"7d": [{"rank": 1, "slug": "frodo", "name": "Frodo, Adventurous Hobbit // Sam, Loyal Attendant", "decks": 1, "trend": 0.0}]}
    frodo = build_top(windows, NOW, catalog)["windows"]["7d"]["commanders"][0]
    assert (frodo["oracle_id"], frodo["color_identity"]) == ("frodo-oracle", ["W"])


def test_the_top_commanders_are_read_before_the_rest_of_the_queue():
    known = {"a": {"checked_at": "2026-09-20T00:00:00Z"}, "b": {"checked_at": "2026-09-22T00:00:00Z"}}
    wanted = {"a": "a", "b": "b", "c": "c"}
    assert due_commanders(known, wanted, ["b", "z"], 3) == [("b", "b"), ("z", "z"), ("c", "c")]
    assert due_commanders(known, wanted, ["z", "b", "z"], 2) == [("z", "z"), ("b", "b")]
    assert due_commanders(known, wanted, [], 2) == due_slugs(known, wanted, 2)
    assert due_commanders(known, wanted, ["b"], 0) == []
    windows = {"7d": [{"slug": "x"}, {"slug": "y"}], "30d": [{"slug": "y"}, {"slug": "w"}]}
    assert top_slugs(windows) == ["x", "y", "w"]
