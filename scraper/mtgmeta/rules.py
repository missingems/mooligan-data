"""rules/keywords.json and rules/comprehensive.json: Magic's Comprehensive Rules, by keyword and in full.

Wizards publishes the Comprehensive Rules as a text file a few times a year, linked from magic.wizards.com/en/rules
(the file name carries the date, so the link is found on the page and never hard-coded). A run reads the page and
downloads the file once (`read_rules`), and writes two files from it:

- rules/keywords.json keeps three things: the named entries of rule 701 (keyword actions) and 702 (keyword abilities),
  the ability words listed in rule 207.2c, and the date the rules take effect.
- rules/comprehensive.json is the whole book: its chapters, sections, rules with their subrules and examples, and the
  glossary, in the order of the text.

The parsing (`parse_rules`, `parse_comprehensive_rules`) is separate from the network (`read_rules` takes the function
that downloads), and each file is rewritten only when its rules changed: the rules are the same for months, and a file
whose bytes did not change keeps its hash and its ETag. See docs/data-format.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .parsing import ParseError

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "rules/keywords.json"
# The hash of the last published rules, so a run can tell that the file it would write is the one already published.
STATE_PATH = "state/rules-keywords.json"
COMPREHENSIVE_PATH = "rules/comprehensive.json"
COMPREHENSIVE_STATE_PATH = "state/rules-comprehensive.json"
PAGE_URL = "https://magic.wizards.com/en/rules"
HOST = "media.wizards.com"

# A source that gives fewer entries than this has changed shape (or came down cut short): nothing is published.
MIN_KEYWORDS = 100
MIN_ABILITY_WORDS = 20
# 60% of what the edition of 25 September 2026 holds: 9 chapters, 147 sections, 3,166 rules and subrules, 741 glossary entries.
MIN_CHAPTERS = 5
MIN_SECTIONS = 88
MIN_NUMBERED_RULES = 1899
MIN_GLOSSARY_ENTRIES = 444

# The source's blank lines are a lone no-break space.
NO_BREAK_SPACE = "\u00a0"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
EFFECTIVE = re.compile(r"effective as of ([A-Za-z]+) (\d{1,2}), (\d{4})\.")
# "701.22. Scry": a named entry. "701.1. Most actions described …" is the section's introduction, a sentence.
HEADER = re.compile(r"^(70[12]\.\d+)\. (.+)$")
SUBRULE = re.compile(r"^(70[12]\.\d+)[a-z]+ (.+)$")
ABILITY_WORDS = re.compile(r"^207\.2c (.+)$")
# "(See rule 509, “Declare Blockers Step,” and rule 702.17, “Reach.”)", "(see rules 702.2 and 702.3)", "(see 601.2b and 601.2f–h)".
CROSS_REFERENCE = re.compile(r"\s*\([Ss]ee (?:also )?(?:rules? |sections? )?\d[^)]*\)")
MAX_NAME_LENGTH = 60

# The book lies between the contents, which end with "Credits", and the credits themselves; the glossary closes it.
CREDITS = "Credits"
GLOSSARY = "Glossary"
# Its lines, tried in this order: "1. Game Concepts", "100. General", "100.1. These Magic rules …", "100.1a A two-player …"
# and "Example: …". A rule's dot is optional and a subrule may have one: the text has "606.5 If …" and "119.1d. In …".
BOOK_CHAPTER = re.compile(r"^(\d)\. (.+)$")
BOOK_SECTION = re.compile(r"^(\d{3})\. (.+)$")
BOOK_RULE = re.compile(r"^(\d{3}\.\d+)\.? (.+)$")
BOOK_SUBRULE = re.compile(r"^(\d{3}\.\d+[a-z]+)\.? (.+)$")
BOOK_EXAMPLE = re.compile(r"^Example: (.+)$")


def rules_url(page: str, page_url: str = PAGE_URL) -> str:
    """The Comprehensive Rules text file's link on Wizards' rules page.

    The links contain literal spaces ("MagicCompRules 20260925.txt"), which become %20. Only a `.txt` on
    media.wizards.com counts, and one named like the rules is preferred when the page links several.
    """
    found = []
    for anchor in BeautifulSoup(page, "html.parser").find_all("a", href=True):
        url = urljoin(page_url, anchor["href"].strip().replace(" ", "%20"))
        parsed = urlparse(url)
        if parsed.hostname == HOST and parsed.path.lower().endswith(".txt"):
            found.append(url)
    if not found:
        raise ParseError(f"No link to the Comprehensive Rules text file on {page_url}")
    return next((url for url in found if "comprules" in url.lower()), found[0])


def effective_date(lines: List[str]) -> str:
    """The date from "These rules are effective as of September 25, 2026.", as 2026-09-25."""
    for line in lines[:20]:
        match = EFFECTIVE.search(line)
        if match and match.group(1) in MONTHS:
            return f"{int(match.group(3)):04d}-{MONTHS.index(match.group(1)) + 1:02d}-{int(match.group(2)):02d}"
    raise ParseError("No effective date at the top of the Comprehensive Rules")


def split_lines(text: str) -> List[str]:
    """The text's lines, trimmed, with its blank lines (a lone no-break space) empty."""
    # Not splitlines(): the rules hold U+2028 inside some lines.
    return [line.replace(NO_BREAK_SPACE, " ").strip() for line in re.split(r"\r\n|\r|\n", text)]


def stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rules(text: str, source_url: str, now: datetime) -> dict:
    """rules/keywords.json, from the text of the Comprehensive Rules.

    `keywords` holds each named entry of 701 and 702 by its lower-cased name, with its subrules in order, cross
    references removed and examples left out. Raises `ParseError` when the text is not the rules, rather than
    produce a file with little in it.
    """
    lines = split_lines(text)
    effective = effective_date(lines)

    start = next((number for number, line in enumerate(lines) if line.startswith("701.1. ")), None)
    if start is None:
        raise ParseError("No rule 701.1 in the Comprehensive Rules")
    keywords: Dict[str, dict] = {}
    current: Optional[dict] = None
    for line in lines[start:]:
        if line.startswith("703."):
            break
        header = HEADER.match(line)
        if header:
            number, name = header.groups()
            if len(name) > MAX_NAME_LENGTH or name.endswith("."):
                current = None
            elif name.lower() in keywords:
                log.warning("Keyword rules: %s repeats the name of %s (%s); skipped", number, keywords[name.lower()]["number"], name)
                current = None
            else:
                current = {"name": name, "number": number, "rules": []}
                keywords[name.lower()] = current
            continue
        subrule = SUBRULE.match(line)
        if subrule and current and subrule.group(1) == current["number"]:
            rule = CROSS_REFERENCE.sub("", subrule.group(2)).strip()
            if rule:
                current["rules"].append(rule)

    sentence = next((match.group(1) for line in lines if (match := ABILITY_WORDS.match(line))), "")
    summary, separator, listed = sentence.partition(" The ability words are ")
    if not separator:
        raise ParseError("No rule 207.2c (the ability words) in the Comprehensive Rules")
    words = [word.strip().removeprefix("and ").strip() for word in listed.rstrip(".").split(",")]
    words = [word for word in words if word]

    if len(keywords) < MIN_KEYWORDS or len(words) < MIN_ABILITY_WORDS:
        raise ParseError(f"Only {len(keywords)} keywords and {len(words)} ability words in the Comprehensive Rules")
    return {
        "schema": SCHEMA,
        "generated_at": stamp(now),
        "effective_date": effective,
        "source_url": source_url,
        "keywords": keywords,
        "ability_words": {"number": "207.2c", "text": summary.strip(), "words": words},
    }


def book_chapters(lines: List[str]) -> List[dict]:
    """The chapters of the book's lines, each holding its sections, each holding its rules.

    An example belongs to the rule or subrule above it, and a line that is none of these continues the text above it,
    after a newline. Raises `ParseError` for a line with nothing above it to belong to.
    """
    chapters: List[dict] = []
    section: Optional[dict] = None
    rule: Optional[dict] = None
    # The rule or subrule an example belongs to, and the text a continuation line goes on: its holder and its key.
    owner: Optional[dict] = None
    continued: Optional[tuple] = None
    for line in lines:
        if not line:
            continue
        if match := BOOK_CHAPTER.match(line):
            chapters.append({"number": match.group(1), "title": match.group(2), "sections": []})
            section = rule = owner = None
            continued = (chapters[-1], "title")
        elif match := BOOK_SECTION.match(line):
            if not chapters:
                raise ParseError(f"Section {match.group(1)} comes before the first chapter of the Comprehensive Rules")
            section = {"number": match.group(1), "title": match.group(2), "rules": []}
            chapters[-1]["sections"].append(section)
            rule = owner = None
            continued = (section, "title")
        elif match := BOOK_RULE.match(line):
            if section is None:
                raise ParseError(f"Rule {match.group(1)} comes before the first section of the Comprehensive Rules")
            rule = owner = {"number": match.group(1), "text": match.group(2), "examples": [], "subrules": []}
            section["rules"].append(rule)
            continued = (rule, "text")
        elif match := BOOK_SUBRULE.match(line):
            if rule is None:
                raise ParseError(f"Subrule {match.group(1)} comes before the first rule of its section in the Comprehensive Rules")
            owner = {"number": match.group(1), "text": match.group(2), "examples": []}
            rule["subrules"].append(owner)
            continued = (owner, "text")
        elif match := BOOK_EXAMPLE.match(line):
            if owner is None:
                raise ParseError(f"An example comes before the first rule of its section in the Comprehensive Rules: {line[:60]}")
            owner["examples"].append(match.group(1))
            continued = (owner["examples"], len(owner["examples"]) - 1)
        else:
            if continued is None:
                raise ParseError(f"Text comes before the first chapter of the Comprehensive Rules: {line[:60]}")
            holder, key = continued
            holder[key] += "\n" + line
    return chapters


def book_glossary(lines: List[str]) -> List[dict]:
    """The glossary's entries: a term, then its definition on one line or more (joined by newlines), then a blank line."""
    entries: List[dict] = []
    block: List[str] = []
    for line in lines + [""]:
        if line:
            block.append(line)
        elif block:
            if len(block) < 2:
                raise ParseError(f"The glossary's “{block[0][:60]}” has no definition in the Comprehensive Rules")
            entries.append({"term": block[0], "definition": "\n".join(block[1:])})
            block = []
    return entries


def book_counts(document: dict) -> Tuple[int, int, int, int]:
    """The chapters, sections, rules and subrules, and glossary entries of rules/comprehensive.json."""
    sections = [section for chapter in document["chapters"] for section in chapter["sections"]]
    rules = [rule for section in sections for rule in section["rules"]]
    return len(document["chapters"]), len(sections), len(rules) + sum(len(rule["subrules"]) for rule in rules), len(document["glossary"])


def parse_comprehensive_rules(text: str, source_url: str, now: datetime) -> dict:
    """rules/comprehensive.json, from the text of the Comprehensive Rules.

    The book runs from the line after the first "Credits" (the last line of the contents) to the second (the credits
    themselves), and its glossary from the line "Glossary" to there. Text is kept as published, cross references,
    curly quotes and U+2028 included. Raises `ParseError` when the text is not the rules, rather than produce a file
    with little in it.
    """
    lines = split_lines(text)
    effective = effective_date(lines)
    credits = [number for number, line in enumerate(lines) if line == CREDITS]
    if len(credits) < 2:
        raise ParseError("No contents and credits around the Comprehensive Rules")
    body = lines[credits[0] + 1:credits[1]]
    if GLOSSARY not in body:
        raise ParseError("No glossary in the Comprehensive Rules")
    glossary = body.index(GLOSSARY)
    document = {
        "schema": SCHEMA,
        "generated_at": stamp(now),
        "effective_date": effective,
        "source_url": source_url,
        "chapters": book_chapters(body[:glossary]),
        "glossary": book_glossary(body[glossary + 1:]),
    }
    chapters, sections, numbered, entries = book_counts(document)
    if chapters < MIN_CHAPTERS or sections < MIN_SECTIONS or numbered < MIN_NUMBERED_RULES or entries < MIN_GLOSSARY_ENTRIES:
        raise ParseError(
            f"Only {chapters} chapters, {sections} sections, {numbered} rules and subrules and {entries} glossary entries in the Comprehensive Rules"
        )
    return document


def fingerprint(document: dict) -> str:
    """The SHA-256 of the file's content without its `generated_at`: equal for two runs that read the same rules."""
    content = {key: value for key, value in document.items() if key != "generated_at"}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def read_fingerprint(directory: Path, state_path: str = STATE_PATH) -> Optional[str]:
    """The fingerprint of the file the run before published, from `state/`; None when it is missing or unreadable."""
    try:
        digest = json.loads((directory / state_path).read_text(encoding="utf-8"))["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return digest if isinstance(digest, str) else None


def fetch(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,text/plain"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def read_rules(download: Callable[[str], bytes]) -> Tuple[str, str]:
    """The text of the Comprehensive Rules and its link: the rules page is read first, then the file it links to.

    `download` returns the bytes at a URL. A failure is raised for the caller to report.
    """
    page = download(PAGE_URL).decode("utf-8", "replace")
    url = rules_url(page)
    return download(url).decode("utf-8-sig"), url


def write_document(directory: Path, document: dict, path: str, state_path: str) -> List[str]:
    """Writes `document` at `path` and its fingerprint at `state_path`, and returns the path; returns no path when the
    fingerprint is the one the run before published.

    The previous file is not in `directory` (a run starts from `snapshots/` and `state/` only), so "keeping" it means
    writing nothing: it stays published, and the manifest carries its hash over.
    """
    digest = fingerprint(document)
    if digest == read_fingerprint(directory, state_path):
        return []
    (directory / path).parent.mkdir(parents=True, exist_ok=True)
    (directory / path).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    state = {"schema": SCHEMA, "sha256": digest, "effective_date": document["effective_date"], "source_url": document["source_url"]}
    (directory / state_path).parent.mkdir(parents=True, exist_ok=True)
    (directory / state_path).write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    return [path]


def write_rules(directory: Path, now: datetime, text: str, source_url: str) -> List[str]:
    """Writes rules/keywords.json from the rules `read_rules` read, and returns its path, or no path when they are the
    same as the last run's (see `fingerprint`). A text that is not the rules raises `ParseError` and writes nothing.
    """
    document = parse_rules(text, source_url, now)
    written = write_document(directory, document, PATH, STATE_PATH)
    if not written:
        log.info("Keyword rules: unchanged since the last run (effective %s)", document["effective_date"])
        return []
    log.info(
        "Keyword rules: %d keywords and %d ability words, effective %s",
        len(document["keywords"]), len(document["ability_words"]["words"]), document["effective_date"],
    )
    return written


def write_comprehensive_rules(directory: Path, now: datetime, text: str, source_url: str) -> List[str]:
    """Writes rules/comprehensive.json from the rules `read_rules` read, as `write_rules` writes rules/keywords.json."""
    document = parse_comprehensive_rules(text, source_url, now)
    written = write_document(directory, document, COMPREHENSIVE_PATH, COMPREHENSIVE_STATE_PATH)
    if not written:
        log.info("Comprehensive rules: unchanged since the last run (effective %s)", document["effective_date"])
        return []
    log.info(
        "Comprehensive rules: %d chapters, %d sections, %d rules and subrules and %d glossary entries, effective %s",
        *book_counts(document), document["effective_date"],
    )
    return written
