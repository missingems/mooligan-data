"""The combos a commander's guide can assemble, from Commander Spellbook, as the guide's `combos`.

`python -m mtgmeta guide-combos DIR --top 100` reads each guide (from DIR, else the live site), asks Spellbook's
find-my-combos for the combos its commander and every card of the guide make together, and writes the guide back to
DIR with them. It calls no model, so it costs nothing and can run again whenever Spellbook learns new combos.
`guides` adds them too, to each guide it writes. See docs/data-format.md.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

log = logging.getLogger(__name__)

SPELLBOOK = "https://backend.commanderspellbook.com"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
PAGE_SIZE = 100
MAX_PAGES = 20
DELAY = 0.5
MAX_COMBOS = 30
# Spellbook's own reading of its bracket tags: Exhibition, Core, Oddball, Powerful, Spicy, Ruthless. Banned is dropped.
BRACKETS = {"E": 1, "C": 2, "O": 2, "P": 3, "S": 3, "R": 4}
# Standalone and contextual results; helper and utility features are steps, not what the combo makes.
RESULT_STATUSES = {"S", "C"}


def post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"}, method="POST"
    )
    time.sleep(DELAY)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read())


def decklist(guide: dict) -> dict:
    """The guide as a Spellbook deck: the commander, both halves of a pair, and every card of its styles and brackets."""
    name = guide["name"]
    commanders = [name, *(half.strip() for half in name.split("//"))] if "//" in name else [name]
    seen, main = set(commanders), []
    for card in (card for group in (*guide.get("styles", []), *guide.get("brackets", [])) for card in group.get("cards", [])):
        if card["name"] not in seen:
            seen.add(card["name"])
            main.append({"card": card["name"], "quantity": 1})
    return {"commanders": [{"card": each} for each in commanders], "main": main}


def included(deck: dict, post: Callable[[str, dict], dict] = post_json) -> List[dict]:
    """Every variant Spellbook finds whole in the deck, through all of its pages."""
    variants: List[dict] = []
    url: Optional[str] = f"{SPELLBOOK}/find-my-combos?limit={PAGE_SIZE}"
    for _ in range(MAX_PAGES):
        if not url:
            break
        body = post(url, deck)
        variants += (body.get("results") or {}).get("included") or []
        url = body.get("next")
    return variants


def combos(variants: Iterable[dict], limit: int = MAX_COMBOS) -> List[dict]:
    """The guide's combos from Spellbook's variants: the most played first, one per set of cards."""
    kept, seen = [], set()
    for variant in sorted(variants, key=lambda each: -(each.get("popularity") or 0)):
        if variant.get("status") != "OK" or variant.get("spoiler") or not (variant.get("legalities") or {}).get("commander"):
            continue
        tag = variant.get("bracketTag")
        if tag not in BRACKETS:
            continue
        cards = [{"name": use["card"]["name"], "oracle_id": use["card"].get("oracleId")} for use in variant.get("uses") or []]
        if not cards or any(not card["oracle_id"] for card in cards):
            continue
        results = [each["feature"]["name"] for each in variant.get("produces") or [] if each["feature"].get("status") in RESULT_STATUSES]
        key = frozenset(card["oracle_id"] for card in cards)
        if not results or key in seen:
            continue
        seen.add(key)
        kept.append({
            "id": variant["id"],
            "cards": cards,
            "requires": [each["template"]["name"] for each in variant.get("requires") or []],
            "results": results,
            "bracket": BRACKETS[tag],
            "bracket_tag": tag,
        })
        if len(kept) == limit:
            break
    return kept


def find(guide: dict, post: Callable[[str, dict], dict] = post_json) -> List[dict]:
    return combos(included(decklist(guide), post))


def with_combos(guide: dict, find_combos: Callable[[dict], List[dict]] = find) -> dict:
    """The guide with its combos, or as it was when Spellbook cannot be read."""
    try:
        return {**guide, "combos": find_combos(guide)}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        log.warning("Combos for %s failed: %s", guide.get("slug"), error)
        return guide


def main(argv: Sequence[str], find_combos: Callable[[dict], List[dict]] = find) -> int:
    from .guides import Source, commander_slugs

    parser = argparse.ArgumentParser(prog="python -m mtgmeta guide-combos", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="data directory, mirroring the R2 bucket; missing guides are read from DATA_URL")
    parser.add_argument("--top", type=int, default=5, help="the first N commanders of edh/top.json (default 5)")
    parser.add_argument("--slug", action="append", default=[], help="a commander's slug, in place of --top; repeatable")
    args = parser.parse_args(list(argv))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    source = Source(args.directory, os.environ.get("DATA_URL", "https://data.mooligan.com"))
    slugs = args.slug or commander_slugs(source.read("edh/top.json"), args.top)
    written, missing, failed = 0, 0, 0
    for slug in slugs:
        path = f"edh/commanders/{slug}/guide.json"
        guide = source.read(path)
        if not guide:
            missing += 1
            continue
        enriched = with_combos(guide, find_combos)
        if "combos" not in enriched:
            failed += 1
            continue
        target = args.directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(enriched, ensure_ascii=False, separators=(",", ":")))
        written += 1
        log.info("Combos %s: %d", slug, len(enriched["combos"]))
    print(f"{written} written, {missing} without a guide, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
