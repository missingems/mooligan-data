import json
from datetime import datetime, timezone

import pytest

import mtgmeta.__main__ as entry
import mtgmeta.setmechanics as setmechanics
from mtgmeta.models import RunReport
from mtgmeta.setmechanics import (
    CATALOG_URL, PATH, build, build_lexicon, canonical, load_rules, read_catalogs, reminder, write_set_mechanics,
)

NOW = datetime(2026, 10, 20, 9, 30, 0, tzinfo=timezone.utc)

RULES = {
    "keywords": {
        "kicker": {"name": "Kicker", "number": "702.33", "rules": ["Kicker is a static ability.", "Multikicker is a variant."]},
        "cycling": {"name": "Cycling", "number": "702.29", "rules": ["Cycling is an activated ability."]},
        "landwalk": {"name": "Landwalk", "number": "702.14", "rules": ["Landwalk is an evasion ability."]},
        "flying": {"name": "Flying", "number": "702.9", "rules": ["Flying is an evasion ability."]},
        "daybound and nightbound": {"name": "Daybound and nightbound", "number": "702.145", "rules": ["x"]},
        "daybound": {"name": "Daybound", "number": "702.145", "rules": ["Daybound is a keyword."]},
        "surveil": {"name": "Surveil", "number": "701.25", "rules": ["To surveil N means to look.", "Second."]},
        "scry": {"name": "Scry", "number": "701.22", "rules": ["Scry."]},
        "mutate": {"name": "Mutate", "number": "702.140", "rules": ["Mutate is a static ability."]},
        "mobilize": {"name": "Mobilize", "number": "702.181", "rules": ["Mobilize is a triggered ability."]},
    },
    "ability_words": {"number": "207.2c", "text": "An ability word appears in italics.", "words": ["landfall", "council’s dilemma", "descend 4", "descend 8"]},
}
CATALOGS = {
    "keyword-abilities": ["Kicker", "Cycling", "Landwalk", "Flying", "Daybound", "Nightbound", "Mutate", "Mobilize", "Multikicker", "Plainscycling", "Islandwalk", "Wizardcycling"],
    "keyword-actions": ["Surveil", "Scry", "Prepared"],
    "ability-words": ["Landfall", "Council's dilemma", "Descend", "Dreadful Surprise"],
}


def scryfall(url):
    return json.dumps({"object": "catalog", "data": CATALOGS[url.removeprefix(CATALOG_URL)]}).encode()


def lexicon():
    return build_lexicon(RULES, read_catalogs(scryfall, lambda seconds: None))


def card(name, code, released, keywords, text="", kind="expansion", oracle=None, rank=None, rarity="common", **more):
    return {
        "name": name, "oracle_id": oracle or f"o-{name}", "set": code, "set_type": kind, "released_at": released,
        "keywords": keywords, "oracle_text": text, "edhrec_rank": rank, "rarity": rarity, "games": ["paper", "mtgo"], "layout": "normal", **more,
    }


CARDS = [
    card("Old Kicker Card", "inv", "2000-10-02", ["Kicker"], "Kicker {R} (You may pay an additional {R}.)"),
    card("Reprint Kicker", "m10", "2009-07-17", ["Kicker"]),
    card("Mutate Beast", "iko", "2020-04-03", ["Mutate"], "Mutate {2}{G} (If you cast this spell for its mutate cost, put it over or under target non-Human creature you own.)", rank=500),
    card("Mutate Elk", "iko", "2020-04-03", ["Mutate"], "Mutate {1}{G} (Cast it over a creature.)", rank=100, oracle="o-elk"),
    card("Mutate Bear", "iko", "2020-04-03", ["Mutate"], "Mutate {G}", rank=None, rarity="mythic"),
    card("Mutate Wolf", "iko", "2020-04-03", ["Mutate"], "Mutate {G}", rank=None, rarity="common"),
    card("Mutate Fox", "iko", "2020-04-03", ["Mutate"], "Mutate {G}", rank=900),
    card("Mutate Elk Showcase", "iko", "2020-04-03", ["Mutate"], "Mutate {1}{G} (Cast it over a creature.)", rank=100, oracle="o-elk"),
    card("Mutate Promo", "piko", "2020-03-28", ["Mutate"], "Mutate {2}{G}", kind="promo"),
    card("Night Wolf", "mid", "2021-09-24", ["Daybound"], "Daybound (If a player casts no spells during their own turn, it becomes night next turn.)"),
    card("Night Wolf Back", "mid", "2021-09-24", ["Nightbound"], "Nightbound"),
    card("Night Commander", "mic", "2021-09-24", ["Daybound"], "Daybound", kind="commander"),
    card("Landfall Land", "zen", "2009-10-02", ["Landfall"], "Landfall — Whenever a land enters, draw a card. (This is not reminder.)"),
    card("Council Card", "cns", "2013-05-03", ["Council's dilemma"], "Will of the council"),
    card("Descender", "lci", "2023-11-17", ["Descend"], "Descend 4 — x"),
    card("Surveil Card", "grn", "2019-01-25", ["Surveil"], "When this enters, surveil 2. (Look at the top two cards of your library, then put any number of them into your graveyard and the rest back on top in any order.)"),
    card("Scry Card", "fut", "2007-05-04", ["Scry"], "Scry 1"),
    card("Flyer", "7ed", "2001-04-11", ["Flying"], "Flying"),
    card("Flyer Two", "lea", "1993-08-05", ["Flying"], "Flying"),
    card("Old Cycler", "tmp", "1997-10-14", ["Cycling"], "Cycling {2}"),
    card("Plains Cycler", "tsp", "2006-10-06", ["Plainscycling"], "Plainscycling {2}"),
    card("Wizard Cycler", "dgm", "2013-05-03", ["Wizardcycling"], "Wizardcycling {2}"),
    card("Island Walker", "mir", "1996-10-08", ["Islandwalk"], "Islandwalk"),
    card("Multi Kicker", "wwk", "2010-02-05", ["Multikicker"], "Multikicker {1}"),
    card("Mobilizer", "tdm", "2025-04-11", ["Mobilize"], "Mobilize 2 (Whenever this creature attacks, create two tapped and attacking 1/1 red Warrior creature tokens.)", rank=3000),
    card("Mobilizer Commander", "tdc", "2025-04-11", ["Mobilize"], "Mobilize 1", kind="commander", rank=10),
    card("Prepared Creature", "sos", "2026-04-24", ["Prepared"], "At the beginning of combat, this creature becomes prepared. (While it's prepared, you may cast a copy of its spell.)", rank=10),
    card("Prepared Creature", "sos", "2026-04-24", ["Prepared"], "x", oracle="o-two", card_faces=[
        {"name": "Front", "oracle_text": "This creature becomes prepared. (Cast a copy.)"}, {"name": "Back", "oracle_text": "Draw."}], rank=20),
    card("Card Specific Name", "sos", "2026-04-24", ["Blizzaga"], "x"),
    card("Digital Only", "ymid", "2021-12-01", ["Surveil"], "Surveil 1", digital=True),
    card("Arena Only", "xxx", "2010-01-01", ["Surveil"], "Surveil 1", games=["arena"]),
    card("Token Thing", "tgrn", "2018-01-01", ["Surveil"], "x", kind="token", layout="token"),
    card("Reprint Mutate Set", "plst", "2024-08-02", ["Mutate"], kind="masters"),
    card("Nothing New", "dmu", "2022-09-09", []),
]


def mechanics(cards=CARDS, rules=None):
    return build(cards, build_lexicon(rules or RULES, read_catalogs(scryfall, lambda seconds: None)), NOW)["sets"]


def keywords(sets, code):
    return [item["keyword"] for item in sets[code]]


def test_a_keyword_is_new_to_the_set_of_its_earliest_printing():
    sets = mechanics()
    assert keywords(sets, "iko") == ["Mutate"]
    assert keywords(sets, "grn") == ["Surveil"]
    assert keywords(sets, "mid") == ["Daybound"]
    assert keywords(sets, "tdm") == ["Mobilize"]
    assert keywords(sets, "cns") == ["Council's dilemma"]
    assert all(item["first_set"] == code for code, items in sets.items() for item in items)


def test_a_reprint_a_promo_or_a_later_set_does_not_take_the_mechanic():
    sets = mechanics()
    assert "piko" not in sets
    assert sets["m10"] == [] and sets["plst"] == []
    assert keywords(sets, "iko") == ["Mutate"]


def test_a_set_and_its_commander_deck_out_together_give_the_mechanic_to_the_set_first():
    sets = mechanics()
    assert keywords(sets, "tdm") == ["Mobilize"] and sets["tdc"] == []
    sets = mechanics([card("A", "xcm", "2020-01-01", ["Mutate"], kind="commander"), card("B", "xex", "2020-01-01", ["Mutate"])])
    assert keywords(sets, "xex") == ["Mutate"] and sets["xcm"] == []


def test_a_mechanic_only_a_commander_set_has_is_that_sets():
    sets = mechanics([card("A", "xcm", "2020-01-01", ["Mutate"], kind="commander")])
    assert keywords(sets, "xcm") == ["Mutate"]


def test_every_set_that_can_introduce_a_mechanic_is_listed_even_with_none():
    sets = mechanics()
    assert sets["dmu"] == [] and sets["lea"] == []
    assert "tgrn" not in sets and "ymid" not in sets and "xxx" not in sets


def test_evergreen_keywords_and_those_first_printed_before_1999_are_left_out():
    all_keywords = {item["keyword"] for items in mechanics().values() for item in items}
    assert not {"Flying", "Scry", "Cycling", "Landwalk"} & all_keywords
    assert keywords(mechanics(), "inv") == ["Kicker"]


def test_variants_of_an_older_mechanic_are_that_mechanic():
    all_keywords = {item["keyword"] for items in mechanics().values() for item in items}
    assert not {"Multikicker", "Plainscycling", "Wizardcycling", "Islandwalk"} & all_keywords
    assert keywords(mechanics(), "wwk") == []


def test_nightbound_is_daybound():
    sets = mechanics()
    assert keywords(sets, "mid") == ["Daybound"]


def test_words_that_are_not_keywords_are_left_out():
    assert "Blizzaga" not in {item["keyword"] for items in mechanics().values() for item in items}


def test_the_kind_comes_from_the_rule_number_the_ability_word_list_then_scryfalls_catalogs():
    sets = mechanics()
    assert next(item for item in sets["iko"])["kind"] == "keyword ability"
    assert next(item for item in sets["grn"])["kind"] == "keyword action"
    assert sets["cns"][0]["kind"] == "ability word"
    assert sets["lci"][0]["kind"] == "ability word"
    assert sets["sos"][0]["kind"] == "keyword action"


def test_the_rules_are_the_keywords_subrules_and_an_ability_words_are_rule_207_2c():
    sets = mechanics()
    assert sets["grn"][0]["rules"] == "To surveil N means to look.\nSecond."
    assert sets["cns"][0]["rules"] == "An ability word appears in italics."
    assert sets["sos"][0]["rules"] == ""


def test_the_reminder_is_the_parenthesis_after_the_keyword_in_an_example_cards_text():
    sets = mechanics()
    assert sets["iko"][0]["reminder"] == "Cast it over a creature."
    assert sets["grn"][0]["reminder"].startswith("Look at the top two cards")
    assert sets["sos"][0]["reminder"] == "While it's prepared, you may cast a copy of its spell."
    assert sets["mid"][0]["reminder"].startswith("If a player casts no spells")


def test_an_ability_word_has_no_reminder_and_a_keyword_without_one_has_an_empty_one():
    sets = mechanics()
    assert sets["cns"][0]["reminder"] == ""
    assert mechanics([card("A", "xex", "2020-01-01", ["Mutate"], "Mutate {G}")])["xex"][0]["reminder"] == ""


@pytest.mark.parametrize("keyword, text, expected", [
    ("Kicker", "Kicker {R} (You may pay an additional {R}.)", "You may pay an additional {R}."),
    ("Kicker", "Flying\nKicker {R} (You may pay.)\nDraw a card (not this).", "You may pay."),
    ("Prepared", "This creature becomes prepared. (While it's prepared, cast a copy.)", "While it's prepared, cast a copy."),
    ("Mutate", "Mutate {G} and then some more words that make the paren far too distant from it to be its reminder text (no).", ""),
    ("Flash", "Flashback {2} (Cast from graveyard.)", ""),
    ("Fabricate", "Fabricate 1 (x)", "x"),
    ("Mutate", "Draw a card. (Not about it.)", ""),
])
def test_reminder_text_is_read_from_a_line_with_the_keyword(keyword, text, expected):
    assert reminder(keyword, text) == expected


def test_a_double_faced_cards_text_is_both_faces():
    sets = mechanics([card("Two Faced", "xex", "2020-01-01", ["Mutate"], card_faces=[{"oracle_text": "Front"}, {"oracle_text": "Mutate {G} (Back reminder.)"}])])
    assert sets["xex"][0]["reminder"] == "Back reminder."


def test_examples_are_the_most_played_cards_up_to_three_without_repeats():
    ids = mechanics()["iko"][0]["example_oracle_ids"]
    assert ids == ["o-elk", "o-Mutate Beast", "o-Mutate Fox"]
    assert len(set(ids)) == 3


def test_examples_without_an_edhrec_rank_go_by_rarity_after_those_with_one():
    cards = [card("Common", "xex", "2020-01-01", ["Mutate"]), card("Mythic", "xex", "2020-01-01", ["Mutate"], rarity="mythic"), card("Ranked", "xex", "2020-01-01", ["Mutate"], rank=7000)]
    assert mechanics(cards)["xex"][0]["example_oracle_ids"] == ["o-Ranked", "o-Mythic", "o-Common"]


def test_a_card_is_found_by_the_oracle_id_of_its_first_face():
    cards = [card("Faces", "xex", "2020-01-01", ["Mutate"], oracle="", card_faces=[{"oracle_id": "face-id", "oracle_text": "x"}])]
    cards[0]["oracle_id"] = None
    assert mechanics(cards)["xex"][0]["example_oracle_ids"] == ["face-id"]


def test_mechanics_in_a_set_are_ordered_by_how_many_cards_have_them_then_by_name():
    cards = [card("A", "xex", "2020-01-01", ["Mutate"]), card("B", "xex", "2020-01-01", ["Mobilize"]), card("C", "xex", "2020-01-01", ["Mobilize"]), card("D", "xex", "2020-01-01", ["Surveil"])]
    assert keywords(mechanics(cards), "xex") == ["Mobilize", "Mutate", "Surveil"]


def test_a_keyword_known_only_to_the_rules_counts():
    rules = json.loads(json.dumps(RULES))
    rules["keywords"]["storied"] = {"name": "Storied", "number": "702.195", "rules": ["Storied is a keyword."]}
    sets = mechanics([card("A", "xex", "2026-08-14", ["Storied"], "Storied (reminder)")], rules)
    assert sets["xex"][0]["keyword"] == "Storied" and sets["xex"][0]["rules"] == "Storied is a keyword."


def test_canonical_folds_variants_into_their_mechanic():
    known = lexicon()
    assert canonical("Plainscycling", known) == "cycling"
    assert canonical("Islandwalk", known) == "landwalk"
    assert canonical("Multikicker", known) == "kicker"
    assert canonical("Nightbound", known) == "daybound"
    assert canonical("Council’s dilemma", known) == "council's dilemma"
    assert canonical("Nonsense", known) is None


def test_the_file_has_the_contracts_shape(tmp_path):
    written = write_set_mechanics(tmp_path, NOW, iter(CARDS), scryfall, lambda: RULES, lambda seconds: None)
    assert written == [PATH]
    document = json.loads((tmp_path / PATH).read_text())
    assert document["schema"] == 1 and document["generated_at"] == "2026-10-20T09:30:00Z"
    assert document["sets"]["sos"] == [{
        "keyword": "Prepared", "kind": "keyword action", "reminder": "While it's prepared, you may cast a copy of its spell.",
        "rules": "", "example_oracle_ids": ["o-Prepared Creature", "o-two"], "first_set": "sos",
    }]


def test_the_catalogs_are_read_with_a_pause_between_requests():
    pauses = []
    read_catalogs(scryfall, pauses.append)
    assert len(pauses) == 2


def test_rules_come_from_the_work_directory_else_the_published_file(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "keywords.json").write_text(json.dumps({"keywords": {"local": 1}}))
    assert load_rules(tmp_path, lambda url: pytest.fail("downloaded"), "https://x/rules.json") == {"keywords": {"local": 1}}
    asked = []
    assert load_rules(tmp_path / "empty", lambda url: asked.append(url) or b'{"keywords": {"remote": 1}}', "https://x/rules.json") == {"keywords": {"remote": 1}}
    assert asked == ["https://x/rules.json"]
    with pytest.raises(RuntimeError):
        load_rules(tmp_path / "empty", lambda url: b"", None)


def test_unreadable_rules_write_nothing(tmp_path):
    def rules():
        raise OSError("HTTP 404")

    with pytest.raises(OSError):
        write_set_mechanics(tmp_path, NOW, iter(CARDS), scryfall, rules, lambda seconds: None)
    assert not (tmp_path / "sets").exists()


def test_publish_set_mechanics_names_the_file_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr("mtgmeta.scryfall._bulk_download_uri", lambda url: "unused")
    monkeypatch.setattr(setmechanics, "write_set_mechanics", lambda *args: ["sets/mechanics.json"])
    assert entry.publish_set_mechanics(tmp_path, RunReport(), "https://data.example") == ["sets/mechanics.json"]


def test_set_mechanics_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SET_MECHANICS", "0")
    monkeypatch.setattr(setmechanics, "write_set_mechanics", lambda *args: pytest.fail("ran"))
    assert entry.publish_set_mechanics(tmp_path, RunReport(), "https://data.example") == []


def test_a_failure_in_publish_set_mechanics_is_a_warning_the_run_passes(tmp_path, monkeypatch):
    def boom(*args):
        raise OSError("HTTP 500")

    monkeypatch.setattr("mtgmeta.scryfall._bulk_download_uri", lambda url: "unused")
    monkeypatch.setattr(setmechanics, "write_set_mechanics", boom)
    report = RunReport()
    assert entry.publish_set_mechanics(tmp_path, report, "https://data.example") == []
    assert report.errors == [] and report.warnings == ["set mechanics: HTTP 500"]
