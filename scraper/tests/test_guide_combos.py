import json
import urllib.error

from mtgmeta import guide_combos

GUIDE = {
    "schema": 1,
    "slug": "kinnan-bonder-prodigy",
    "name": "Kinnan, Bonder Prodigy",
    "styles": [{"id": "ramp", "name": "Ramp", "cards": [{"name": "Basalt Monolith", "oracle_id": "basalt"}, {"name": "Sol Ring", "oracle_id": "ring"}]}],
    "brackets": [{"level": 4, "name": "Optimized", "cards": [{"name": "Sol Ring", "oracle_id": "ring"}, {"name": "Thrasios, Triton Hero", "oracle_id": "thrasios"}]}],
}


def card(name, oracle_id):
    return {"card": {"name": name, "oracleId": oracle_id}}


def variant(id, cards, popularity, tag="R", status="OK", produces=None, requires=(), commander=True, spoiler=False):
    return {
        "id": id,
        "status": status,
        "spoiler": spoiler,
        "legalities": {"commander": commander},
        "bracketTag": tag,
        "popularity": popularity,
        "uses": [card(*each) for each in cards],
        "requires": [{"template": {"name": name}} for name in requires],
        "produces": produces if produces is not None else [{"feature": {"name": "Infinite colorless mana", "status": "S"}}],
    }


KINNAN = ("Kinnan, Bonder Prodigy", "kinnan")
BASALT = ("Basalt Monolith", "basalt")


def test_the_deck_is_the_commander_and_every_card_once():
    deck = guide_combos.decklist(GUIDE)
    assert deck["commanders"] == [{"card": "Kinnan, Bonder Prodigy"}]
    assert [each["card"] for each in deck["main"]] == ["Basalt Monolith", "Sol Ring", "Thrasios, Triton Hero"]


def test_a_pair_sends_both_halves_and_the_whole_name():
    deck = guide_combos.decklist({**GUIDE, "name": "Thrasios, Triton Hero // Tymna the Weaver"})
    assert [each["card"] for each in deck["commanders"]] == ["Thrasios, Triton Hero // Tymna the Weaver", "Thrasios, Triton Hero", "Tymna the Weaver"]
    assert "Thrasios, Triton Hero" not in [each["card"] for each in deck["main"]]


def test_every_page_is_read():
    pages = {
        "https://backend.commanderspellbook.com/find-my-combos?limit=100": {"next": "page-2", "results": {"included": [{"id": "a"}]}},
        "page-2": {"next": None, "results": {"included": [{"id": "b"}], "almostIncluded": [{"id": "c"}]}},
    }
    assert [each["id"] for each in guide_combos.included({}, lambda url, body: pages[url])] == ["a", "b"]


def test_combos_keep_the_playable_most_played_first_once_per_set_of_cards():
    variants = [
        variant("low", [KINNAN, BASALT], 10, tag="P", requires=["A mana sink"]),
        variant("high", [KINNAN, BASALT], 900),
        variant("casual", [("Sol Ring", "ring"), BASALT], 50, tag="E"),
        variant("banned", [BASALT, ("Mana Crypt", "crypt")], 5000, tag="B"),
        variant("draft", [BASALT, ("Other", "other")], 5000, status="NR"),
        variant("spoiler", [BASALT, ("New", "new")], 5000, spoiler=True),
        variant("illegal", [BASALT, ("Ante", "ante")], 5000, commander=False),
        variant("helpers", [BASALT, ("Helper", "helper")], 5000, produces=[{"feature": {"name": "Untap", "status": "H"}}]),
        variant("no-oracle", [BASALT, ("Token", None)], 5000),
    ]
    combos = guide_combos.combos(variants)
    assert [each["id"] for each in combos] == ["high", "casual"]
    assert combos[0] == {
        "id": "high",
        "cards": [{"name": "Kinnan, Bonder Prodigy", "oracle_id": "kinnan"}, {"name": "Basalt Monolith", "oracle_id": "basalt"}],
        "requires": [],
        "results": ["Infinite colorless mana"],
        "bracket": 4,
        "bracket_tag": "R",
    }
    assert combos[1]["bracket"] == 1


def test_a_failed_lookup_leaves_the_guide_as_it_was():
    def fails(guide):
        raise urllib.error.URLError("down")

    assert guide_combos.with_combos(GUIDE, fails) == GUIDE


def test_the_command_adds_combos_to_a_guide(tmp_path, capsys):
    path = tmp_path / "edh" / "commanders" / "kinnan-bonder-prodigy" / "guide.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(GUIDE))

    def find(guide):
        return guide_combos.combos([variant("high", [KINNAN, BASALT], 900)])

    assert guide_combos.main([str(tmp_path), "--slug", "kinnan-bonder-prodigy"], find_combos=find) == 0
    assert json.loads(path.read_text())["combos"][0]["id"] == "high"
    assert "1 written, 0 without a guide, 0 failed" in capsys.readouterr().out


def test_a_wrapped_two_card_combo_is_kept_from_bracket_three():
    wrapped = [
        {"combo": variant("two", [KINNAN, BASALT], 50, tag="C"), "definitelyTwoCard": True, "arguablyTwoCard": True, "relevant": True},
        {"combo": variant("three", [KINNAN, BASALT, ("Sol Ring", "ring")], 40, tag="C"), "definitelyTwoCard": False, "arguablyTwoCard": False},
    ]
    combos = {each["id"]: each for each in guide_combos.combos(wrapped)}
    assert (combos["two"]["bracket"], combos["two"]["two_card"]) == (3, True)
    assert (combos["three"]["bracket"], combos["three"]["two_card"]) == (2, False)
    # A variant from find-my-combos carries no such flags, and no two_card.
    assert "two_card" not in guide_combos.combos([variant("plain", [KINNAN, BASALT], 10, tag="C")])[0]


def test_a_data_built_guide_keeps_its_own_combos(tmp_path):
    path = tmp_path / "edh" / "commanders" / "kinnan-bonder-prodigy" / "guide.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({**GUIDE, "generator": "data-1", "combos": [{"id": "own"}]}))

    assert guide_combos.main([str(tmp_path), "--slug", "kinnan-bonder-prodigy"], find_combos=lambda guide: []) == 0
    assert json.loads(path.read_text())["combos"] == [{"id": "own"}]
