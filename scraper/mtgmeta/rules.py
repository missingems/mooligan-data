"""rules/keywords.json: the keyword actions, keyword abilities and ability words of Magic's Comprehensive Rules.

Wizards publishes the Comprehensive Rules as a text file a few times a year, linked from magic.wizards.com/en/rules
(the file name carries the date, so the link is found on the page and never hard-coded). A run reads the page, downloads
the file and keeps three things from it: the named entries of rule 701 (keyword actions) and 702 (keyword abilities),
the ability words listed in rule 207.2c, and the date the rules take effect. Everything else in the rules is left out.

The parsing (`parse_rules`) is separate from the network (`write_rules` takes the function that downloads), and the
file is rewritten only when the rules changed: the rules are the same for months, and a file whose bytes did not
change keeps its hash and its ETag. See docs/data-format.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .parsing import ParseError

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "rules/keywords.json"
# The hash of the last published rules, so a run can tell that the file it would write is the one already published.
STATE_PATH = "state/rules-keywords.json"
PAGE_URL = "https://magic.wizards.com/en/rules"
HOST = "media.wizards.com"

# A source that gives fewer entries than this has changed shape (or came down cut short): nothing is published.
MIN_KEYWORDS = 100
MIN_ABILITY_WORDS = 20

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


def parse_rules(text: str, source_url: str, now: datetime) -> dict:
    """The file, from the text of the Comprehensive Rules.

    `keywords` holds each named entry of 701 and 702 by its lower-cased name, with its subrules in order, cross
    references removed and examples left out. Raises `ParseError` when the text is not the rules, rather than
    produce a file with little in it.
    """
    # Not splitlines(): the rules hold U+2028 inside some lines.
    lines = [line.replace(NO_BREAK_SPACE, " ").strip() for line in re.split(r"\r\n|\r|\n", text)]
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
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "effective_date": effective,
        "source_url": source_url,
        "keywords": keywords,
        "ability_words": {"number": "207.2c", "text": summary.strip(), "words": words},
    }


def fingerprint(document: dict) -> str:
    """The SHA-256 of the file's content without its `generated_at`: equal for two runs that read the same rules."""
    content = {key: value for key, value in document.items() if key != "generated_at"}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def read_fingerprint(directory: Path) -> Optional[str]:
    """The fingerprint of the file the run before published, from `state/`; None when it is missing or unreadable."""
    try:
        digest = json.loads((directory / STATE_PATH).read_text(encoding="utf-8"))["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return digest if isinstance(digest, str) else None


def fetch(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,text/plain"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def write_rules(directory: Path, now: datetime, download: Callable[[str], bytes]) -> List[str]:
    """Writes rules/keywords.json into `directory` and returns its path, or returns no path when there is nothing to publish.

    `download` returns the bytes at a URL. The previous file is not in `directory` (a run starts from `snapshots/` and
    `state/` only), so "keeping" it means writing nothing: it stays published, and the manifest carries its hash over.
    That is what happens when the rules are the same as the last run's (see `fingerprint`), and when anything fails,
    which is raised for the caller to report.
    """
    page = download(PAGE_URL).decode("utf-8", "replace")
    url = rules_url(page)
    document = parse_rules(download(url).decode("utf-8-sig"), url, now)
    digest = fingerprint(document)
    if digest == read_fingerprint(directory):
        log.info("Keyword rules: unchanged since the last run (effective %s)", document["effective_date"])
        return []
    path = directory / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    state = {"schema": SCHEMA, "sha256": digest, "effective_date": document["effective_date"], "source_url": url}
    (directory / STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (directory / STATE_PATH).write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    log.info(
        "Keyword rules: %d keywords and %d ability words, effective %s",
        len(document["keywords"]), len(document["ability_words"]["words"]), document["effective_date"],
    )
    return [PATH]
