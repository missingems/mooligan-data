"""edh/commanders/{slug}/guide.json: Claude's own read of a commander's play styles and power brackets.

`python -m mtgmeta guides DIR --top 5` takes the first commanders of `edh/top.json`, gives Claude each one's oracle
text and the card pool of its `edh/commanders/{slug}.json`, and writes what it returns, with every card checked
against Scryfall's catalog. A guide is asked for again only when what Claude would be sent changes (the pool, the
oracle text, the rules or the model), which `state/guides.json` remembers. See docs/data-format.md.

It reads ANTHROPIC_API_KEY from the environment, and `--dry-run` shows what would be asked, and its estimated
cost, without one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cards import slug as card_slug
from .scryfall import HEADERS as SCRYFALL_HEADERS
from .top import top_slugs

log = logging.getLogger(__name__)

SCHEMA = 1
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MAX_TOKENS = 32000
# Refusals go to the model the API picks for their category, inside the same call.
BETAS = ["server-side-fallback-2026-07-01"]
TOOL_NAME = "write_guide"
STATE_PATH = "state/guides.json"
GAME_CHANGERS = Path(__file__).with_name("game_changers.json")
SCRYFALL_API = "https://api.scryfall.com"
SCRYFALL_DELAY = 0.1

ROLES = ("land", "ramp", "draw", "removal", "counter", "wipe", "protection", "tutor", "payoff", "engine", "combo", "utility")
BRACKETS = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}
MIN_STYLES, MAX_STYLES = 3, 6
MIN_STYLE_CARDS, MAX_STYLE_CARDS = 30, 60
MAX_BRACKET_CARDS = 30
BRACKET_3_GAME_CHANGERS = 3

# Sonnet 5.5, per million tokens; a 5-minute cache write is 1.25 times input.
PRICE_INPUT, PRICE_OUTPUT, PRICE_CACHE_WRITE, PRICE_CACHE_READ = 2.00, 10.00, 2.50, 0.20

_CARD = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "role"],
    "properties": {
        "name": {"type": "string", "description": "The card's exact English name, as Scryfall prints it."},
        "role": {"type": "string", "enum": list(ROLES)},
    },
}
_LEVEL = {"type": "integer", "enum": list(BRACKETS)}

TOOL = {
    "name": TOOL_NAME,
    "description": "Records the commander's guide: its play styles and what each of the five power brackets looks like for it.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["styles", "brackets"],
        "properties": {
            "styles": {
                "type": "array",
                "description": "3 to 6 distinct ways to build the deck, most played first.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "summary", "brackets", "cards"],
                    "properties": {
                        "name": {"type": "string", "description": "A short name, such as Infect or Spellslinger."},
                        "summary": {"type": "string", "description": "Two or three sentences: the plan and how it wins."},
                        "brackets": {"type": "array", "description": "Every bracket this style plays well at.", "items": _LEVEL},
                        "cards": {"type": "array", "description": "40 to 60 cards that make the style.", "items": _CARD},
                    },
                },
            },
            "brackets": {
                "type": "array",
                "description": "All five brackets, 1 to 5, once each.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["level", "summary", "cards"],
                    "properties": {
                        "level": _LEVEL,
                        "summary": {"type": "string", "description": "Two or three sentences: what the deck looks like at this bracket."},
                        "cards": {"type": "array", "description": "12 to 25 cards that set this bracket apart.", "items": _CARD},
                    },
                },
            },
        },
    },
}

_RULES = """You are an expert Magic: The Gathering Commander deck builder. You judge play styles and power brackets yourself, from the commander's oracle text and the card pool its players use; EDHREC's own theme and bracket pages are not your source.

You are given one commander: its oracle text and colour identity, then the cards EDHREC's decks for it play, by section, each with the share of the commander's decks that play it ("~60%"). A "*" marks a card in EDHREC's average deck for it.

Call the write_guide tool once with the whole guide, and write nothing else.

## Play styles

Give 3 to 6 genuinely different ways to build around this commander, most played first: different win conditions or engines, not the same deck at another budget. For each:
- name: short, such as "Infect", "Spellslinger", "Aristocrats".
- summary: two or three sentences on the plan and how it wins.
- brackets: every bracket the style plays well at, such as [2, 3, 4].
- cards: 40 to 60 cards that make the style, the most important first. Draw them from the pool, or from well-known staples legal in Commander and in the commander's colour identity. Never list the commander itself, cards outside its colour identity, or cards banned in Commander.

## Power brackets

Describe all five brackets for this commander, once each, levels 1 to 5. For each, a summary of two or three sentences on what the deck looks like at that bracket, and 12 to 25 cards that set the bracket apart for this commander: at 1 and 2 the on-theme core that keeps it casual, at 3 the upgrades (with at most three Game Changers), at 4 and 5 the high-power additions. The cards of a bracket must keep its rules.

Wizards of the Coast's Commander Brackets:
1. Exhibition. Theme and flavour first, power well below a preconstructed deck; expect games of nine turns or more. No Game Changers. No mass land denial. No extra-turn cards. No two-card combos that win the game or make an infinite loop.
2. Core. About the power of a current preconstructed deck; expect games of eight turns or more. No Game Changers. No mass land denial. Extra turns only a few, never chained or looped. No two-card combos.
3. Upgraded. Stronger than a precon, with tuned synergy and better interaction; expect games of six turns or more. Up to three Game Changers. No mass land denial. Extra turns only a few, never chained or looped. No two-card combos that can win early in the game; late-game combos are fine.
4. Optimized. High power, with nothing restricted but the banned list: any number of Game Changers, fast mana, mass land denial, chained extra turns and compact combos; games can end from turn four.
5. cEDH. Built to win as fast and as reliably as possible for the competitive metagame, with the same card rules as bracket 4.

Tutors: since October 2025 the brackets set no separate limit on tutors. The most efficient ones are Game Changers and count as such; at brackets 1 and 2 keep tutors few, fetching theme pieces rather than combo pieces.

Mass land denial means cards that destroy, exile or bounce several lands, or stop lands untapping, such as Armageddon, Ruination, Winter Orb or Blood Moon. Extra-turn cards are cards such as Time Warp or Nexus of Fate.

Game Changers (each counts against bracket 3's three, and none is allowed at brackets 1 or 2):
{game_changers}

## Roles

Give every card one role, the job it does in this deck:
- land: a land.
- ramp: makes or fixes mana beyond the land drop.
- draw: draws cards or gives card advantage.
- removal: removes a single permanent or creature.
- counter: counters spells.
- wipe: removes many permanents at once.
- protection: protects the commander or the board.
- tutor: searches the library for a card.
- payoff: what the deck wins with or builds towards.
- engine: repeats value with the commander's plan.
- combo: a piece of a combo that wins the game.
- utility: anything else.
"""


def load_game_changers(path: Path = GAME_CHANGERS) -> List[dict]:
    return json.loads(path.read_text())["cards"]


def system_prompt(game_changers: Sequence[dict]) -> str:
    return _RULES.replace("{game_changers}", "\n".join(f"- {card['name']}" for card in game_changers))


def fingerprint(system: str) -> str:
    """What every guide was asked with: the model, its effort, the rules and the tool. A change asks for every guide again."""
    body = json.dumps({"model": MODEL, "effort": EFFORT, "system": system, "tool": TOOL}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def commander_message(page: dict, oracle_text: str) -> str:
    """The user turn for one commander: its oracle text, then its card pool, each card once, in its first section."""
    identity = page.get("color_identity")
    lines = [
        f"Commander: {page['name']}",
        f"Colour identity: {' '.join(identity) if identity else 'colourless'}" if identity is not None else "Colour identity: unknown",
        "",
        "Oracle text:",
        oracle_text.strip() or "(not available)",
        "",
        f"Card pool from {page.get('decks', 0)} EDHREC decks:",
    ]
    average = {name for section in page.get("average_deck", []) for name in section.get("cards", [])}
    seen = {page["name"]}
    for section in page.get("sections", []):
        rows = []
        for card in section.get("cards", []):
            if card["name"] in seen:
                continue
            seen.add(card["name"])
            share = round(card["decks"] * 10 / card["of_decks"]) * 10 if card.get("of_decks") else 0
            rows.append(f"{card['name']} (~{share}%){' *' if card['name'] in average else ''}")
        if rows:
            lines += ["", f"## {section.get('header') or section.get('tag')}", *rows]
    rest = sorted(average - seen)
    if rest:
        lines += ["", "## Also in the average deck", ", ".join(rest)]
    return "\n".join(lines) + "\n"


def request(system: str, message: str) -> dict:
    """The Messages API call: the tool and rules form the cached prefix, the commander is the turn after it."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "betas": BETAS,
        "fallbacks": "default",
        "output_config": {"effort": EFFORT},
        "tools": [TOOL],
        "tool_choice": {"type": "auto"},
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": message}],
    }


def input_hash(fingerprint_: str, message: str) -> str:
    return hashlib.sha256(f"{fingerprint_}\n{message}".encode()).hexdigest()[:16]


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, usage) -> None:
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    def dollars(self) -> float:
        return (
            self.input * PRICE_INPUT + self.output * PRICE_OUTPUT + self.cache_write * PRICE_CACHE_WRITE + self.cache_read * PRICE_CACHE_READ
        ) / 1_000_000


class GuideError(Exception):
    def __init__(self, message: str, usage=None) -> None:
        super().__init__(message)
        self.usage = usage


def ask(client, call: dict):
    """Claude's guide for one call, as the tool's input, and the message it came in."""
    with client.beta.messages.stream(**call) as stream:
        message = stream.get_final_message()
    if message.stop_reason in ("refusal", "max_tokens"):
        raise GuideError(f"stopped: {message.stop_reason}", message.usage)
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return block.input, message
    raise GuideError(f"no {TOOL_NAME} call (stop reason {message.stop_reason})", message.usage)


@dataclass
class Checker:
    """Resolves Claude's card names against the catalog and keeps what the commander may play."""

    catalog: Dict[str, dict]
    identity: Optional[Set[str]]
    commander: Set[str]
    banned: Set[str]
    game_changers: Set[str]
    dropped: List[str] = field(default_factory=list)

    def cards(self, cards: Iterable[dict], limit: int, game_changers: Optional[int] = None) -> List[dict]:
        kept, ids, changers = [], set(), 0
        for card in cards:
            name = str(card.get("name", "")).strip()
            entry = self.catalog.get(card_slug(name)) if name else None
            if not entry or not entry.get("oracle_id"):
                self.dropped.append(f"{name}: not in the catalog")
                continue
            oracle_id = entry["oracle_id"]
            if oracle_id in ids or oracle_id in self.commander:
                continue
            if oracle_id in self.banned:
                self.dropped.append(f"{name}: banned in Commander")
                continue
            colours = entry.get("color_identity")
            if self.identity is not None and colours is not None and not set(colours) <= self.identity:
                self.dropped.append(f"{name}: outside the colour identity")
                continue
            if oracle_id in self.game_changers and game_changers is not None:
                if changers >= game_changers:
                    self.dropped.append(f"{name}: a Game Changer over the bracket's limit")
                    continue
                changers += 1
            role = card.get("role") if card.get("role") in ROLES else "utility"
            ids.add(oracle_id)
            kept.append({"name": entry["name"], "oracle_id": oracle_id, "role": role})
            if len(kept) == limit:
                break
        return kept


def build_guide(slug: str, name: str, answer: dict, checker: Checker, model: str, now: datetime) -> Tuple[dict, List[str]]:
    """The guide.json document from Claude's answer, and the warnings it raised; GuideError when it breaks the contract."""
    warnings: List[str] = []
    styles, ids = [], set()
    for style in answer.get("styles") or []:
        style_name = str(style.get("name", "")).strip()
        style_id = card_slug(style_name)
        levels = sorted({level for level in style.get("brackets") or [] if level in BRACKETS})
        if not style_id or style_id in ids or not levels:
            warnings.append(f"style {style_name!r} dropped: no name, a repeated name or no bracket")
            continue
        cards = checker.cards(style.get("cards") or [], MAX_STYLE_CARDS)
        if len(cards) < MIN_STYLE_CARDS:
            warnings.append(f"style {style_id}: {len(cards)} cards after checking, under {MIN_STYLE_CARDS}")
        ids.add(style_id)
        styles.append({"id": style_id, "name": style_name, "summary": str(style.get("summary", "")).strip(), "brackets": levels, "cards": cards})
    if len(styles) < MIN_STYLES:
        raise GuideError(f"{len(styles)} play styles, under {MIN_STYLES}")
    if len(styles) > MAX_STYLES:
        warnings.append(f"{len(styles)} play styles, the first {MAX_STYLES} kept")
        styles = styles[:MAX_STYLES]

    by_level: Dict[int, dict] = {}
    for bracket in answer.get("brackets") or []:
        if bracket.get("level") in BRACKETS:
            by_level.setdefault(bracket["level"], bracket)
    missing = [level for level in BRACKETS if level not in by_level]
    if missing:
        raise GuideError(f"brackets {missing} missing")
    limits = {1: 0, 2: 0, 3: BRACKET_3_GAME_CHANGERS}
    brackets = [
        {
            "level": level,
            "name": BRACKETS[level],
            "summary": str(by_level[level].get("summary", "")).strip(),
            "cards": checker.cards(by_level[level].get("cards") or [], MAX_BRACKET_CARDS, limits.get(level)),
        }
        for level in BRACKETS
    ]
    guide = {
        "schema": SCHEMA,
        "slug": slug,
        "name": name,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "styles": styles,
        "brackets": brackets,
    }
    return guide, warnings


def http_json(url: str, headers: Optional[dict] = None) -> Optional[dict]:
    """The JSON at `url`, or None when it is not there."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": SCRYFALL_HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return None
        raise


def scryfall_json(url: str) -> Optional[dict]:
    time.sleep(SCRYFALL_DELAY)
    return http_json(url, SCRYFALL_HEADERS)


def _card_text(card: dict) -> str:
    faces = card.get("card_faces") or [card]
    parts = []
    for face in faces:
        head = " - ".join(part for part in (face.get("name"), face.get("mana_cost"), face.get("type_line")) if part)
        parts.append(f"{head}\n{face.get('oracle_text', '')}".strip())
    return "\n\n".join(parts)


def oracle_text(page: dict, fetch: Callable[[str], Optional[dict]] = scryfall_json) -> str:
    """The commander's oracle text from Scryfall, by EDHREC's printing id, else by name; both halves of a partner pair."""
    if page.get("scryfall_id"):
        cards = [fetch(f"{SCRYFALL_API}/cards/{page['scryfall_id']}")]
    else:
        names = [half.strip() for half in page["name"].split("//")] if "//" in page["name"] else [page["name"]]
        cards = [fetch(f"{SCRYFALL_API}/cards/named?exact={urllib.parse.quote(name)}") for name in names]
    return "\n\n".join(_card_text(card) for card in cards if card)


def banned_oracle_ids(fetch: Callable[[str], Optional[dict]] = scryfall_json) -> Set[str]:
    """The oracle ids of every card banned in Commander, from Scryfall's search."""
    url: Optional[str] = f"{SCRYFALL_API}/cards/search?q={urllib.parse.quote('banned:commander')}&unique=cards"
    ids: Set[str] = set()
    while url:
        body = fetch(url)
        if not body:
            raise GuideError("Scryfall's banned list could not be read")
        ids.update(card["oracle_id"] for card in body.get("data", []) if card.get("oracle_id"))
        url = body.get("next_page") if body.get("has_more") else None
    return ids


def commander_identity(page: dict, catalog: Dict[str, dict]) -> Optional[Set[str]]:
    if page.get("color_identity") is not None:
        return set(page["color_identity"])
    halves = [catalog.get(card_slug(half)) for half in page["name"].split("//")]
    if all(half and "color_identity" in half for half in halves):
        return {letter for half in halves for letter in half["color_identity"]}
    return None


def commander_ids(page: dict, catalog: Dict[str, dict]) -> Set[str]:
    names = [page["name"], *page["name"].split("//")]
    return {entry["oracle_id"] for entry in (catalog.get(card_slug(name)) for name in names) if entry and entry.get("oracle_id")}


class Source:
    """Reads a published file from DIR, or from the live site when DIR does not have it."""

    def __init__(self, directory: Path, data_url: str, fetch: Callable[[str], Optional[dict]] = http_json) -> None:
        self._directory = directory
        self._data_url = data_url.rstrip("/")
        self._fetch = fetch

    def read(self, path: str) -> Optional[dict]:
        local = self._directory / path
        if local.exists():
            return json.loads(local.read_text())
        return self._fetch(f"{self._data_url}/{path}")


@dataclass
class Result:
    written: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    planned: List[Tuple[str, int]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def commander_slugs(top: Optional[dict], count: int) -> List[str]:
    windows = {window: body.get("commanders", []) for window, body in ((top or {}).get("windows") or {}).items()}
    return top_slugs(windows)[:count]


def run(
    directory: Path,
    slugs: Sequence[str],
    source: Source,
    *,
    client=None,
    catalog: Optional[Dict[str, dict]] = None,
    banned: Optional[Set[str]] = None,
    fetch_oracle: Callable[[dict], str] = oracle_text,
    force: bool = False,
    dry_run: bool = False,
    now: Optional[Callable[[], datetime]] = None,
) -> Result:
    """Asks for the guide of each commander whose input changed, writing each one and the state as it goes."""
    clock = now or (lambda: datetime.now(timezone.utc))
    game_changers = load_game_changers()
    system = system_prompt(game_changers)
    prefix = fingerprint(system)
    state_path = directory / STATE_PATH
    state: Dict[str, dict] = json.loads(state_path.read_text()) if state_path.exists() else {}
    changer_ids = {card["oracle_id"] for card in game_changers}
    result = Result()
    for slug in slugs:
        try:
            page = source.read(f"edh/commanders/{slug}.json")
            if not page or not page.get("name"):
                raise GuideError("no commander page")
            message = commander_message(page, fetch_oracle(page))
        except Exception as error:  # noqa: BLE001 - one commander must not stop the others
            log.error("Guide %s failed: %s", slug, error)
            result.failed.append(slug)
            continue
        digest = input_hash(prefix, message)
        target = directory / "edh" / "commanders" / slug / "guide.json"
        if not force and state.get(slug, {}).get("hash") == digest:
            result.unchanged.append(slug)
            continue
        if dry_run:
            result.planned.append((slug, estimate_tokens(system + json.dumps(TOOL) + message)))
            continue
        checker = Checker(catalog or {}, commander_identity(page, catalog or {}), commander_ids(page, catalog or {}), banned or set(), changer_ids)
        try:
            answer, response = ask(client, request(system, message))
            result.usage.add(response.usage)
            guide, warnings = build_guide(slug, page["name"], answer, checker, response.model, clock())
        except Exception as error:  # noqa: BLE001 - an API error or a broken answer fails this commander only
            result.usage.add(getattr(error, "usage", None))
            log.error("Guide %s failed: %s: %s", slug, type(error).__name__, error)
            result.failed.append(slug)
            continue
        for warning in warnings:
            log.warning("Guide %s: %s", slug, warning)
        if checker.dropped:
            log.info("Guide %s: dropped %d cards: %s", slug, len(checker.dropped), "; ".join(checker.dropped))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(guide, ensure_ascii=False, separators=(",", ":")))
        state[slug] = {"hash": digest, "generated_at": guide["generated_at"], "model": guide["model"]}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, sort_keys=True, indent=1))
        result.written.append(f"edh/commanders/{slug}/guide.json")
        log.info("Guide %s: %d styles", slug, len(guide["styles"]))
    return result


def estimate_tokens(text: str) -> int:
    """A rough count, about four characters a token, for the dry run; the API's count_tokens is exact but is a call."""
    return len(text) // 4


def _client():
    """The Anthropic client, with the key from ANTHROPIC_API_KEY; None when it is not set."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    return anthropic.Anthropic(api_key=key)


def main(
    argv: Sequence[str], make_client: Callable[[], object] = _client, load_catalog=None, fetch_banned=banned_oracle_ids, fetch_oracle=oracle_text
) -> int:
    parser = argparse.ArgumentParser(prog="python -m mtgmeta guides", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="data directory, mirroring the R2 bucket; missing pages are read from DATA_URL")
    parser.add_argument("--top", type=int, default=5, help="the first N commanders of edh/top.json, the week's first (default 5)")
    parser.add_argument("--slug", action="append", default=[], help="a commander's slug, in place of --top; repeatable")
    parser.add_argument("--force", action="store_true", help="ask again even when the input has not changed")
    parser.add_argument("--dry-run", action="store_true", help="list what would be asked and its estimated cost; calls nothing")
    args = parser.parse_args(list(argv))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("anthropic", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    source = Source(args.directory, os.environ.get("DATA_URL", "https://data.mooligan.com"))
    slugs = args.slug or commander_slugs(source.read("edh/top.json"), args.top)
    if not slugs:
        log.error("No commanders: edh/top.json could not be read")
        return 1
    client = None
    if not args.dry_run:
        client = make_client()
        if client is None:
            log.error("ANTHROPIC_API_KEY is not set")
            return 2
    if args.dry_run:
        catalog, banned = {}, set()
    else:
        if load_catalog is None:
            from .scryfall import card_catalog as load_catalog
        catalog, banned = load_catalog(), fetch_banned()
    result = run(
        args.directory, slugs, source, client=client, catalog=catalog, banned=banned, fetch_oracle=fetch_oracle, force=args.force, dry_run=args.dry_run
    )

    if args.dry_run:
        for slug, tokens in result.planned:
            print(f"would ask: {slug} (~{tokens} input tokens)")
        print(f"{len(result.planned)} to ask, {len(result.unchanged)} unchanged")
    else:
        usage = result.usage
        print(
            f"{len(result.written)} written, {len(result.unchanged)} unchanged, {len(result.failed)} failed; "
            f"tokens: {usage.input} input, {usage.cache_write} cache write, {usage.cache_read} cache read, {usage.output} output; "
            f"about ${usage.dollars():.2f}"
        )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
