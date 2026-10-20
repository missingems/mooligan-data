import hashlib
import importlib.util
import json
import logging
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import mtgmeta.__main__ as entry
import mtgmeta.rules as rules
from mtgmeta.manifest import FILES, explore_paths, is_explore_path, write_manifest
from mtgmeta.parsing import ParseError
from mtgmeta.rules import PAGE_URL, PATH, STATE_PATH, fingerprint, parse_rules, read_fingerprint, rules_url, write_rules

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 12, 14, 0, 7, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 13, 14, 2, 31, tzinfo=timezone.utc)
SOURCE = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt"
# The excerpt is as Wizards serves the file: a byte order mark, and a lone no-break space for each blank line.
EXCERPT = (FIXTURES / "comprehensive_rules_excerpt.txt").read_bytes()
PAGE = (FIXTURES / "rules_page.html").read_bytes()


@pytest.fixture(autouse=True)
def small_excerpt(monkeypatch):
    """The excerpt has six keywords, where the real rules have hundreds; the floor has its own tests."""
    monkeypatch.setattr(rules, "MIN_KEYWORDS", 1)


def excerpt() -> str:
    return EXCERPT.decode("utf-8-sig")


def build(text=None, now=NOW):
    return parse_rules(excerpt() if text is None else text, SOURCE, now)


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
    assert lines.count("\u00a0") > 40 and "" not in lines[:-1]


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
    assert write_rules(tmp_path, NOW, wizards) == ["rules/keywords.json"]
    assert wizards.asked == [PAGE_URL, SOURCE]
    assert PATH == "rules/keywords.json"


def test_the_file_is_compact_utf8_json_in_the_contracts_shape(tmp_path):
    write_rules(tmp_path, NOW, Wizards())
    body = (tmp_path / PATH).read_bytes()
    assert b"\n" not in body and b": " not in body and "’".encode() in body
    document = json.loads(body)
    assert document == build()
    assert document["source_url"] == SOURCE and document["effective_date"] == "2026-09-25"


def test_the_state_keeps_the_fingerprint_for_the_next_run(tmp_path):
    write_rules(tmp_path, NOW, Wizards())
    state = json.loads((tmp_path / STATE_PATH).read_text())
    assert state["sha256"] == fingerprint(build()) == read_fingerprint(tmp_path)
    assert state["effective_date"] == "2026-09-25" and state["source_url"] == SOURCE
    assert STATE_PATH == "state/rules-keywords.json"


def test_the_fingerprint_ignores_when_the_file_was_generated_and_nothing_else():
    assert fingerprint(build(now=NOW)) == fingerprint(build(now=LATER))
    assert fingerprint(build()) != fingerprint(parse_rules(excerpt(), SOURCE.replace("0925", "1001"), NOW))
    assert fingerprint(build()) != fingerprint(build(excerpt().replace("Flying is an evasion ability.", "Flying is an evasion ability!")))


def test_the_same_rules_the_next_day_write_nothing_and_leave_the_published_file_as_it_was(tmp_path):
    write_rules(tmp_path, NOW, Wizards())
    first = (tmp_path / PATH).read_bytes()
    assert write_rules(tmp_path, LATER, Wizards()) == []
    assert (tmp_path / PATH).read_bytes() == first
    assert json.loads(first)["generated_at"] == "2026-10-12T14:00:07Z"


def test_a_run_starts_with_state_only_so_the_same_rules_then_write_no_file_at_all(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_rules(first, NOW, Wizards())
    # The workflow downloads snapshots/ and state/ and nothing else: rules/keywords.json stays on R2.
    (second / "state").mkdir(parents=True)
    (second / STATE_PATH).write_bytes((first / STATE_PATH).read_bytes())
    assert write_rules(second, LATER, Wizards()) == []
    assert not (second / PATH).exists()
    assert (second / STATE_PATH).read_bytes() == (first / STATE_PATH).read_bytes()


def test_new_rules_write_the_file_and_the_state_again(tmp_path):
    write_rules(tmp_path, NOW, Wizards())
    changed = excerpt().replace("September 25, 2026", "January 16, 2027").replace("Flying is an evasion ability.", "Flying is an evasion ability, always.")
    moved = SOURCE.replace("20260925", "20270116")
    wizards = Wizards(page=PAGE.replace(b"20260925", b"20270116"), text=changed.encode())
    wizards.pages[moved] = wizards.pages.pop(SOURCE)
    assert write_rules(tmp_path, LATER, wizards) == [PATH]
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
        assert write_rules(directory, NOW, Wizards()) == [PATH], state


def test_a_failed_download_writes_nothing_and_raises(tmp_path):
    for broken in (
        Wizards(page=urllib.error.URLError("no route to magic.wizards.com")),
        Wizards(text=urllib.error.HTTPError(SOURCE, 503, "Service Unavailable", {}, None)),
        Wizards(page=b"<html><body>Rules are down for maintenance</body></html>"),
        Wizards(text=b"<html>Access denied</html>"),
        Wizards(text=b"\xff\xfe not utf-8 \xff"),
    ):
        with pytest.raises((OSError, ParseError, UnicodeDecodeError)):
            write_rules(tmp_path, NOW, broken)
        assert not (tmp_path / PATH).exists() and not (tmp_path / STATE_PATH).exists()


# ---- In a run

def test_publish_rules_names_the_file_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    result = report()
    assert entry.publish_rules(tmp_path, result) == ["rules/keywords.json"]
    assert (tmp_path / PATH).is_file() and result.errors == [] and result.warnings == []


def test_publish_rules_names_nothing_when_the_rules_did_not_change(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    entry.publish_rules(tmp_path, report())
    (tmp_path / PATH).unlink()
    result = report()
    assert entry.publish_rules(tmp_path, result) == []
    assert not (tmp_path / PATH).exists() and result.errors == [] and result.warnings == []


def test_a_failure_in_publish_rules_is_a_warning_and_the_previous_file_stays(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards()(url))
    entry.publish_rules(tmp_path, report())
    published, state = (tmp_path / PATH).read_bytes(), (tmp_path / STATE_PATH).read_bytes()

    def down(url, user_agent):
        raise urllib.error.URLError("Temporary failure in name resolution")

    monkeypatch.setattr(rules, "fetch", down)
    result = report()
    with caplog.at_level(logging.WARNING):
        assert entry.publish_rules(tmp_path, result) == []
    assert result.errors == []
    assert result.warnings == ["keyword rules: <urlopen error Temporary failure in name resolution>"]
    assert "Keyword rules failed" in caplog.text
    assert (tmp_path / PATH).read_bytes() == published and (tmp_path / STATE_PATH).read_bytes() == state


def test_a_rules_page_that_changed_shape_is_a_warning_too(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "fetch", lambda url, user_agent: Wizards(page=b"<html>moved</html>")(url))
    result = report()
    assert entry.publish_rules(tmp_path, result) == []
    assert result.errors == [] and len(result.warnings) == 1 and result.warnings[0].startswith("keyword rules: No link")
    assert not (tmp_path / PATH).exists()


def test_publish_rules_asks_with_the_pipelines_user_agent_and_can_be_turned_off(tmp_path, monkeypatch):
    agents = []

    def record(url, user_agent):
        agents.append(user_agent)
        return Wizards()(url)

    monkeypatch.setattr(rules, "fetch", record)
    monkeypatch.delenv("LOCATOR_USER_AGENT", raising=False)
    entry.publish_rules(tmp_path / "default", report())
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
    write_rules(tmp_path, NOW, Wizards())
    assert explore_paths(tmp_path) == [PATH]
    write_manifest(tmp_path, NOW)
    listed = json.loads((tmp_path / "explore-manifest.json").read_text())["files"]
    assert listed == {PATH: {"sha256": hashlib.sha256((tmp_path / PATH).read_bytes()).hexdigest()}}


def test_a_run_that_writes_no_rules_keeps_the_hash_of_the_run_that_did(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_rules(first, NOW, Wizards())
    write_manifest(first, NOW)
    # The next run starts from state/ only. The rules are unchanged, so it writes no file, and the manifest still lists it.
    (second / "state").mkdir(parents=True)
    for name in ("explore-manifest.json", "rules-keywords.json"):
        (second / "state" / name).write_bytes((first / "state" / name).read_bytes())
    assert write_rules(second, LATER, Wizards()) == []
    write_manifest(second, LATER)
    assert json.loads((second / "explore-manifest.json").read_text())["files"] == json.loads((first / "explore-manifest.json").read_text())["files"]
    assert list(json.loads((second / "explore-manifest.json").read_text())["files"]) == [PATH]


def test_the_https_sync_downloads_the_state_file():
    script = Path(__file__).resolve().parents[2] / "ops" / "fetch_live.py"
    spec = importlib.util.spec_from_file_location("fetch_live", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert STATE_PATH in module.STATE_FILES
