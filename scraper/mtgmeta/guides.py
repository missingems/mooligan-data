"""edh/commanders/{slug}/guide.json: a commander's play styles and power brackets, built from data with no model.

Each play style is one of EDHREC's themes for the commander, with its own cards and deck counts. Each style gets a
whole deck for every bracket it is played at, filled by the Mooligan app's builder rules (guide_builder.py) from
EDHREC's inclusion rates under that bracket's rules (guide_brackets.py), and the Commander Spellbook combos that deck
holds. Prices are Scryfall's, from the card catalog. The summaries are templates over those numbers (guide_text.py);
`--polish` has Claude rewrite them as prose through one Message Batch a run (guide_polish.py), and is the only part
that needs ANTHROPIC_API_KEY. A guide rebuilt with the same facts keeps its last polish rather than being sent again.

The daily scrape runs it for the commanders of `edh/top.json` (the first 100 of its windows and every one its brackets
rank), a few dozen a run. `state/guides.json` remembers what each guide was built from, so a commander is read again
only when its themes change, its decks move by a tenth, or its guide is a week old. `python -m mtgmeta guides DIR --top 5`
runs it by hand. See docs/data-format.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from . import guide_text
from .guide_polish import Batch, BatchPolisher, apply as apply_polish, carry_over, polish_hash
from .cards import slug as card_slug
from .edhrec import COMMANDER_URL, _commander_entry as commander_entry
from .guide_brackets import NAMES, Pool, Rules, counts, deck_bracket, find_pool, post_json
from .guide_builder import BASICS, Candidate, Deck, fill, role
from .guide_edhrec import Page, SubPages, published_page, read_sub_pages
from .scryfall import HEADERS as SCRYFALL_HEADERS
from .top import top_slugs
from .top_brackets import bracket_slugs

log = logging.getLogger(__name__)

SCHEMA = 1
# Bumped whenever a change to the build would change a guide, so every guide is built again.
GENERATOR = "data-2"
STATE_PATH = "state/guides.json"
POLISH_BATCH_PATH = "state/polish-batch.json"
GAME_CHANGERS = Path(__file__).with_name("game_changers.json")
EDHREC_USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"

MAX_STYLES = 5
# A theme or bracket page needs this many decks before its inclusion rates are used.
MIN_SAMPLE = 30
# A style is played at a bracket when this share of its decks are built for it.
MIN_BRACKET_SHARE = 0.10
MAX_STYLE_CARDS = 60
MAX_BRACKET_CARDS = 30
SIGNATURE_CARDS = 3
REFRESH_DAYS = 7
# Spellbook reads at most 600 cards besides the commanders.
MAX_POOL = 600
DECKS_MOVED = 0.10


def load_game_changers(path: Path = GAME_CHANGERS) -> List[dict]:
    return json.loads(path.read_text())["cards"]


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


def edhrec_json(url: str) -> Optional[dict]:
    """An EDHREC page, None when it has none or cannot be read now."""
    try:
        return http_json(url, {"User-Agent": EDHREC_USER_AGENT})
    except (urllib.error.URLError, OSError, ValueError) as error:
        log.warning("EDHREC %s: %s", url, error)
        return None


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


def commander_slugs(top: Optional[dict], count: int, brackets: bool = False) -> List[str]:
    """The first `count` commanders of top.json's windows, and with `brackets` every one its brackets rank after them."""
    windows = {window: body.get("commanders", []) for window, body in ((top or {}).get("windows") or {}).items()}
    first = top_slugs(windows)[:count]
    return list(dict.fromkeys(first + bracket_slugs(top))) if brackets else first


def commander_names(name: str) -> List[str]:
    return [half.strip() for half in name.split("//")] if "//" in name else [name]


def commander_identity(page: dict, catalog: Dict[str, dict]) -> Optional[Set[str]]:
    if page.get("color_identity") is not None:
        return set(page["color_identity"])
    halves = [catalog.get(card_slug(half)) for half in page["name"].split("//")]
    if all(half and "color_identity" in half for half in halves):
        return {letter for half in halves for letter in half["color_identity"]}
    return None


def themes(page: dict) -> List[dict]:
    """The themes that become play styles: EDHREC's with enough decks, most decks first."""
    return [theme for theme in page.get("themes") or [] if theme.get("decks", 0) >= MIN_SAMPLE][:MAX_STYLES]


def fingerprint(page: dict, game_changers: Sequence[dict]) -> str:
    """What makes a guide due before its week is out: the generator, the commander's themes and the Game Changers."""
    body = json.dumps({
        "generator": GENERATOR,
        "themes": [theme["slug"] for theme in themes(page)],
        "game_changers": sorted(card["oracle_id"] for card in game_changers),
    }, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def is_due(entry: Optional[dict], page: dict, digest: str, now: datetime) -> bool:
    if not entry or entry.get("generator") != GENERATOR or entry.get("fingerprint") != digest:
        return True
    try:
        built = datetime.strptime(entry["built_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return True
    if now - built >= timedelta(days=REFRESH_DAYS):
        return True
    before, decks = entry.get("decks") or 0, page.get("decks") or 0
    return not before or abs(decks - before) / before >= DECKS_MOVED


@dataclass
class Resolver:
    """Turns EDHREC's names into the catalog's cards the commander may play, each with its role."""

    catalog: Dict[str, dict]
    identity: Optional[Set[str]]
    commanders: Set[str]
    banned: Set[str] = field(default_factory=set)
    _cache: Dict[str, Optional[dict]] = field(default_factory=dict)

    def ban(self, names: Set[str]) -> None:
        self.banned = set(names)
        self._cache.clear()

    def card(self, name: str) -> Optional[dict]:
        if name not in self._cache:
            self._cache[name] = self._resolve(name)
        return self._cache[name]

    def _resolve(self, name: str) -> Optional[dict]:
        entry = self.catalog.get(card_slug(name))
        if not entry or not entry.get("oracle_id") or entry["name"] in self.commanders or name in self.commanders:
            return None
        if entry["name"] in self.banned or name in self.banned:
            return None
        if (entry.get("type_line") or "").startswith("Basic"):
            return None
        colours = entry.get("color_identity")
        if self.identity is not None and colours is not None and not set(colours) <= self.identity:
            return None
        return {**entry, "role": role(entry)}


def candidates(scores: Dict[str, Tuple[float, float]], resolver: Resolver) -> List[Candidate]:
    kept: Dict[str, Candidate] = {}
    for name, (score, synergy) in scores.items():
        entry = resolver.card(name)
        if entry is None or entry["name"] in kept:
            continue
        kept[entry["name"]] = Candidate(
            name=entry["name"],
            oracle_id=entry["oracle_id"],
            role=entry["role"],
            score=score,
            synergy=synergy,
            mana_value=entry.get("mana_value") or 0.0,
            mana_cost=entry.get("mana_cost") or "",
            price=entry.get("price"),
        )
    return list(kept.values())


def usable(page: Optional[Page]) -> Optional[Page]:
    return page if page is not None and page.decks >= MIN_SAMPLE else None


def nearest_bracket(sub: SubPages, level: int) -> Optional[Page]:
    """The bracket's own page when it has enough decks, else the nearest level's that has, the higher on a tie."""
    for other in sorted(sub.brackets, key=lambda each: (abs(each - level), -each)):
        page = usable(sub.brackets.get(other))
        if page is not None:
            return page
    return None


def scores(base: Page, theme: Page, bracket: Optional[Page]) -> Dict[str, Tuple[float, float]]:
    """Each card's inclusion in the theme's decks, moved by how much more or less the bracket's decks play it."""
    names = list(dict.fromkeys([*theme.cards, *(bracket.cards if bracket else {})]))
    result: Dict[str, Tuple[float, float]] = {}
    for name in names:
        overall = base.cards[name].inclusion if name in base.cards else 0.0
        themed = theme.cards[name].inclusion if name in theme.cards else overall
        lift = (bracket.cards[name].inclusion - overall) if bracket and name in bracket.cards else 0.0
        synergy = theme.cards[name].synergy if name in theme.cards else bracket.cards[name].synergy
        result[name] = (max(0.0, themed + lift), synergy)
    return result


def bracket_split(theme: Page, base: Page) -> Dict[int, int]:
    """How the theme's decks split by bracket, or the commander's when too few of the theme's say."""
    return theme.bracket_decks if sum(theme.bracket_decks.values()) >= MIN_SAMPLE else base.bracket_decks


def style_levels(split: Dict[int, int]) -> List[int]:
    """The brackets a style is played at: from the lowest to the highest that holds a tenth of its decks."""
    total = sum(split.values())
    levels = [level for level in NAMES if total and split.get(level, 0) / total >= MIN_BRACKET_SHARE]
    return list(range(min(levels), max(levels) + 1)) if levels else [2, 3]


def most_played(split: Dict[int, int], levels: Sequence[int]) -> Optional[int]:
    played = [level for level in levels if split.get(level)]
    return max(played, key=lambda level: (split[level], -level)) if played else None


def card_json(card: Candidate, role_: Optional[str] = None) -> dict:
    return {"name": card.name, "oracle_id": card.oracle_id, "role": role_ or card.role}


def deck_combos(names: Set[str], pool: Pool, commanders: Set[str]) -> List[dict]:
    have = names | commanders
    return [combo for combo in pool.combos if {card["name"] for card in combo["cards"]} <= have]


def deck_json(level: int, deck: Deck, pool: Pool, commanders: Set[str], basic_prices: Dict[str, float]) -> dict:
    """One style's whole deck at one bracket; a spell that is a piece of one of its combos has the `combo` role."""
    names = {card.name for card in deck.cards}
    combos = deck_combos(names, pool, commanders)
    pieces = {card["name"] for combo in combos for card in combo["cards"]}
    price = sum(card.price or 0.0 for card in deck.cards) + sum(basic_prices.get(color, 0.0) * count for color, count in deck.basics.items())
    return {
        "level": level,
        "name": NAMES[level],
        "cards": [card_json(card, "combo" if card.name in pieces and not card.is_land else None) for card in deck.cards],
        "basics": [{"name": BASICS[color], "count": count} for color, count in deck.basics.items()],
        "lands": sum(1 for card in deck.cards if card.is_land) + sum(deck.basics.values()),
        "price": round(price, 2),
        "bracket": deck_bracket(names, pool, commanders),
        **counts(names, pool),
        "combos": [combo["id"] for combo in combos],
    }


def build_deck(level: int, base: Page, theme: Page, sub: SubPages, resolver: Resolver, pool: Pool, commanders: Set[str], identity: Sequence[str]) -> Deck:
    rules = Rules(level, pool, commanders)
    return fill(
        candidates(scores(base, theme, nearest_bracket(sub, level)), resolver),
        slots=100 - len(commanders),
        identity=identity,
        nonbasic_lands=(theme.lands - theme.basics) if theme.lands is not None and theme.basics is not None else None,
        allows=rules.allows,
        on_add=rules.add,
    )


def lifted(base: Page, page: Page, resolver: Resolver) -> List[Candidate]:
    """The cards `page`'s decks play more than the commander's decks overall, most lifted first."""
    lifts = {}
    for name, card in page.cards.items():
        overall = base.cards[name].inclusion if name in base.cards else 0.0
        if card.inclusion - overall > 0:
            lifts[name] = (card.inclusion - overall, card.synergy)
    return sorted(candidates(lifts, resolver), key=lambda card: (-card.score, card.name))


def signature(base: Page, theme: Page, resolver: Resolver, count: int = SIGNATURE_CARDS) -> List[str]:
    """The spells the theme's decks play most above the commander's other decks: in a fifth of them, 5 points up."""
    return [
        card.name for card in lifted(base, theme, resolver)
        if card.role != "land" and card.score >= 0.05 and theme.cards.get(card.name) and theme.cards[card.name].inclusion >= 0.2
    ][:count] if theme is not base else []


def bracket_cards(level: int, base: Page, sub: SubPages, resolver: Resolver, pool: Pool, commanders: Set[str]) -> List[Candidate]:
    """What sets the bracket apart: the cards its decks play more than the commander's decks overall, within its rules."""
    page = nearest_bracket(sub, level)
    if page is None:
        return []
    rules = Rules(level, pool, commanders)
    kept: List[Candidate] = []
    names: Set[str] = set()
    for card in lifted(base, page, resolver):
        if not rules.allows(card.name, names):
            continue
        rules.add(card.name)
        names.add(card.name)
        kept.append(card)
        if len(kept) == MAX_BRACKET_CARDS:
            break
    return kept


def pool_names(base: Page, sub: SubPages, resolver: Resolver, limit: int = MAX_POOL) -> List[str]:
    """Every card the commander's pages name that it may play, the `limit` with the best inclusion on any page."""
    pages = [base, *(page for page in sub.themes.values() if page), *(page for page in sub.brackets.values() if page)]
    best: Dict[str, float] = {}
    for page in pages:
        for name, card in page.cards.items():
            entry = resolver.card(name)
            if entry:
                best[entry["name"]] = max(best.get(entry["name"], 0.0), card.inclusion)
    return sorted(sorted(best, key=lambda name: (-best[name], name))[:limit])


def basic_prices(catalog: Dict[str, dict]) -> Dict[str, float]:
    return {color: (catalog.get(card_slug(name)) or {}).get("price") or 0.0 for color, name in BASICS.items()}


def build_guide(page: dict, sub: SubPages, catalog: Dict[str, dict], pool: Pool, resolver: Resolver, now: datetime) -> dict:
    """The guide.json document for one commander, from its published page, its sub-pages and Spellbook's reading."""
    base = published_page(page)
    commanders = set(commander_names(page["name"]))
    identity = sorted(resolver.identity or set())
    prices = basic_prices(catalog)
    chosen = [(theme, themed) for theme in themes(page) if (themed := usable(sub.themes.get(theme["slug"]))) is not None]
    if not chosen:
        chosen = [({"slug": "", "name": "Average Deck", "decks": base.decks}, base)]
    styles, used = [], set()
    for theme, themed in chosen:
        split = bracket_split(themed, base)
        levels = style_levels(split)
        decks = [deck_json(level, build_deck(level, base, themed, sub, resolver, pool, commanders, identity), pool, commanders, prices) for level in levels]
        order = {card.name: index for index, card in enumerate(sorted(candidates(scores(base, themed, None), resolver), key=lambda card: (-card.score, -card.synergy, card.name)))}
        style_cards = sorted((card for card in decks[0]["cards"] if card["role"] != "land"), key=lambda card: order.get(card["name"], len(order)))
        combo_ids = {each for deck in decks for each in deck["combos"]}
        combos = [combo for combo in pool.combos if combo["id"] in combo_ids]
        used |= combo_ids
        styles.append({
            "id": theme["slug"] or card_slug(theme["name"]),
            "name": theme["name"],
            "summary": guide_text.style_summary(
                page["name"], theme["name"], theme["decks"], base.decks, levels, most_played(split, levels),
                signature(base, themed, resolver), combos[0] if combos else None,
            ),
            "brackets": levels,
            "decks": theme["decks"],
            "url": f"https://edhrec.com/commanders/{page['slug']}/{theme['slug']}" if theme["slug"] else page.get("url"),
            "cards": style_cards[:MAX_STYLE_CARDS],
            "lists": decks,
        })
    brackets = []
    for level, name in NAMES.items():
        cards = bracket_cards(level, base, sub, resolver, pool, commanders)
        own = sub.brackets.get(level)
        decks = base.bracket_decks.get(level) or (own.decks if own else 0)
        brackets.append({
            "level": level,
            "name": name,
            "summary": guide_text.bracket_summary(page["name"], level, decks, [card.name for card in cards[:3]]),
            "decks": decks,
            "cards": [card_json(card) for card in cards],
        })
    return {
        "schema": SCHEMA,
        "slug": page["slug"],
        "name": page["name"],
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": GENERATOR,
        "model": None,
        "decks": base.decks,
        "url": page.get("url"),
        "styles": styles,
        "brackets": brackets,
        "combos": [combo for combo in pool.combos if combo["id"] in used],
    }


def build_one(page: dict, catalog: Dict[str, dict], changer_ids: Set[str], fetch_edhrec, post_spellbook, delay: float, now: datetime) -> Optional[dict]:
    """One commander's guide; None when Spellbook cannot be read, as its brackets would be guesses."""
    commanders = commander_names(page["name"])
    resolver = Resolver(catalog, commander_identity(page, catalog), set(commanders))
    sub = read_sub_pages(page["slug"], [theme["slug"] for theme in themes(page)], fetch_edhrec, delay)
    names = pool_names(published_page(page), sub, resolver)
    pool = find_pool(commanders, names, post_spellbook)
    if pool is None:
        return None
    ours = {name for name in names if resolver.card(name)["oracle_id"] in changer_ids}
    theirs = pool.game_changers & set(names)
    if ours != theirs:
        log.info("Guide %s: Game Changers differ from Spellbook's: only ours %s, only Spellbook's %s", page["slug"], sorted(ours - theirs), sorted(theirs - ours))
    pool.game_changers = ours
    resolver.ban(pool.banned)
    return build_guide(page, sub, catalog, pool, resolver, now)


def fresh_page(slug: str, page: dict, fetch_edhrec: Callable[[str], Optional[dict]]) -> dict:
    """A page published before it carried EDHREC's themes, read again from EDHREC; as it was when EDHREC has none."""
    body = fetch_edhrec(f"{COMMANDER_URL}/{slug}.json")
    entry = commander_entry(body, None, slug) if body else None
    return {**page, **entry, "oracle_ids": page.get("oracle_ids", {})} if entry else page


@dataclass
class Result:
    written: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)
    polished: List[str] = field(default_factory=list)
    carried: List[str] = field(default_factory=list)


def guide_path(slug: str) -> str:
    return f"edh/commanders/{slug}/guide.json"


def write_guide(directory: Path, guide: dict) -> str:
    path = guide_path(guide["slug"])
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(guide, ensure_ascii=False, separators=(",", ":")))
    return path


def apply_batch(directory: Path, source: Source, polisher: BatchPolisher, batch: Batch, guides: Dict[str, dict], state: Dict[str, dict], result: Result) -> None:
    """Writes each guide of an ended batch with Claude's summaries, if its facts are still the ones it was asked from."""
    collected = polisher.collect(batch)
    for slug, (answer, model) in sorted(collected.answers.items()):
        guide = guides.get(slug)
        if guide is None:
            try:
                guide = source.read(guide_path(slug))
            except Exception as error:  # noqa: BLE001 - one guide must not stop the others
                log.warning("Polish %s: its guide could not be read: %s", slug, error)
        if not guide or polish_hash(guide) != batch.hashes.get(slug):
            log.info("Polish %s: its facts changed since the batch was sent; left for the next polish", slug)
            continue
        path = write_guide(directory, apply_polish(guide, answer, model))
        if path not in result.written:
            result.written.append(path)
        state.setdefault(slug, {}).update({"model": model, "polish_hash": batch.hashes[slug]})
        result.polished.append(slug)


def polish_guides(directory: Path, source: Source, polisher: BatchPolisher, guides: Dict[str, dict], state: Dict[str, dict], result: Result) -> None:
    """Collects the batches earlier runs left running, then polishes this run's guides as one batch and waits for it.

    A batch still running when the wait is over is kept in `state/polish-batch.json` for the next run. A failed call
    leaves the guides templated; it never fails the run.
    """
    path = directory / POLISH_BATCH_PATH
    pending = [Batch.of(body) for body in (json.loads(path.read_text()).get("batches") or [] if path.exists() else [])]
    running: List[Batch] = []
    for batch in pending:
        try:
            if polisher.ended(batch):
                apply_batch(directory, source, polisher, batch, {}, state, result)
            else:
                running.append(batch)
        except Exception as error:  # noqa: BLE001 - the templated guides stay, and the paid batch is tried again
            log.warning("Polish: the batch %s left by an earlier run could not be read: %s", batch.id, error)
            running.append(batch)
    guides = {slug: guide for slug, guide in guides.items() if slug not in result.polished}
    if guides:
        batch = None
        try:
            batch = polisher.submit(list(guides.values()))
            if polisher.wait(batch):
                apply_batch(directory, source, polisher, batch, guides, state, result)
            else:
                running.append(batch)
        except Exception as error:  # noqa: BLE001 - the templated guides stay
            log.warning("Polish failed, keeping the templated summaries: %s", error)
            if batch is not None:
                # Submitted and paid for: the next run reads its results again.
                running.append(batch)
    if running:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"batches": [batch.json() for batch in running]}, indent=1))
    elif path.exists():
        path.unlink()


def run(
    directory: Path,
    slugs: Sequence[str],
    source: Source,
    catalog: Dict[str, dict],
    *,
    fetch_edhrec: Callable[[str], Optional[dict]] = edhrec_json,
    post_spellbook: Callable[[str, dict], dict] = post_json,
    limit: Optional[int] = None,
    delay: float = 1.0,
    force: bool = False,
    polish: Optional[BatchPolisher] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> Result:
    """Builds the guide of each commander that is due, up to `limit` of them, writing each one and the state as it goes,
    then has `polish` rewrite the summaries of the ones whose facts changed since their last polish."""
    clock = now or (lambda: datetime.now(timezone.utc))
    game_changers = load_game_changers()
    changer_ids = {card["oracle_id"] for card in game_changers}
    state_path = directory / STATE_PATH
    state: Dict[str, dict] = json.loads(state_path.read_text()) if state_path.exists() else {}
    result = Result()
    due: List[Tuple[str, dict, str]] = []
    for slug in slugs:
        try:
            page = source.read(f"edh/commanders/{slug}.json")
        except Exception as error:  # noqa: BLE001 - one commander must not stop the others
            log.error("Guide %s: its page could not be read: %s", slug, error)
            page = None
        if page and "themes" not in page:
            page = fresh_page(slug, page, fetch_edhrec)
        elif not page:
            # A commander ranked at a bracket before the refresh wrote its page.
            page = fresh_page(slug, {}, fetch_edhrec)
        if not page or not page.get("name"):
            result.failed.append(slug)
            continue
        page = {**page, "slug": slug}
        digest = fingerprint(page, game_changers)
        if not force and not is_due(state.get(slug), page, digest, clock()):
            result.unchanged.append(slug)
            continue
        due.append((slug, page, digest))
    # Never built by this generator first, then the oldest, so a short run still brings every commander round.
    due.sort(key=lambda item: (state.get(item[0], {}).get("generator") == GENERATOR, state.get(item[0], {}).get("built_at", "")))
    if limit is not None:
        result.deferred = [slug for slug, _, _ in due[limit:]]
        due = due[:limit]

    def save_state() -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, sort_keys=True, indent=1))

    unpolished: Dict[str, dict] = {}
    for slug, page, digest in due:
        try:
            guide = build_one(page, catalog, changer_ids, fetch_edhrec, post_spellbook, delay, clock())
        except Exception as error:  # noqa: BLE001 - one commander must not stop the others
            log.exception("Guide %s failed: %s", slug, error)
            guide = None
        if guide is None:
            result.failed.append(slug)
            continue
        hashed = polish_hash(guide)
        before = state.get(slug) or {}
        entry = {"generator": GENERATOR, "fingerprint": digest, "built_at": guide["generated_at"], "decks": page.get("decks") or 0}
        if before.get("polish_hash") == hashed:
            try:
                carried = carry_over(guide, source.read(guide_path(slug)))
            except Exception as error:  # noqa: BLE001 - it is polished again instead
                log.warning("Guide %s: its last polish could not be read: %s", slug, error)
                carried = None
            if carried is not None:
                guide = carried
                entry.update({"model": guide["model"], "polish_hash": hashed})
                result.carried.append(slug)
        if not guide.get("model"):
            unpolished[slug] = guide
        state[slug] = entry
        result.written.append(write_guide(directory, guide))
        save_state()
        log.info("Guide %s: %d styles, %d combos", slug, len(guide["styles"]), len(guide["combos"]))
    if polish is not None:
        polish_guides(directory, source, polish, unpolished, state, result)
        save_state()
    return result


def main(argv: Sequence[str], load_catalog=None, fetch_edhrec=edhrec_json, post_spellbook=post_json, make_polisher=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mtgmeta guides", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="data directory, mirroring the R2 bucket; missing pages are read from DATA_URL")
    parser.add_argument("--top", type=int, default=5, help="the first N commanders of edh/top.json, the week's first (default 5)")
    parser.add_argument("--brackets", action="store_true", help="also every commander edh/top.json ranks at a bracket")
    parser.add_argument("--limit", type=int, default=None, help="build at most N of the due guides")
    parser.add_argument("--slug", action="append", default=[], help="a commander's slug, in place of --top; repeatable")
    parser.add_argument("--force", action="store_true", help="build again even when the guide is not due")
    parser.add_argument("--polish", action="store_true", help="have Claude rewrite the summaries as prose, as one Message Batch (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between EDHREC pages (default 1)")
    args = parser.parse_args(list(argv))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("anthropic", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    source = Source(args.directory, os.environ.get("DATA_URL", "https://data.mooligan.com"))
    slugs = args.slug or commander_slugs(source.read("edh/top.json"), args.top, args.brackets)
    if not slugs:
        log.error("No commanders: edh/top.json could not be read")
        return 1
    polish = None
    if args.polish:
        if make_polisher is None:
            from .guide_polish import make_polisher
        polish = make_polisher()
        if polish is None:
            log.error("--polish needs ANTHROPIC_API_KEY (and GUIDE_POLISH not 0)")
            return 2
    if load_catalog is None:
        from .scryfall import card_catalog as load_catalog
    result = run(
        args.directory, slugs, source, load_catalog(),
        fetch_edhrec=fetch_edhrec, post_spellbook=post_spellbook, limit=args.limit, delay=args.delay, force=args.force, polish=polish,
    )
    print(
        f"{len(result.written)} written, {len(result.unchanged)} unchanged, {len(result.failed)} failed, "
        f"{len(result.polished)} polished, {len(result.carried)} kept their polish"
    )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
