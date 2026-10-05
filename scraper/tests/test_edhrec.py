import json

from mtgmeta.edhrec import Edhrec, due_slugs, edhrec_slug

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
        "https://json.edhrec.com/pages/commanders/vivi-ornitier.json": page(
            {"num_decks": 40779, "color_identity": ["U", "R"], "id": "ecc1027a-8c07-44a0-bdde-fa2844cff694"}),
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
    # EDHREC without either leaves them null, not missing.
    bare = Edhrec("test").commander("no-identity")
    assert bare["color_identity"] is None and bare["scryfall_id"] is None


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
