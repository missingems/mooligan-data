"""Checks commander guides against what the app decodes before they are uploaded.

`python -m mtgmeta guide-check DIR --top 100` prints the slug of every guide in DIR that passes, one a line, and
logs what is wrong with the others. ops/guides.sh uploads only what it prints.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Sequence

log = logging.getLogger(__name__)

LEVELS = [1, 2, 3, 4, 5]


def _cards(cards, where: str, required: bool = True) -> List[str]:
    if not isinstance(cards, list) or (required and not cards):
        return [f"{where}: no cards"]
    return [f"{where}: a card without a name or oracle id" for card in cards if not isinstance(card, dict) or not isinstance(card.get("name"), str) or not isinstance(card.get("oracle_id"), str)][:1]


def problems(guide: dict, slug: str) -> List[str]:
    found: List[str] = []
    if guide.get("slug") != slug:
        found.append(f"slug {guide.get('slug')!r}")
    if not isinstance(guide.get("name"), str) or not guide["name"]:
        found.append("no name")
    styles = guide.get("styles")
    if not isinstance(styles, list) or len(styles) < 3:
        found.append("fewer than 3 styles")
    for style in styles if isinstance(styles, list) else []:
        where = f"style {style.get('id')!r}"
        if not isinstance(style.get("id"), str) or not isinstance(style.get("name"), str) or not isinstance(style.get("summary"), str):
            found.append(f"{where}: no id, name or summary")
        levels = style.get("brackets")
        if not isinstance(levels, list) or not levels or any(level not in LEVELS for level in levels):
            found.append(f"{where}: brackets {levels!r}")
        found += _cards(style.get("cards"), where)
    brackets = guide.get("brackets")
    if not isinstance(brackets, list) or [bracket.get("level") for bracket in brackets] != LEVELS:
        found.append("brackets are not levels 1 to 5")
    for bracket in brackets if isinstance(brackets, list) else []:
        if not isinstance(bracket.get("name"), str):
            found.append(f"bracket {bracket.get('level')}: no name")
        found += _cards(bracket.get("cards"), f"bracket {bracket.get('level')}", required=False)
    combos = guide.get("combos")
    if not isinstance(combos, list):
        found.append("no combos")
    for combo in combos if isinstance(combos, list) else []:
        where = f"combo {combo.get('id')!r}"
        if not isinstance(combo.get("id"), str) or combo.get("bracket") not in LEVELS or not isinstance(combo.get("requires"), list):
            found.append(f"{where}: no id, bracket or requires")
        results = combo.get("results")
        if not isinstance(results, list) or not results or not all(isinstance(result, str) for result in results):
            found.append(f"{where}: no results")
        found += _cards(combo.get("cards"), where)
    return found


def main(argv: Sequence[str]) -> int:
    from .guides import Source, commander_slugs

    parser = argparse.ArgumentParser(prog="python -m mtgmeta guide-check", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="data directory holding edh/commanders/{slug}/guide.json")
    parser.add_argument("--top", type=int, default=5, help="the first N commanders of edh/top.json (default 5)")
    parser.add_argument("--slug", action="append", default=[], help="a commander's slug, in place of --top; repeatable")
    args = parser.parse_args(list(argv))
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    slugs = args.slug or commander_slugs(Source(args.directory, os.environ.get("DATA_URL", "https://data.mooligan.com")).read("edh/top.json"), args.top)
    failed = 0
    for slug in slugs:
        path = args.directory / "edh" / "commanders" / slug / "guide.json"
        if not path.exists():
            log.warning("Guide %s: not written", slug)
            continue
        try:
            found = problems(json.loads(path.read_text()), slug)
        except ValueError as error:
            found = [f"not JSON: {error}"]
        if found:
            failed += 1
            log.error("Guide %s: %s", slug, "; ".join(found))
        else:
            print(slug)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
