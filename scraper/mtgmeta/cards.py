"""Turns the stored decklists into one page per card: where that card is played.

A card page answers "which archetypes play this, and in how many of the
format's decks", so an app can show it without a query API.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Dict, List, Tuple

SCHEMA = 1
# Archetypes listed per format on a card page, most decks first.
MAX_ARCHETYPES = 12
# Decks linked per archetype, newest first.
MAX_DECK_IDS = 5


def slug(card_name: str) -> str:
    """The file name for a card: "Fable of the Mirror-Breaker" -> "fable-of-the-mirror-breaker".

    Only the front face counts, whether written "Fire // Ice" (Scryfall) or
    "Fire/Ice" (MTGGoldfish), and accents fold away, since MTGGoldfish writes
    "Bartolome" for Scryfall's "Bartolomé". MTGMetaKit's CardSlug applies the
    same rule, so the two must change together.
    """
    front = card_name.split("/", 1)[0]
    folded = unicodedata.normalize("NFKD", front).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def build_card_pages(
    formats: Dict[str, "FormatDecks"],
    generated_at: str,
) -> Tuple[Dict[str, dict], dict]:
    """Returns the page for every card played, keyed by slug, and the index of them all."""
    pages: Dict[str, dict] = {}
    for format, decks in formats.items():
        for slug_name, entry in _format_entries(decks).items():
            page = pages.setdefault(
                slug_name,
                {"schema": SCHEMA, "slug": slug_name, "card_name": entry["card_name"], "generated_at": generated_at, "formats": {}},
            )
            page["formats"][format] = entry["format_entry"]
    index = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "cards": {
            slug_name: {"name": page["card_name"], "formats": sorted(page["formats"])}
            for slug_name, page in sorted(pages.items())
        },
    }
    return pages, index


class FormatDecks:
    """The decks of one format in the history window, newest first.

    `contents` maps a deck id to its mainboard and sideboard as (quantity, card
    name) pairs; `archetypes` maps a deck id to its archetype's id and name.
    """

    def __init__(self, contents: Dict[str, dict], archetypes: Dict[str, Tuple[str, str]]) -> None:
        self.contents = contents
        self.archetypes = archetypes


def _format_entries(decks: FormatDecks) -> Dict[str, dict]:
    total = len(decks.contents)
    if total == 0:
        return {}
    names: Dict[str, str] = {}
    counts: Dict[str, int] = {}  # slug -> decks playing it
    # slug -> archetype id -> {"name", "decks", "copies", "deck_ids"}
    by_archetype: Dict[str, Dict[str, dict]] = {}

    for deck_id, deck in decks.contents.items():
        archetype_id, archetype_name = decks.archetypes.get(deck_id, ("", "Other"))
        # A card in both boards is one deck playing it, and its copies add up.
        copies: Dict[str, int] = {}
        for quantity, card_name in [*deck.get("m", []), *deck.get("s", [])]:
            key = slug(card_name)
            if not key:
                continue
            names.setdefault(key, card_name)
            copies[key] = copies.get(key, 0) + quantity
        for key, quantity in copies.items():
            counts[key] = counts.get(key, 0) + 1
            entry = by_archetype.setdefault(key, {}).setdefault(
                archetype_id, {"name": archetype_name, "decks": 0, "copies": 0, "deck_ids": []}
            )
            entry["decks"] += 1
            entry["copies"] += quantity
            if len(entry["deck_ids"]) < MAX_DECK_IDS:
                entry["deck_ids"].append(deck_id)

    entries = {}
    for key, archetypes in by_archetype.items():
        listed = sorted(archetypes.items(), key=lambda item: item[1]["decks"], reverse=True)[:MAX_ARCHETYPES]
        entries[key] = {
            "card_name": names[key],
            "format_entry": {
                "decks": counts[key],
                "of_decks": total,
                "archetypes": [
                    {
                        "archetype_id": archetype_id or None,
                        "name": entry["name"],
                        "decks": entry["decks"],
                        "avg_copies": round(entry["copies"] / entry["decks"], 1),
                        "deck_ids": entry["deck_ids"],
                    }
                    for archetype_id, entry in listed
                ],
            },
        }
    return entries


def page_hash(page: dict) -> str:
    # generated_at changes every run, so it is left out of the comparison.
    body = {key: value for key, value in page.items() if key != "generated_at"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
