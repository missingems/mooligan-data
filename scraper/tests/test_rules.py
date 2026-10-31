import hashlib
import importlib.util
import json
import logging
import re
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import mtgmeta.__main__ as entry
import mtgmeta.rules as rules
from mtgmeta.manifest import FILES, explore_paths, is_explore_path, write_manifest
from mtgmeta.parsing import ParseError
from mtgmeta.rules import (
    COMPREHENSIVE_PATH,
    COMPREHENSIVE_STATE_PATH,
    PAGE_URL,
    PATH,
    STATE_PATH,
    fingerprint,
    parse_comprehensive_rules,
    parse_rules,
    read_fingerprint,
    read_rules,
    rules_url,
    write_comprehensive_rules,
    write_rules,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, 14, 0, 7, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 13, 14, 2, 31, tzinfo=timezone.utc)
SOURCE = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt"
# The excerpt is as Wizards serves the file: a byte order mark, and a lone no-break space for each blank line.
EXCERPT = (FIXTURES / "comprehensive_rules_excerpt.txt").read_bytes()
PAGE = (FIXTURES / "rules_page.html").read_bytes()
# The floors as published, before `small_excerpt` lowers them, and the counts of the edition of 25 September 2026 they were set from.
FLOORS = (rules.MIN_CHAPTERS, rules.MIN_SECTIONS, rules.MIN_NUMBERED_RULES, rules.MIN_GLOSSARY_ENTRIES)
EDITION_COUNTS = (9, 147, 3166, 741)


@pytest.fixture(autouse=True)
def small_excerpt(monkeypatch):
    """The excerpt has six keywords and a few rules of three chapters, where the real rules have hundreds; the floors have their own tests."""
    monkeypatch.setattr(rules, "MIN_KEYWORDS", 1)
    monkeypatch.setattr(rules, "MIN_CHAPTERS", 1)
    monkeypatch.setattr(rules, "MIN_SECTIONS", 1)
    monkeypatch.setattr(rules, "MIN_NUMBERED_RULES", 1)
    monkeypatch.setattr(rules, "MIN_GLOSSARY_ENTRIES", 1)


def excerpt() -> str:
    return EXCERPT.decode("utf-8-sig")


def build(text=None, now=NOW):
    return parse_rules(excerpt() if text is None else text, SOURCE, now)


def book(text=None, now=NOW):
    return parse_comprehensive_rules(excerpt() if text is None else text, SOURCE, now)


class Wizards:
    """Stands in for the network: the rules page and the file it links to, and a record of what was asked for."""

    def __init__(self, page=PAGE, text=EXCERPT):
        self.pages = {PAGE_URL: page, SOURCE: text}
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        found = self.pages[url]
        if isinstance(found, Exception):
            raise found
        return found


def write(directory, now=NOW, wizards=None):
    """rules/keywords.json, written as a run writes it: from one read of Wizards' page and file."""
    return write_rules(directory, now, *read_rules(wizards or Wizards()))


def write_book(directory, now=NOW, wizards=None):
    return write_comprehensive_rules(directory, now, *read_rules(wizards or Wizards()))


def report():
    return SimpleNamespace(errors=[], warnings=[])


# ---- Parsing

def test_the_effective_date_is_the_iso_date_of_the_line_at_the_top():
    assert build()["effective_date"] == "2026-09-25"


def test_the_file_has_the_contracts_fields_in_order():
    document = build()
    assert list(document) == ["schema", "generated_at", "effective_date", "source_url", "keywords", "ability_words"]
    assert document["schema"] == 1
    assert document["generated_at"] == "2026-10-12T14:00:07Z"
    assert document["source_url"] == SOURCE


def test_the_time_is_utc_whatever_the_zone_it_is_given_in():
    assert build(now=datetime(2026, 10, 12, 22, 0, 7, tzinfo=timezone(timedelta(hours=8))))["generated_at"] == "2026-10-12T14:00:07Z"


def test_each_named_entry_of_701_and_702_is_a_keyword_by_its_lower_cased_name_in_the_order_of_the_rules():
    keywords = build()["keywords"]
    assert list(keywords) == ["activate", "exchange", "scry", "flying", "landwalk", "bestow"]
    assert [(entry["name"], entry["number"]) for entry in keywords.values()] == [
        ("Activate", "701.2"), ("Exchange", "701.12"), ("Scry", "701.22"), ("Flying", "702.9"), ("Landwalk", "702.14"), ("Bestow", "702.103"),
    ]
    assert all(list(entry) == ["name", "number", "rules"] for entry in keywords.values())


def test_the_sections_introductions_are_not_entries():
    # 701.1 and 702.1 look like headers ("701.1. Most actions described …") but their "name" is a sentence.
    keywords = build()["keywords"]
    assert not any(entry["number"] in ("701.1", "702.1") for entry in keywords.values())
    assert not any(name.startswith("most ") for name in keywords)
    assert "Most actions described" not in json.dumps(keywords)


def test_the_rules_of_an_entry_are_its_subrules_in_order_without_their_letters():
    scry = build()["keywords"]["scry"]["rules"]
    assert len(scry) == 4
    assert scry[0].startswith("To “scry N” means to look at the top N cards of your library")
    assert scry[1] == "If a player is instructed to scry 0, no scry event occurs. Abilities that trigger whenever a player scries won’t trigger."
    assert scry[3].startswith("An ability that triggers whenever a player scries triggers after the process")
    assert not any(rule[:2].isdigit() for rule in scry)


def test_a_see_rule_cross_reference_is_removed_with_the_space_before_it():
    flying = build()["keywords"]["flying"]["rules"]
    assert flying == [
        "Flying is an evasion ability.",
        "A creature with flying can’t be blocked except by creatures with flying and/or reach. A creature with flying can block a creature with or without flying.",
        "Multiple instances of flying on the same creature are redundant.",
    ]
    assert not any("(See" in rule or "(see" in rule for entry in build()["keywords"].values() for rule in entry["rules"])


def test_a_cross_reference_that_names_no_rule_is_removed_too():
    bestow = build()["keywords"]["bestow"]["rules"]
    assert bestow[0].endswith("follows the rules for paying alternative costs.")
    assert "601.2b" not in json.dumps(bestow)


def test_a_cross_reference_that_is_a_sentence_and_other_parentheses_stay():
    keywords = build()["keywords"]
    assert keywords["bestow"]["rules"][-1].endswith("See rule 702.26, “Phasing.”")
    assert "(for example, life totals or control of two permanents)" in keywords["exchange"]["rules"][0]


def test_examples_are_left_out_and_do_not_end_an_entry():
    keywords = build()["keywords"]
    assert "Example" not in json.dumps(keywords)
    assert len(keywords["exchange"]["rules"]) == 8
    # Example lines sit between 702.14d and 702.14e, and between 702.103d and 702.103e.
    assert len(keywords["landwalk"]["rules"]) == 5
    assert keywords["landwalk"]["rules"][4].startswith("Multiple instances of the same kind of landwalk")
    assert len(keywords["bestow"]["rules"]) == 7


def test_a_cross_reference_alone_in_a_subrule_leaves_no_empty_rule():
    text = excerpt().replace("702.9c Multiple instances of flying on the same creature are redundant.", "702.9c (See rule 702.17.)")
    assert build(text)["keywords"]["flying"]["rules"][-1].startswith("A creature with flying can’t be blocked")
    assert len(build(text)["keywords"]["flying"]["rules"]) == 2


def test_the_entries_stop_at_rule_703():
    late = "702.300. Late\n\xa0\n702.300a Its rule.\n\xa0\n"
    inside = excerpt().replace("703. Turn-Based Actions\n\xa0\n703.1.", late + "703. Turn-Based Actions\n\xa0\n703.1.")
    outside = excerpt().replace("703.1. Turn-based", late + "703.1. Turn-based")
    assert build(inside)["keywords"]["late"]["rules"] == ["Its rule."]
    assert "late" not in build(outside)["keywords"]
    assert len(build(outside)["keywords"]["flying"]["rules"]) == 3


def test_a_subrule_of_another_entry_is_not_taken_by_the_entry_before_it():
    text = excerpt().replace("702.14. Landwalk", "702.14. Landwalk\n\xa0\n702.9d Flying again, out of place.")
    assert len(build(text)["keywords"]["landwalk"]["rules"]) == 5
    assert len(build(text)["keywords"]["flying"]["rules"]) == 3


def test_a_repeated_name_keeps_the_first_entry_and_warns(caplog):
    text = excerpt().replace("702.14. Landwalk", "702.14. Flying")
    with caplog.at_level(logging.WARNING):
        keywords = build(text)["keywords"]
    assert keywords["flying"]["number"] == "702.9" and "landwalk" not in keywords
    assert "702.14 repeats the name of 702.9" in caplog.text


def test_the_ability_words_are_the_sentences_before_the_list_and_the_listed_words():
    words = build()["ability_words"]
    assert list(words) == ["number", "text", "words"]
    assert words["number"] == "207.2c"
    assert words["text"].startswith("An ability word appears in italics at the beginning of some abilities.")
    assert words["text"].endswith("no individual entries in the Comprehensive Rules.")
    assert "The ability words are" not in words["text"]
    assert len(words["words"]) == 61
    assert words["words"][:3] == ["adamant", "addendum", "alliance"]
    # The last word has lost its "and", a word is kept as written, apostrophe and number included.
    assert words["words"][-1] == "will of the council"
    assert "council’s dilemma" in words["words"] and "descend 4" in words["words"]
    assert not any(word.startswith("and ") or word.endswith(".") for word in words["words"])


def test_crlf_lines_parse_the_same_as_lf_lines():
    assert build(excerpt().replace("\n", "\r\n")) == build()


def test_a_line_separator_inside_a_line_does_not_split_it():
    text = excerpt().replace("Flying is an evasion ability.", "Flying is an\u2028evasion ability.")
    assert build(text)["keywords"]["flying"]["rules"][0] == "Flying is an\u2028evasion ability."


def test_the_excerpt_is_as_wizards_serves_the_file():
    assert EXCERPT.startswith(b"\xef\xbb\xbf")
    lines = excerpt().split("\n")
    # Most blank lines are a lone no-break space; the few before a chapter, the glossary and the credits are empty.
    assert lines.count("\u00a0") > 40 and lines[:-1].count("") == 5
    assert [lines[number + 1] for number, line in enumerate(lines[:-1]) if line == ""] == [
        "1. Game Concepts", "2. Parts of a Card", "7. Additional Rules", "Glossary", "Credits",
    ]


@pytest.mark.parametrize(
    "damage, message",
    [
        (lambda text: text.replace("effective as of", "valid from"), "effective date"),
        (lambda text: text.replace("September", "Septembre"), "effective date"),
        (lambda text: text.replace("701.1. ", "701.1 "), "701.1"),
        (lambda text: text.replace("207.2c ", "207.2d "), "207.2c"),
        (lambda text: text.replace(" The ability words are ", " The words are "), "207.2c"),
    ],
)
def test_text_that_is_not_the_rules_raises_instead_of_giving_a_file_with_holes(damage, message):
    with pytest.raises(ParseError, match=message):
        build(damage(excerpt()))


def test_too_few_keywords_or_ability_words_raise(monkeypatch):
    monkeypatch.setattr(rules, "MIN_KEYWORDS", 100)
    with pytest.raises(ParseError, match="Only 6 keywords and 61 ability words"):
        build()
    monkeypatch.setattr(rules, "MIN_KEYWORDS", 1)
    monkeypatch.setattr(rules, "MIN_ABILITY_WORDS", 62)
    with pytest.raises(ParseError, match="Only 6 keywords and 61 ability words"):
        build()


# ---- The whole book

def every_rule(document):
    return [rule for chapter in document["chapters"] for section in chapter["sections"] for rule in section["rules"]]


def rule(document, number):
    return next(found for found in every_rule(document) if found["number"] == number)


def subrule(document, number):
    return next(found for item in every_rule(document) for found in item["subrules"] if found["number"] == number)


def test_the_book_has_the_contracts_fields_in_order():
    document = book()
    assert list(document) == ["schema", "generated_at", "effective_date", "source_url", "chapters", "glossary"]
    assert document["schema"] == 1 and document["generated_at"] == "2026-10-12T14:00:07Z"
    assert document["effective_date"] == "2026-09-25" and document["source_url"] == SOURCE


def test_the_book_is_its_chapters_and_their_sections_and_not_the_contents():
    chapters = book()["chapters"]
    assert [(chapter["number"], chapter["title"]) for chapter in chapters] == [("1", "Game Concepts"), ("2", "Parts of a Card"), ("7", "Additional Rules")]
    assert [[(section["number"], section["title"]) for section in chapter["sections"]] for chapter in chapters] == [
        [("100", "General"), ("101", "The Magic Golden Rules")],
        [("207", "Text Box")],
        [("700", "General"), ("701", "Keyword Actions"), ("702", "Keyword Abilities"), ("703", "Turn-Based Actions")],
    ]
    assert chapters[2]["sections"][0]["rules"] == []


def test_every_key_is_always_present_with_empty_lists_for_no_examples_and_no_subrules():
    document = book()
    assert all(list(chapter) == ["number", "title", "sections"] for chapter in document["chapters"])
    assert all(list(section) == ["number", "title", "rules"] for chapter in document["chapters"] for section in chapter["sections"])
    assert all(list(item) == ["number", "text", "examples", "subrules"] for item in every_rule(document))
    assert all(list(item) == ["number", "text", "examples"] for found in every_rule(document) for item in found["subrules"])
    assert all(list(entry) == ["term", "definition"] for entry in document["glossary"])
    assert rule(document, "100.1")["examples"] == [] and rule(document, "703.1")["subrules"] == []
    assert subrule(document, "100.1a")["examples"] == []


def test_a_rules_number_loses_its_dot_and_its_text_is_the_rest_of_the_line_however_short():
    document = book()
    assert rule(document, "100.1")["text"] == "These Magic rules apply to any Magic game with two or more players, including two-player games and multiplayer games."
    assert rule(document, "701.2")["text"] == "Activate"
    assert [item["number"] for item in rule(document, "701.2")["subrules"]] == ["701.2a"]
    # The introduction of a section is a rule like any other.
    assert rule(document, "701.1")["text"].startswith("Most actions described in a card’s rules text")


def test_subrules_belong_to_the_rule_above_them_in_order():
    document = book()
    assert [(item["number"], item["text"]) for item in rule(document, "100.1")["subrules"]] == [
        ("100.1a", "A two-player game is a game that begins with only two players."),
        ("100.1b", "A multiplayer game is a game that begins with more than two players. See section 8, “Multiplayer Rules.”"),
    ]
    assert [item["number"] for item in rule(document, "701.12")["subrules"]] == [f"701.12{letter}" for letter in "abcdefgh"]


def test_an_example_belongs_to_the_rule_or_subrule_above_it_without_its_prefix():
    document = book()
    assert subrule(document, "701.12a")["examples"] == [
        "If a spell attempts to exchange control of two target creatures but one of those creatures is destroyed before the spell resolves, the spell does nothing to the other creature."
    ]
    assert [example[:30] for example in subrule(document, "702.103d")["examples"]] == ["Aether Storm is an enchantment", "Garruk’s Horde says, in part, "]
    # 101.2's example sits under the rule itself, before its first subrule.
    assert len(rule(document, "101.2")["examples"]) == 1 and subrule(document, "101.2a")["examples"] == []
    assert "Example" not in json.dumps(document)


def test_a_line_that_is_nothing_else_continues_the_text_above_it_after_a_newline():
    document = book()
    assert subrule(document, "100.2a")["text"] == (
        "In constructed play (a way of playing in which each player creates their own deck ahead of time), each deck has a minimum deck size of 60 cards.\n"
        "A constructed deck may contain any number of basic land cards and no more than four of any card with a particular English name other than basic land cards."
    )
    assert rule(document, "101.2")["examples"] == [
        "If one effect reads “You may play an additional land this turn” and another reads “You can’t play lands this turn,”\n"
        "the effect that precludes you from playing lands wins."
    ]


def test_text_is_kept_as_published_with_its_cross_references_and_quotes():
    document = book()
    assert subrule(document, "101.2a")["text"].endswith("don’t fall under this rule. (See rule 113.10.)")
    assert subrule(document, "702.103a")["text"].endswith("follows the rules for paying alternative costs (see 601.2b and 601.2f–h).")
    assert subrule(document, "702.9b")["text"] == "A creature with flying can’t be blocked except by creatures with flying and/or reach. A creature with flying can block a creature with or without flying. (See rule 509, “Declare Blockers Step,” and rule 702.17, “Reach.”)"


def test_everything_keeps_the_order_of_the_text():
    body = excerpt().split("\nCredits\n")[1]
    numbers = re.findall(r"^(\d{3}\.\d+[a-z]*)\.? ", body, re.MULTILINE)
    document = book()
    assert [number for item in every_rule(document) for number in [item["number"]] + [found["number"] for found in item["subrules"]]] == numbers
    assert len(numbers) == 47


def test_a_rule_without_its_dot_and_a_subrule_with_one_are_read_as_the_real_text_writes_them():
    # The edition of 25 September 2026 has "606.5 If the total cost …" and "119.1d. In a two-player Brawl game …".
    text = excerpt().replace("101.1. Whenever", "101.1 Whenever").replace("100.1b A multiplayer", "100.1b. A multiplayer")
    document = book(text)
    assert rule(document, "101.1")["text"].startswith("Whenever a card’s text directly contradicts")
    assert subrule(document, "100.1b")["text"].startswith("A multiplayer game")
    assert document == book()


def test_the_glossary_is_each_term_and_its_definition_in_order():
    glossary = book()["glossary"]
    assert [entry["term"] for entry in glossary] == ["Abandon", "Ability", "Defense", "Flying", "Scry", "Zone-Change Triggers"]
    assert glossary[0]["definition"] == "To turn a face-up ongoing scheme card face down and put it on the bottom of its owner’s scheme deck. See rule 701.33, “Abandon.”"
    assert glossary[-1] == {"term": "Zone-Change Triggers", "definition": "Trigger events that involve objects changing zones. See rule 603.6."}


def test_a_definition_on_several_lines_is_joined_by_newlines_and_its_numbers_are_not_chapters():
    document = book()
    defense = next(entry for entry in document["glossary"] if entry["term"] == "Defense")
    assert defense["definition"] == (
        "1. Part of a card that only battle cards have. A battle card’s defense is printed in its lower right corner. See rule 210, “Defense.”\n"
        "2. A characteristic that only battles can have. See rule 310, “Battles.”"
    )
    assert len(document["chapters"]) == 3
    # "Ability" separates its numbered meanings with U+2028, kept as published.
    ability = next(entry for entry in document["glossary"] if entry["term"] == "Ability")["definition"]
    assert ability.count("\u2028") == 2 and "\n" not in ability


def test_the_credits_are_not_in_the_book():
    assert "Richard Garfield" not in json.dumps(book(), ensure_ascii=False)


def test_the_book_parses_crlf_lines_the_same_as_lf_lines():
    assert book(excerpt().replace("\n", "\r\n")) == book()


@pytest.mark.parametrize(
    "damage, message",
    [
        (lambda text: text.replace("\nCredits\n\xa0\nMagic: The Gathering", "\nThanks\n\xa0\nMagic: The Gathering"), "No contents and credits"),
        (lambda text: text.replace("\nGlossary\n\xa0\nAbandon", "\nGlossaire\n\xa0\nAbandon"), "No glossary"),
        (lambda text: text.replace("\n1. Game Concepts\n\xa0\n100. General", "\n\xa0\n100. General"), "Section 100 comes before the first chapter"),
        (lambda text: text.replace("100. General\n\xa0\n100.1. These", "100. General\n\xa0\n100.0a Out of place.\n\xa0\n100.1. These"), "Subrule 100.0a comes before the first rule"),
        (lambda text: text.replace("207. Text Box\n\xa0\n207.2. ", "207. Text Box\n\xa0\nExample: Out of place.\n\xa0\n207.2. "), "An example comes before the first rule"),
        (lambda text: text.replace("Credits\n\n1. Game Concepts", "Credits\n\nA line out of place.\n1. Game Concepts"), "Text comes before the first chapter"),
        (lambda text: text.replace("Flying\nA keyword ability that restricts", "Flying\n\xa0\nA keyword ability that restricts"), "The glossary's “Flying” has no definition"),
        (lambda text: text.replace("effective as of", "valid from"), "effective date"),
    ],
)
def test_a_book_that_is_not_the_rules_raises_instead_of_giving_a_file_with_holes(damage, message):
    with pytest.raises(ParseError, match=message):
        book(damage(excerpt()))


def test_too_few_chapters_sections_rules_or_glossary_entries_raise(monkeypatch):
    # The excerpt holds 3 chapters, 7 sections, 47 rules and subrules and 6 glossary entries.
    book()
    for floor, count in (("MIN_CHAPTERS", 3), ("MIN_SECTIONS", 7), ("MIN_NUMBERED_RULES", 47), ("MIN_GLOSSARY_ENTRIES", 6)):
        monkeypatch.setattr(rules, floor, count)
        book()
        monkeypatch.setattr(rules, floor, count + 1)
        with pytest.raises(ParseError, match="Only 3 chapters, 7 sections, 47 rules and subrules and 6 glossary entries"):
            book()
        monkeypatch.setattr(rules, floor, 1)


def test_the_floors_are_about_sixty_percent_of_the_real_rules():
    assert FLOORS == (5, 88, 1899, 444)
    assert all(0.55 * count <= floor <= 0.6 * count for floor, count in zip(FLOORS, EDITION_COUNTS))


# ---- Finding the file

def test_the_text_file_is_the_link_on_media_wizards_com_with_its_spaces_as_percent_20():
    assert rules_url(PAGE.decode()) == SOURCE


def test_the_docx_and_pdf_next_to_it_and_a_txt_elsewhere_are_not_taken():
    page = '<a href="https://media.wizards.com/2026/downloads/MagicCompRules 20260925.pdf">PDF</a><a href="https://example.com/MagicCompRules.txt">x</a>'
    with pytest.raises(ParseError, match="No link"):
        rules_url(page)


def test_an_address_that_is_already_encoded_or_relative_to_the_page_is_made_whole():
    assert rules_url('<a href="//media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt">x</a>') == SOURCE
    assert rules_url('<a href="/2026/downloads/MagicCompRules 20260925.txt">x</a>', "https://media.wizards.com/en/rules") == SOURCE
    assert rules_url('<a href="  https://media.wizards.com/2026/downloads/MagicCompRules 20260925.TXT  ">x</a>').endswith("20260925.TXT")


def test_the_file_named_like_the_rules_is_preferred_when_the_page_links_several():
    page = (
        '<a href="https://media.wizards.com/2026/downloads/Glossary Only.txt">a</a>'
        '<a href="https://media.wizards.com/2026/downloads/MagicCompRules 20260925.txt">b</a>'
    )
    assert rules_url(page) == SOURCE
    assert rules_url('<a href="https://media.wizards.com/a/b c.txt">a</a>') == "https://media.wizards.com/a/b%20c.txt"


def test_a_page_without_a_link_raises():
    with pytest.raises(ParseError, match="No link to the Comprehensive Rules text file"):
        rules_url("<html><body><a href='/en/rules'>Rules</a><script>var a='x.txt'</script></body></html>")


# ---- Writing the file

def test_the_page_is_read_first_and_the_file_it_links_to_second(tmp_path):
    wizards = Wizards()
    assert read_rules(wizards) == (excerpt(), SOURCE)
    assert wizards.asked == [PAGE_URL, SOURCE]
    assert write(tmp_path) == ["rules/keywords.json"]
    assert PATH == "rules/keywords.json"


def test_the_file_is_compact_utf8_json_in_the_contracts_shape(tmp_path):
    write(tmp_path, NOW)
    body = (tmp_path / PATH).read_bytes()
    assert b"\n" not in body and b": " not in body and "’".encode() in body
    document = json.loads(body)
    assert document == build()
    assert document["source_url"] == SOURCE and document["effective_date"] == "2026-09-25"


def test_the_state_keeps_the_fingerprint_for_the_next_run(tmp_path):
    write(tmp_path, NOW)
    state = json.loads((tmp_path / STATE_PATH).read_text())
    assert state["sha256"] == fingerprint(build()) == read_fingerprint(tmp_path)
    assert state["effective_date"] == "2026-09-25" and state["source_url"] == SOURCE
    assert STATE_PATH == "state/rules-keywords.json"


def test_the_fingerprint_ignores_when_the_file_was_generated_and_nothing_else():
    assert fingerprint(build(now=NOW)) == fingerprint(build(now=LATER))
    assert fingerprint(build()) != fingerprint(parse_rules(excerpt(), SOURCE.replace("0925", "1001"), NOW))
    assert fingerprint(build()) != fingerprint(build(excerpt().replace("Flying is an evasion ability.", "Flying is an evasion ability!")))


def test_the_same_rules_the_next_day_write_nothing_and_leave_the_published_file_as_it_was(tmp_path):
    write(tmp_path, NOW)
    first = (tmp_path / PATH).read_bytes()
    assert write(tmp_path, LATER) == []
    assert (tmp_path / PATH).read_bytes() == first
    assert json.loads(first)["generated_at"] == "2026-10-12T14:00:07Z"


def test_a_run_starts_with_state_only_so_the_same_rules_then_write_no_file_at_all(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write(first, NOW)
    # The workflow downloads snapshots/ and state/ and nothing else: rules/keywords.json stays on R2.
    (second / "state").mkdir(parents=True)
    (second / STATE_PATH).write_bytes((first / STATE_PATH).read_bytes())
    assert write(second, LATER) == []
    assert not (second / PATH).exists()
    assert (second / STATE_PATH).read_bytes() == (first / STATE_PATH).read_bytes()


def test_new_rules_write_the_file_and_the_state_again(tmp_path):
    write(tmp_path, NOW)
    changed = excerpt().replace("September 25, 2026", "January 16, 2027").replace("Flying is an evasion ability.", "Flying is an evasion ability, always.")
    moved = SOURCE.replace("20260925", "20270116")
    wizards = Wizards(page=PAGE.replace(b"20260925", b"20270116"), text=changed.encode())
    wizards.pages[moved] = wizards.pages.pop(SOURCE)
    assert write(tmp_path, LATER, wizards) == [PATH]
    document = json.loads((tmp_path / PATH).read_text())
    assert document["effective_date"] == "2027-01-16" and document["generated_at"] == "2026-10-13T14:02:31Z"
    assert document["source_url"] == moved
    assert document["keywords"]["flying"]["rules"][0] == "Flying is an evasion ability, always."
    assert read_fingerprint(tmp_path) == fingerprint(document)


def test_a_missing_or_corrupt_state_means_the_file_is_written(tmp_path):
    for number, state in enumerate((None, b"", b"not json", b"[]", b"{}", b'{"sha256":5}', b'{"sha256":null}', b"\xff\xfe\x00")):
        directory = tmp_path / str(number)
        if state is not None:
            (directory / "state").mkdir(parents=True)
            (directory / STATE_PATH).write_bytes(state)
        assert read_fingerprint(directory) is None
        assert write(directory, NOW) == [PATH], state


def test_a_failed_download_writes_nothing_and_raises(tmp_path):
    for broken in (
        Wizards(page=urllib.error.URLError("no route to magic.wizards.com")),
        Wizards(text=urllib.error.HTTPError(SOURCE, 503, "Service Unavailable", {}, None)),
        Wizards(page=b"<html><body>Rules are down for maintenance</body></html>"),
        Wizards(text=b"<html>Access denied</html>"),
        Wizards(text=b"\xff\xfe not utf-8 \xff"),
    ):
        with pytest.raises((OSError, ParseError, UnicodeDecodeError)):
            write(tmp_path, NOW, broken)
        assert not (tmp_path / PATH).exists() and not (tmp_path / STATE_PATH).exists()


# ---- Writing the book

def test_the_book_is_compact_utf8_json_with_its_own_state(tmp_path):
    assert write_book(tmp_path) == [COMPREHENSIVE_PATH]
    body = (tmp_path / COMPREHENSIVE_PATH).read_bytes()
    assert b"\n" not in body and b": " not in body and "’".encode() in body
    assert json.loads(body) == book()
    state = json.loads((tmp_path / COMPREHENSIVE_STATE_PATH).read_text())
    assert state == {"schema": 1, "sha256": fingerprint(book()), "effective_date": "2026-09-25", "source_url": SOURCE}
    assert read_fingerprint(tmp_path, COMPREHENSIVE_STATE_PATH) == state["sha256"]
    assert COMPREHENSIVE_STATE_PATH == "state/rules-comprehensive.json"


def test_the_same_book_the_next_day_writes_nothing_and_leaves_the_published_file_as_it_was(tmp_path):
    write_book(tmp_path, NOW)
    first = (tmp_path / COMPREHENSIVE_PATH).read_bytes()
    assert write_book(tmp_path, LATER) == []
    assert (tmp_path / COMPREHENSIVE_PATH).read_bytes() == first


def test_a_run_that_starts_with_the_books_state_only_writes_no_book(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_book(first, NOW)
    (second / "state").mkdir(parents=True)
    (second / COMPREHENSIVE_STATE_PATH).write_bytes((first / COMPREHENSIVE_STATE_PATH).read_bytes())
    assert write_book(second, LATER) == []
    assert not (second / COMPREHENSIVE_PATH).exists()


def test_each_file_has_its_own_fingerprint(tmp_path):
    write(tmp_path, NOW)
    # The keyword rules' state does not stand for the book's.
    assert write_book(tmp_path, NOW) == [COMPREHENSIVE_PATH]
    # A change outside rules 701 and 702 and 207.2c rewrites the book and not the keywords.
    changed = excerpt().replace("Trigger events that involve objects changing zones.", "Trigger events that involve objects moving between zones.").encode()
    assert write(tmp_path, LATER, Wizards(text=changed)) == []
    assert write_book(tmp_path, LATER, Wizards(text=changed)) == [COMPREHENSIVE_PATH]
    assert json.loads((tmp_path / COMPREHENSIVE_PATH).read_text())["generated_at"] == "2026-10-13T14:02:31Z"
    assert read_fingerprint(tmp_path, STATE_PATH) == fingerprint(build())


def test_a_book_that_cannot_be_parsed_writes_nothing(tmp_path):
    broken = Wizards(text=excerpt().replace("\nGlossary\n", "\nGlossaire\n").encode())
    with pytest.raises(ParseError):
        write_book(tmp_path, NOW, broken)
    assert not (tmp_path / COMPREHENSIVE_PATH).exists() and not (tmp_path / COMPREHENSIVE_STATE_PATH).exists()


# ---- In a run

def test_publish_rules_names_the_files_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    result = report()
    assert entry.publish_rules(tmp_path, result) == ["rules/keywords.json", "rules/comprehensive.json"]
    assert (tmp_path / PATH).is_file() and (tmp_path / COMPREHENSIVE_PATH).is_file()
    assert result.errors == [] and result.warnings == []


def test_publish_rules_names_nothing_when_the_rules_did_not_change(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    entry.publish_rules(tmp_path, report())
    (tmp_path / PATH).unlink()
    (tmp_path / COMPREHENSIVE_PATH).unlink()
    result = report()
    assert entry.publish_rules(tmp_path, result) == []
    assert not (tmp_path / PATH).exists() and not (tmp_path / COMPREHENSIVE_PATH).exists()
    assert result.errors == [] and result.warnings == []


def test_a_failure_in_publish_rules_is_a_warning_and_the_previous_files_stay(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    entry.publish_rules(tmp_path, report())
    paths = (PATH, STATE_PATH, COMPREHENSIVE_PATH, COMPREHENSIVE_STATE_PATH)
    published = [(tmp_path / path).read_bytes() for path in paths]

    def down(url, user_agent):
        raise urllib.error.URLError("Temporary failure in name resolution")

    monkeypatch.setattr(rules, "fetch", down)
    result = report()
    with caplog.at_level(logging.WARNING):
        assert entry.publish_rules(tmp_path, result) == []
    assert result.errors == []
    assert result.warnings == ["rules: <urlopen error Temporary failure in name resolution>"]
    assert "Comprehensive Rules could not be read" in caplog.text
    assert [(tmp_path / path).read_bytes() for path in paths] == published


def test_a_rules_page_that_changed_shape_is_a_warning_too(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards(page=b"<html>moved</html>")(url))
    result = report()
    assert entry.publish_rules(tmp_path, result) == []
    assert result.errors == [] and len(result.warnings) == 1 and result.warnings[0].startswith("rules: No link")
    assert not (tmp_path / PATH).exists() and not (tmp_path / COMPREHENSIVE_PATH).exists()


def test_a_book_that_cannot_be_parsed_still_lets_the_keyword_rules_publish(tmp_path, monkeypatch, caplog):
    text = excerpt().replace("\nCredits\n\xa0\nMagic: The Gathering Original Game Design", "\nThanks\n\xa0\nMagic: The Gathering Original Game Design")
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards(text=text.encode())(url))
    result = report()
    with caplog.at_level(logging.WARNING):
        assert entry.publish_rules(tmp_path, result) == [PATH]
    assert result.errors == [] and result.warnings == ["comprehensive rules: No contents and credits around the Comprehensive Rules"]
    assert "Comprehensive rules failed" in caplog.text
    assert (tmp_path / PATH).is_file() and not (tmp_path / COMPREHENSIVE_PATH).exists() and not (tmp_path / COMPREHENSIVE_STATE_PATH).exists()


def test_keyword_rules_that_cannot_be_parsed_still_let_the_book_publish(tmp_path, monkeypatch):
    text = excerpt().replace("207.2c ", "207.2d ")
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards(text=text.encode())(url))
    result = report()
    assert entry.publish_rules(tmp_path, result) == [COMPREHENSIVE_PATH]
    assert result.warnings == ["keyword rules: No rule 207.2c (the ability words) in the Comprehensive Rules"]
    assert (tmp_path / COMPREHENSIVE_PATH).is_file() and not (tmp_path / PATH).exists() and not (tmp_path / STATE_PATH).exists()


def test_publish_rules_asks_with_the_pipelines_user_agent_and_can_be_turned_off(tmp_path, monkeypatch):
    agents = []

    def record(url, user_agent):
        agents.append(user_agent)
        return Wizards()(url)

    monkeypatch.setattr(rules, "fetch", record)
    monkeypatch.delenv("LOCATOR_USER_AGENT", raising=False)
    # One read of the page and one of the file, for both files.
    assert len(entry.publish_rules(tmp_path / "default", report())) == 2
    assert set(agents) == {"mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"} and len(agents) == 2
    agents.clear()
    monkeypatch.setenv("LOCATOR_USER_AGENT", "test-agent/1")
    entry.publish_rules(tmp_path / "custom", report())
    assert set(agents) == {"test-agent/1"}
    agents.clear()
    monkeypatch.setenv("KEYWORD_RULES", "0")
    assert entry.publish_rules(tmp_path / "off", report()) == []
    assert agents == [] and not (tmp_path / "off").exists()


def test_fetch_asks_with_a_user_agent_and_the_timeout_of_the_other_readers(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"body"

    def urlopen(request, timeout):
        seen.update(url=request.full_url, agent=request.get_header("User-agent"), timeout=timeout)
        return Response()

    monkeypatch.setattr(rules.urllib.request, "urlopen", urlopen)
    assert rules.fetch(SOURCE, "agent/1") == b"body"
    assert seen == {"url": SOURCE, "agent": "agent/1", "timeout": 60}


# ---- In the manifest and the sync

def test_the_keyword_rules_are_an_explore_file_of_the_manifest(tmp_path):
    assert "rules/keywords.json" in FILES and PATH in FILES
    assert is_explore_path(PATH)
    assert not any(is_explore_path(path) for path in ("rules/other.json", "rules/keywords.json.bak", "rules/", "rules/a/keywords.json", "keywords.json", STATE_PATH))
    write(tmp_path, NOW)
    assert explore_paths(tmp_path) == [PATH]
    write_manifest(tmp_path, NOW)
    listed = json.loads((tmp_path / "explore-manifest.json").read_text())["files"]
    assert listed == {PATH: {"sha256": hashlib.sha256((tmp_path / PATH).read_bytes()).hexdigest()}}


def test_a_run_that_writes_no_rules_keeps_the_hash_of_the_run_that_did(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write(first, NOW)
    write_manifest(first, NOW)
    # The next run starts from state/ only. The rules are unchanged, so it writes no file, and the manifest still lists it.
    (second / "state").mkdir(parents=True)
    for name in ("explore-manifest.json", "rules-keywords.json"):
        (second / "state" / name).write_bytes((first / "state" / name).read_bytes())
    assert write(second, LATER) == []
    write_manifest(second, LATER)
    assert json.loads((second / "explore-manifest.json").read_text())["files"] == json.loads((first / "explore-manifest.json").read_text())["files"]
    assert list(json.loads((second / "explore-manifest.json").read_text())["files"]) == [PATH]


def test_the_book_is_not_in_the_manifest_the_app_reads_it_on_demand(tmp_path):
    assert COMPREHENSIVE_PATH == "rules/comprehensive.json"
    assert COMPREHENSIVE_PATH not in FILES and not is_explore_path(COMPREHENSIVE_PATH)
    write(tmp_path, NOW)
    write_book(tmp_path, NOW)
    assert (tmp_path / COMPREHENSIVE_PATH).is_file()
    assert explore_paths(tmp_path) == [PATH]
    write_manifest(tmp_path, NOW)
    assert list(json.loads((tmp_path / "explore-manifest.json").read_text())["files"]) == [PATH]


def test_the_https_sync_downloads_the_state_files():
    script = Path(__file__).resolve().parents[2] / "ops" / "fetch_live.py"
    spec = importlib.util.spec_from_file_location("fetch_live", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert STATE_PATH in module.STATE_FILES
    assert COMPREHENSIVE_STATE_PATH in module.STATE_FILES
