"""sets/mechanics.json: the mechanics each set introduced, keyed by Scryfall set code, for "new in this set" on a set page.

A keyword is new to a set when the earliest printing of a card with it, across the paper sets, is in that set. Scryfall's
`keywords` array on each printing in its default-cards file says which keywords a card has, and `released_at` when the printing
came out. Only the sets that can introduce a mechanic count (expansions, core sets, Masters, Commander decks and the like, not
promos, tokens or Secret Lair), so a promo that is out before its set does not take its mechanics.

Only a word that is a keyword counts: one in the Comprehensive Rules (`rules/keywords.json`, which says whether it is a
keyword ability, 702, a keyword action, 701, or an ability word, 207.2c, and gives its rules) or in Scryfall's catalogs of
keyword abilities, keyword actions and ability words, which name a new set's mechanics before the rules do. That leaves out the
many names of one card's abilities Scryfall also puts in `keywords`. The evergreen keywords and what was first printed before 1999
are left out, as are variants of one mechanic (every "...cycling", every landwalk, multikicker, nightbound).

A set's examples are its cards with the keyword, the most played first (by EDHREC rank, else by rarity). See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "sets/mechanics.json"
RULES_PATH = "rules/keywords.json"
CATALOG_URL = "https://api.scryfall.com/catalog/"
CATALOGS = (("keyword-abilities", "keyword ability"), ("keyword-actions", "keyword action"), ("ability-words", "ability word"))
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
CATALOG_DELAY = 0.1
FIRST_RELEASE = "1999-01-01"
EXAMPLES = 3
# The sets that can introduce a mechanic, and the order one wins a tie in: a set and its Commander decks come out together.
SET_PRIORITY = {
    "expansion": 0, "core": 0, "draft_innovation": 0, "funny": 0,
    "masters": 1, "commander": 2,
    "starter": 3, "planechase": 3, "archenemy": 3, "eternal": 3, "duel_deck": 3, "premium_deck": 3, "from_the_vault": 3,
}
SKIPPED_LAYOUTS = {"token", "double_faced_token", "art_series", "emblem", "vanguard", "scheme", "planar"}
RARITY = {"common": 0, "uncommon": 1, "rare": 2, "special": 2, "mythic": 3, "bonus": 3}
EVERGREEN = {
    "deathtouch", "defender", "double strike", "enchant", "equip", "first strike", "flash", "flying", "haste", "hexproof",
    "indestructible", "lifelink", "menace", "protection", "prowess", "reach", "trample", "vigilance", "ward",
    "attach", "counter", "create", "destroy", "discard", "exchange", "exile", "fight", "mill", "play", "regenerate", "reveal",
    "sacrifice", "scry", "search", "shuffle", "tap", "untap",
}
# A mechanic Scryfall lists under more than one name, and the name the rules (and the first set) know it by.
ALIASES = {
    "multikicker": "kicker", "megamorph": "morph", "commander ninjutsu": "ninjutsu", "partner with": "partner",
    "hexproof from": "hexproof", "nightbound": "daybound", "protection from": "protection",
}
LANDWALK = re.compile(r"^(?:(?:legendary|nonbasic|snow|basic) )?(?:plains|island|swamp|mountain|forest|desert|land)walk$")
# The keyword, then no more than a few words, then the reminder text in parentheses: "Kicker {1}{R} (You may pay…)".
BETWEEN = re.compile(r"[^().]{0,60}\.?\s*")


class Lexicon(NamedTuple):
    """What the rules and Scryfall's catalogs say a keyword is: its kind, its name as written, and the rules for it."""
    kinds: Dict[str, str]
    names: Dict[str, str]
    rules: Dict[str, str]


class Found:
    """A keyword's earliest printings: the date, and by set the cards that carry it."""

    def __init__(self, date: str, name: str):
        self.date, self.name = date, name
        self.sets: Dict[str, Dict[str, dict]] = {}


def normal(word: str) -> str:
    return word.replace("’", "'").strip().lower()


def read_catalogs(scryfall: Callable[[str], bytes], sleep: Callable[[float], None] = time.sleep) -> Dict[str, Tuple[str, str]]:
    """Scryfall's keyword abilities, keyword actions and ability words, each by its lower-case name with its kind and name."""
    found: Dict[str, Tuple[str, str]] = {}
    for index, (catalog, kind) in enumerate(CATALOGS):
        if index:
            sleep(CATALOG_DELAY)
        for name in json.loads(scryfall(CATALOG_URL + catalog)).get("data", []):
            found.setdefault(normal(name), (kind, name))
    return found


def build_lexicon(rules: dict, catalogs: Dict[str, Tuple[str, str]]) -> Lexicon:
    """The rules' keywords first (their kind comes from the rule's number), then the catalogs' for what the rules do not have yet."""
    kinds: Dict[str, str] = {}
    names: Dict[str, str] = {}
    texts: Dict[str, str] = {}
    for key, entry in (rules.get("keywords") or {}).items():
        number = str(entry.get("number", ""))
        kind = "keyword action" if number.startswith("701.") else "keyword ability" if number.startswith("702.") else None
        if kind:
            kinds[normal(key)] = kind
            names[normal(key)] = entry.get("name") or key
            texts[normal(key)] = "\n".join(entry.get("rules") or [])
    ability_words = rules.get("ability_words") or {}
    for word in ability_words.get("words") or []:
        key = normal(word)
        for variant in {key, re.sub(r"\s+\d+$", "", key)}:
            if variant not in kinds:
                kinds[variant] = "ability word"
                names[variant] = variant
                texts[variant] = ability_words.get("text") or ""
    for key, (kind, name) in catalogs.items():
        kinds.setdefault(key, kind)
        names[key] = name
        texts.setdefault(key, "")
    return Lexicon(kinds, names, texts)


def canonical(keyword: str, lexicon: Lexicon) -> Optional[str]:
    """The key a printing's keyword is counted under: its own, or the mechanic it is a variant of; None when it is not a keyword."""
    key = normal(keyword)
    if key not in lexicon.kinds:
        return None
    parent = ALIASES.get(key)
    if parent is None and key.endswith("cycling") and key != "cycling":
        parent = "cycling"
    if parent is None and LANDWALK.match(key) and key != "landwalk":
        parent = "landwalk"
    return parent if parent in lexicon.kinds else key


def oracle_text(card: dict) -> str:
    faces = card.get("card_faces") or []
    return "\n".join(face.get("oracle_text") or "" for face in faces) if faces else card.get("oracle_text") or ""


def oracle_id(card: dict) -> Optional[str]:
    return card.get("oracle_id") or next((face.get("oracle_id") for face in card.get("card_faces") or [] if face.get("oracle_id")), None)


def remember(found: Dict[str, Found], key: str, card: dict, name: str) -> None:
    """Keeps the card under the keyword when its printing is as early as any seen, and forgets the later ones when it is earlier."""
    date, code, identity = card["released_at"], card["set"], oracle_id(card)
    entry = found.get(key)
    if entry is None or date < entry.date:
        entry = found[key] = Found(date, name)
    if date > entry.date or date < FIRST_RELEASE or not identity:
        return
    cards = entry.sets.setdefault(code, {})
    rank = card.get("edhrec_rank")
    previous = cards.get(identity)
    if previous is None or (rank is not None and (previous["rank"] is None or rank < previous["rank"])):
        cards[identity] = {
            "oracle_id": identity, "name": card.get("name") or "", "rank": rank,
            "rarity": RARITY.get(card.get("rarity") or "", 0), "text": oracle_text(card),
        }


def collect(cards: Iterable[dict], lexicon: Lexicon) -> Tuple[Dict[str, Found], Dict[str, int]]:
    """Each keyword's earliest printings, and every set that can introduce one with its tie-break priority."""
    found: Dict[str, Found] = {}
    sets: Dict[str, int] = {}
    for card in cards:
        priority = SET_PRIORITY.get(card.get("set_type") or "")
        if priority is None or card.get("digital") or "paper" not in (card.get("games") or []) or card.get("layout") in SKIPPED_LAYOUTS:
            continue
        if not card.get("set") or not card.get("released_at"):
            continue
        sets[card["set"]] = priority
        for keyword in card.get("keywords") or []:
            key = canonical(keyword, lexicon)
            if key is not None and key not in EVERGREEN:
                remember(found, key, card, keyword)
    return found, sets


def reminder(keyword: str, text: str) -> str:
    """The reminder text in parentheses that follows the keyword on one of the card's lines, without the parentheses; "" when none does."""
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?![A-Za-z])", re.I)
    for line in text.split("\n"):
        for match in pattern.finditer(line):
            tail = line[match.end():]
            opening = tail.find("(")
            if opening < 0 or not BETWEEN.fullmatch(tail[:opening]):
                continue
            closing = tail.find(")", opening)
            if closing > opening + 1:
                return tail[opening + 1:closing].strip()
    return ""


def order(candidates: Iterable[dict]) -> List[dict]:
    """The most played cards first: lowest EDHREC rank, then the rarest, then by name."""
    return sorted(candidates, key=lambda card: (card["rank"] is None, card["rank"] or 0, -card["rarity"], card["name"], card["oracle_id"]))


def entry_for(key: str, found: Found, code: str, lexicon: Lexicon) -> dict:
    kind = lexicon.kinds[key]
    cards = order(found.sets[code].values())
    text = ""
    if kind != "ability word":
        spellings = {found.name, lexicon.names.get(key, found.name)}
        text = next((found_text for card in cards for spelling in sorted(spellings) if (found_text := reminder(spelling, card["text"]))), "")
    return {
        "keyword": lexicon.names.get(key) or found.name,
        "kind": kind,
        "reminder": text,
        "rules": lexicon.rules.get(key, ""),
        "example_oracle_ids": [card["oracle_id"] for card in cards[:EXAMPLES]],
        "first_set": code,
        "_cards": len(cards),
    }


def build(cards: Iterable[dict], lexicon: Lexicon, now: datetime) -> dict:
    found, priorities = collect(cards, lexicon)
    sets: Dict[str, List[dict]] = {code: [] for code in sorted(priorities)}
    for key, entry in found.items():
        if entry.date < FIRST_RELEASE or not entry.sets:
            continue
        code = min(entry.sets, key=lambda candidate: (priorities[candidate], -len(entry.sets[candidate]), candidate))
        sets[code].append(entry_for(key, entry, code, lexicon))
    for mechanics in sets.values():
        mechanics.sort(key=lambda item: (-item["_cards"], item["keyword"].lower()))
        for item in mechanics:
            del item["_cards"]
    return {"schema": SCHEMA, "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sets": sets}


def load_rules(directory: Path, download: Callable[[str], bytes], url: Optional[str]) -> dict:
    """The keyword rules this run wrote (`rules/keywords.json` is written only when Wizards' rules changed), else the published file."""
    try:
        return json.loads((directory / RULES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not url:
        raise RuntimeError("No rules/keywords.json in the work directory and no URL to read it from")
    return json.loads(download(url))


def write_set_mechanics(
    directory: Path, now: datetime, cards: Iterable[dict], scryfall: Callable[[str], bytes],
    rules: Callable[[], dict], sleep: Callable[[float], None] = time.sleep,
) -> List[str]:
    """Writes sets/mechanics.json into `directory` and returns its path.

    `cards` are Scryfall's default cards, `scryfall` returns the bytes of a Scryfall API URL, and `rules` the keyword rules
    document. Any of them failing is raised, and writes nothing, so the published file stays.
    """
    lexicon = build_lexicon(rules(), read_catalogs(scryfall, sleep))
    document = build(cards, lexicon, now)
    path = directory / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info(
        "Set mechanics: %d mechanics new to %d of %d sets",
        sum(len(mechanics) for mechanics in document["sets"].values()), sum(1 for mechanics in document["sets"].values() if mechanics), len(document["sets"]),
    )
    return [PATH]


def fetch(url: str, user_agent: str = USER_AGENT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(args: List[str]) -> int:
    """`python -m mtgmeta set-mechanics DIR`: writes DIR/sets/mechanics.json, reading the rules from DIR/rules/keywords.json or the published file."""
    import argparse
    import os

    from .scryfall import DEFAULT_CARDS_URL, _bulk_download_uri, bulk_cards

    parser = argparse.ArgumentParser(prog="mtgmeta set-mechanics", description=main.__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args(args)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = os.environ.get("SET_MECHANICS_USER_AGENT", USER_AGENT)
    data_url = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")
    write_set_mechanics(
        options.directory, datetime.now(timezone.utc), bulk_cards(_bulk_download_uri(DEFAULT_CARDS_URL)),
        lambda url: fetch(url, agent), lambda: load_rules(options.directory, lambda url: fetch(url, agent), f"{data_url}/{RULES_PATH}"),
    )
    return 0
