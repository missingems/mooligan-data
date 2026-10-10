"""The printed names and pictures of the cards Explore shows, in the languages the app is translated into.

Reads the oracle ids of `today.json` and `explore.json`, streams Scryfall's every-printing file once, and writes each
file's `localized` map back: oracle id to language to the card as printed in that language. `today.json` also gets
the type line and rules text, so a card opened from Today reads in full offline. See docs/data-format.md.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .scryfall import ALL_CARDS_URL, SKIPPED_LAYOUTS, _bulk_download_uri, bulk_lines

log = logging.getLogger(__name__)

# The languages published, in the order they are written; English is the card the app already has.
LANGUAGES = ("ja", "fr", "it", "es", "de")
# The published files that carry the map, and whether their cards also carry text.
FILES = (("today.json", True), ("explore.json", False))
# The last good run's cards with their text, for a run that cannot read Scryfall's file.
STATE = "state/localized.json.gz"
# A scan that is not a photograph of the card: a stand-in for a card Scryfall has no picture of yet.
UNUSABLE_IMAGES = {"missing", "placeholder"}

# What a line must hold to be worth parsing: a language this module reads, and an oracle id (on the card, or on a
# face when the card has none of its own).
LANG_FIELD = re.compile(rb'"lang":\s*"(en|ja|fr|it|es|de)"')
ORACLE_FIELD = re.compile(rb'"oracle_id":\s*"([^"]+)"')
DIGITS = re.compile(r"\d+")

Printing = Dict[str, Any]
Rank = Tuple[int, str, str, str]


def oracle_ids(document: Any) -> Set[str]:
    """Every oracle id in a JSON document, wherever it sits."""
    found: Set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "oracle_id" and isinstance(value, str):
                found.add(value)
            else:
                found |= oracle_ids(value)
    elif isinstance(document, list):
        for value in document:
            found |= oracle_ids(value)
    return found


def pick(lines: Iterable[bytes], wanted: Set[str]) -> Dict[str, Dict[str, Printing]]:
    """For each wanted oracle id, the printing to show in each language that has one, in one pass over the lines.

    The English printing is the one the app shows: the newest paper printing, then the lowest collector number.
    A language shows its printing of the same set and collector number when it has one with a usable picture,
    else its newest paper printing with a usable picture. Only the best so far of each is kept, so memory holds
    a handful of printings per wanted card however large the file.
    """
    wanted_bytes = {oracle_id.encode() for oracle_id in wanted}
    english: Dict[str, Tuple[Rank, Printing]] = {}
    same_printing: Dict[Tuple[str, str], Dict[Tuple[str, str], Tuple[Rank, Printing]]] = {}
    newest: Dict[Tuple[str, str], Tuple[Rank, Printing]] = {}
    for line in lines:
        if not LANG_FIELD.search(line):
            continue
        if wanted_bytes.isdisjoint(ORACLE_FIELD.findall(line)):
            continue
        printing = json.loads(line)
        oracle_id = _oracle_id(printing)
        language = printing.get("lang")
        if oracle_id not in wanted or printing.get("layout") in SKIPPED_LAYOUTS:
            continue
        if "paper" not in (printing.get("games") or []):
            continue
        rank = _rank(printing)
        if language == "en":
            if oracle_id not in english or rank < english[oracle_id][0]:
                english[oracle_id] = (rank, printing)
        elif language in LANGUAGES and _usable(printing):
            key = (oracle_id, language)
            printed = (printing.get("set") or "", printing.get("collector_number") or "")
            candidates = same_printing.setdefault(key, {})
            if printed not in candidates or rank < candidates[printed][0]:
                candidates[printed] = (rank, printing)
            if key not in newest or rank < newest[key][0]:
                newest[key] = (rank, printing)
    picked: Dict[str, Dict[str, Printing]] = {}
    for oracle_id in sorted(wanted):
        shown = english.get(oracle_id)
        printed = (shown[1].get("set") or "", shown[1].get("collector_number") or "") if shown else None
        for language in LANGUAGES:
            key = (oracle_id, language)
            match = same_printing.get(key, {}).get(printed) if printed else None
            chosen = match or newest.get(key)
            if chosen:
                picked.setdefault(oracle_id, {})[language] = chosen[1]
    return picked


def entry(printing: Printing, with_text: bool) -> Dict[str, Any]:
    """A printing as `localized` publishes it: name and pictures, and the text when `with_text`; missing keys are left out."""
    faces = printing.get("card_faces") or []
    result: Dict[str, Any] = {}
    name = _name(printing, faces)
    if name:
        result["name"] = name
    image, back_image = _images(printing, faces)
    if image:
        result["image"] = image
    if back_image:
        result["back_image"] = back_image
    if len(faces) > 1:
        face_entries = [_text(face, with_text, {"name": face.get("printed_name")}) for face in faces]
        if any(face_entries):
            result["faces"] = face_entries
    if with_text:
        result.update(_text(printing, True, {}))
    return result


def localize(directory: Path, url: Optional[str] = None) -> List[str]:
    """Writes `localized` into the published `today.json` and `explore.json` of `directory`; returns what went wrong.

    The file is streamed once, whichever files are there. Each file gets only its own cards. A file with no
    cards to look up costs no download. When the file cannot be read, the cards come from `state/localized.json.gz`,
    which the last good run wrote, and that is returned as a problem; with no such state the error is raised.
    """
    documents: Dict[str, Dict[str, Any]] = {}
    sizes: Dict[str, int] = {}
    for name, _ in FILES:
        path = directory / name
        if path.exists():
            body = path.read_bytes()
            documents[name] = json.loads(body)
            sizes[name] = len(body)
    if not documents:
        log.info("Localized: no today.json or explore.json in %s", directory)
        return []
    wanted: Set[str] = set()
    ids: Dict[str, Set[str]] = {}
    for name, document in documents.items():
        ids[name] = oracle_ids({key: value for key, value in document.items() if key != "localized"})
        wanted |= ids[name]
    problems: List[str] = []
    entries: Dict[bool, Dict[str, Dict[str, Dict[str, Any]]]] = {True: {}, False: {}}
    if wanted:
        try:
            picked = pick(bulk_lines(url or _bulk_download_uri(ALL_CARDS_URL)), wanted)
            if not picked:
                raise ValueError("none of %d cards had a localized printing" % len(wanted))
        except Exception as error:  # noqa: BLE001 - yesterday's text stands in for a file that cannot be read
            saved = _read_state(directory, wanted)
            if not saved:
                raise
            log.warning("Localized: Scryfall's file could not be read: %s", error)
            problems.append("Localized: could not read Scryfall's file (%s); %d of %d cards come from the last good run" % (error, len(saved), len(wanted)))
            entries[True] = saved
            entries[False] = {oracle_id: {language: _without_text(card) for language, card in languages.items()} for oracle_id, languages in saved.items()}
        else:
            for with_text in (True, False):
                entries[with_text] = {
                    oracle_id: {language: entry(printing, with_text) for language, printing in languages.items()}
                    for oracle_id, languages in picked.items()
                }
            _write_state(directory, entries[True])
    counts = {language: 0 for language in LANGUAGES}
    for languages in entries[True].values():
        for language in languages:
            counts[language] += 1
    log.info("Localized: %d cards wanted, %s", len(wanted), ", ".join("%s %d" % (language, counts[language]) for language in LANGUAGES))
    missing = sorted(wanted - set(entries[True]))
    if missing:
        log.info("Localized: %d cards with no localized printing: %s", len(missing), ", ".join(missing[:20]))
    for name, with_text in FILES:
        if name not in documents:
            continue
        document = documents[name]
        document["localized"] = {
            oracle_id: {language: entries[with_text][oracle_id][language] for language in LANGUAGES if language in entries[with_text][oracle_id]}
            for oracle_id in sorted(ids[name] & set(entries[with_text]))
        }
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        (directory / name).write_text(body, encoding="utf-8")
        log.info(
            "Localized: %s %d cards, %d to %d bytes (%d gzipped)",
            name, len(document["localized"]), sizes[name], len(body.encode()), len(gzip.compress(body.encode(), mtime=0)),
        )
    return problems


def _read_state(directory: Path, wanted: Set[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """The last good run's cards, with text, for the wanted ids it has; empty when there is no readable state."""
    path = directory / STATE
    try:
        saved = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    return {oracle_id: saved[oracle_id] for oracle_id in sorted(wanted) if isinstance(saved.get(oracle_id), dict)}


def _write_state(directory: Path, cards: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
    path = directory / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
    path.write_bytes(gzip.compress(body.encode(), mtime=0))


def _without_text(card: Dict[str, Any]) -> Dict[str, Any]:
    """A saved card as `explore.json` shows it: name and pictures, and the faces' names."""
    result = {key: value for key, value in card.items() if key in ("name", "image", "back_image")}
    faces = [{key: value for key, value in face.items() if key == "name"} for face in card.get("faces") or []]
    if any(faces):
        result["faces"] = faces
    return result


def _oracle_id(printing: Printing) -> Optional[str]:
    return printing.get("oracle_id") or (printing.get("card_faces") or [{}])[0].get("oracle_id")


def _rank(printing: Printing) -> Rank:
    """Sorts the better printing first: newest release, lowest collector number, then set code and id."""
    released = (printing.get("released_at") or "").replace("-", "")
    collector = DIGITS.sub(lambda match: match.group().zfill(8), printing.get("collector_number") or "")
    return (-int(released) if released.isdigit() else 0, collector, printing.get("set") or "", printing.get("id") or "")


def _usable(printing: Printing) -> bool:
    return printing.get("image_status") not in UNUSABLE_IMAGES


def _name(printing: Printing, faces: List[dict]) -> Optional[str]:
    if printing.get("printed_name"):
        return printing["printed_name"]
    names = [face.get("printed_name") for face in faces]
    if len(names) > 1 and all(names):
        return " // ".join(names)
    return names[0] if names and names[0] else None


def _images(printing: Printing, faces: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """The normal-size pictures: one for a single-sided card; front and back for a double-faced one with both, else none."""
    if printing.get("image_uris"):
        return printing["image_uris"].get("normal"), None
    if len(faces) > 1 and faces[0].get("image_uris") and faces[1].get("image_uris"):
        return faces[0]["image_uris"].get("normal"), faces[1]["image_uris"].get("normal")
    return None, None


def _text(source: Printing, with_text: bool, result: Dict[str, Any]) -> Dict[str, Any]:
    if with_text:
        for key, field in (("type_line", "printed_type_line"), ("text", "printed_text"), ("flavor_text", "flavor_text")):
            result[key] = source.get(field)
    return {key: value for key, value in result.items() if value}


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: python -m mtgmeta.localized DIR")
    for problem in localize(Path(sys.argv[1]), os.environ.get("LOCALIZE_ALL_CARDS_URL") or None):
        log.error("%s", problem)
