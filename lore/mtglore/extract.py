"""Has Claude read each saved page and list who and what is in it, as data/extracted/<slug>.json.

Every page goes through the Message Batches API (half price, done within the hour as a rule). Claude
returns, for one page:

- entities: every named character, creature, deity, plane, location, faction, artifact, event and concept
- events: what happens, who takes part, where, with a verbatim quote from one paragraph
- relations: how two entities stand to each other, with a quote

A quote that is not word for word in the paragraph it names is a sign the model made something up, so
the event or relation is dropped (and kept under "rejected" for review). Names in events and relations
must be ones listed under entities.

The batch in flight is kept in data/state/batch.json, so a run that stops while it waits picks the same
batch up again instead of paying for a second one.
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
# Bump when the prompt or schema changes enough that saved extractions should be redone.
PROMPT_VERSION = 1

ENTITY_TYPES = ["character", "creature", "deity", "plane", "location", "faction", "artifact", "event", "concept"]
RELATIONS = [
    "ally", "enemy", "family", "romantic", "mentor_of", "member_of", "leader_of", "serves",
    "created", "killed", "located_in", "other",
]

SYSTEM = """You index the official Magic: The Gathering story published by Wizards of the Coast. You read one page \
at a time and record, as data, who and what is in it and what happens. The index answers fans' questions such as \
"who is Jace?" and "what happened to Jace?", and every fact in it is shown with the quote it came from, so it must \
hold only what this page says.

Entities: list every named character, creature, deity, plane, location, faction (guilds, orders, clans, armies), \
artifact (named items, weapons, machines), event (named happenings such as "the Mending" or "the Invasion") and \
concept (named phenomena, magic, places between planes such as "the Blind Eternities"). Give each its fullest name \
as used in this page or as Magic fans know it ("Jace Beleren", not "Jace"), and every other name or title this page \
calls it under aliases. Unnamed people ("the guard") are not entities. A changed or alternate version of a character \
that the page treats as distinct (a Phyrexian-compleated version, an alternate-reality version, a past life) gets its \
own entry, named for the difference ("Phyrexian Nissa Revane"), with the original's name under aliases only if the \
page uses it for them. Planeswalkers are characters; say so in the description. The description is one or two \
sentences on who or what they are, from this page.

Events: list what happens in this page, in the order it happens, at the level a recap would tell it: arrivals, \
decisions, fights, discoveries, deaths, betrayals, revelations, changes of allegiance or of power. Mark as major what \
changes a character's situation for good (a death, losing a spark, compleation, a new title, the end of a war). \
Participants and location must be names you listed under entities. Flashbacks and memories are events too; say \
they are in the summary.

Relations: how two entities stand to each other as of this page, with the evidence. Use "other" with a short note \
when none of the listed relations fits.

Quotes: copy them exactly, character for character, from a single paragraph, and give that paragraph's number. \
Keep them short (one sentence or a clause, under 40 words) and never join, trim the middle of, or paraphrase a \
quote. If nothing in the page supports a fact word for word, leave the fact out.

Leave out what is not story: editor's notes, credits, links and promotions.

Storyline: the name of the story arc or set this page belongs to ("March of the Machine"), from the page, or "" if \
the page doesn't say."""

SCHEMA = {
    "type": "object",
    "properties": {
        "storyline": {"type": "string"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ENTITY_TYPES},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "presence": {"type": "string", "enum": ["appears", "mentioned"]},
                },
                "required": ["name", "type", "aliases", "description", "presence"],
                "additionalProperties": False,
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "participants": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "string"},
                    "importance": {"type": "string", "enum": ["major", "minor"]},
                    "paragraph": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["summary", "participants", "location", "importance", "paragraph", "quote"],
                "additionalProperties": False,
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "relation": {"type": "string", "enum": RELATIONS},
                    "target": {"type": "string"},
                    "note": {"type": "string"},
                    "paragraph": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["source", "relation", "target", "note", "paragraph", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["storyline", "entities", "events", "relations"],
    "additionalProperties": False,
}


KINDS = {
    "story": "Magic Story article",
    "profile": "profile page of a planeswalker or plane",
    "archive": "story column from the old wizards.com (Savor the Flavor, Uncharted Realms, Magic Arcana or a feature), "
               "as the Internet Archive saved it",
    "cards": "the flavor text of every card in one Magic set; each paragraph is one card's flavor text, after the card's "
             "name in parentheses (the name is not part of the text to quote). Flavor text quotes characters or "
             "in-world writings, and the attribution after the dash names the speaker",
    "wiki": "MTG Wiki article (fan-written summary of the official story, including the novels); a line starting "
            "with ## is a section heading, not a paragraph",
}


def page_prompt(page: dict) -> str:
    lines = [
        f"Title: {page['title']}",
        f"Kind: {KINDS.get(page['kind'], page['kind'])}",
    ]
    if page.get("story_date"):
        lines.append(f"First published: {page['story_date']}")
    if page.get("storyline_nav"):
        lines.append(f"Story navigation names the storyline: {page['storyline_nav']['title']}")
    if page.get("description"):
        lines.append(f"Summary line: {page['description']}")
    lines.append("")
    lines.append("Paragraphs, numbered (a blank line between numbers marks a scene break):")
    scene = None
    for index, paragraph in enumerate(page["paragraphs"]):
        if scene is not None and paragraph["scene"] != scene:
            lines.append("")
            if paragraph.get("section"):
                lines.append(f"## {paragraph['section']}")
        scene = paragraph["scene"]
        card = f"({paragraph['card']}) " if paragraph.get("card") else ""
        lines.append(f"[{index}] {card}{paragraph['text']}")
    return "\n".join(lines)


def request_params(page: dict, effort: str) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 32000,
        # The instructions are the same for every page, so they are cached across the batch.
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": page_prompt(page)}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    }


# --- checking what comes back ---------------------------------------------------------------------------

_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-", "…": "...", " ": " "})


def fold(text: str) -> str:
    """Text as compared for quotes: typographic quotes and dashes made plain, spaces collapsed, lower case."""
    text = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return re.sub(r"\s+", " ", text).strip().lower()


def locate(quote: str, paragraphs: List[dict], hint: int) -> Optional[int]:
    """The paragraph holding `quote` word for word: the one Claude named, else any other, else None.

    The quote must start and end on word boundaries, so "He heard" does not pass for "She heard".
    """
    needle = fold(quote).strip(" .,;:!?\"'")
    if len(needle) < 8:
        return None
    pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)")
    order = ([hint] if 0 <= hint < len(paragraphs) else []) + [i for i in range(len(paragraphs)) if i != hint]
    for index in order:
        if pattern.search(fold(paragraphs[index]["text"])):
            return index
    return None


def check(page: dict, raw: dict) -> dict:
    """Keeps the events and relations whose quotes are in the page and whose names are listed entities."""
    entities = []
    names: Dict[str, str] = {}
    for entity in raw.get("entities", []):
        name = entity["name"].strip()
        if not name or fold(name) in names:
            continue
        entity = {**entity, "name": name, "aliases": [a.strip() for a in entity["aliases"] if a.strip() and fold(a) != fold(name)]}
        entities.append(entity)
        names[fold(name)] = name
    for entity in entities:
        for alias in entity["aliases"]:
            names.setdefault(fold(alias), entity["name"])

    def known(name: str) -> Optional[str]:
        return names.get(fold(name)) if name and name.strip() else None

    events, relations, rejected = [], [], []
    for event in raw.get("events", []):
        where = locate(event["quote"], page["paragraphs"], event["paragraph"])
        participants = [known(name) for name in event["participants"]]
        if where is None:
            rejected.append({"kind": "event", "reason": "quote not in page", **event})
        elif not participants or None in participants:
            rejected.append({"kind": "event", "reason": "unlisted participant", **event})
        else:
            location = known(event["location"]) or ""
            events.append({**event, "participants": list(dict.fromkeys(participants)), "location": location, "paragraph": where})
    for relation in raw.get("relations", []):
        where = locate(relation["quote"], page["paragraphs"], relation["paragraph"])
        source, target = known(relation["source"]), known(relation["target"])
        if where is None:
            rejected.append({"kind": "relation", "reason": "quote not in page", **relation})
        elif source is None or target is None or source == target:
            rejected.append({"kind": "relation", "reason": "unlisted entity", **relation})
        else:
            relations.append({**relation, "source": source, "target": target, "paragraph": where})
    return {
        "storyline": raw.get("storyline", "").strip(),
        "entities": entities,
        "events": events,
        "relations": relations,
        "rejected": rejected,
    }


# --- running the batch ----------------------------------------------------------------------------------


# Where pages are kept, one folder per kind: the current site's stories and profiles, then the older sources
# (see sources.py).
PAGE_FOLDERS = ("stories", "profiles", "archive", "cards", "wiki")


def load_pages(directory: Path) -> Dict[str, dict]:
    """Every saved page, keyed by the id its extraction is saved under ("stories/<slug>")."""
    pages = {}
    for folder in PAGE_FOLDERS:
        for path in sorted((directory / folder).glob("*.json")):
            if not path.name.startswith("_"):
                pages[f"{folder}/{path.stem}"] = json.loads(path.read_text())
    return pages


def _custom_id(key: str) -> str:
    # Batch ids allow [a-zA-Z0-9_-] up to 64 characters; the mapping back is kept in the state file.
    return re.sub(r"[^a-zA-Z0-9_-]", "_", key)[-64:]


def pending(directory: Path, pages: Dict[str, dict]) -> List[str]:
    """The pages with no extraction yet, or one made by an older prompt."""
    keys = []
    for key in pages:
        path = directory / "extracted" / f"{key}.json"
        if not path.exists() or json.loads(path.read_text()).get("prompt_version") != PROMPT_VERSION:
            keys.append(key)
    return keys


def submit(client, directory: Path, pages: Dict[str, dict], keys: Iterable[str], effort: str) -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    keys = list(keys)
    ids = {_custom_id(key): key for key in keys}
    if len(ids) != len(keys):
        raise ValueError("Two pages map to the same batch id")
    batch = client.messages.batches.create(
        requests=[Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**request_params(pages[key], effort))) for cid, key in ids.items()]
    )
    state = {"batch_id": batch.id, "submitted_at": _now(), "effort": effort, "ids": ids}
    _state_path(directory).parent.mkdir(parents=True, exist_ok=True)
    _state_path(directory).write_text(json.dumps(state, indent=1) + "\n")
    log.info("Submitted batch %s with %d pages", batch.id, len(keys))
    return batch.id


def wait(client, batch_id: str, deadline: float, poll: float = 60) -> bool:
    """Whether the batch ended before `deadline` (a time.time())."""
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return True
        counts = batch.request_counts
        log.info("Batch %s: %d processing, %d done", batch_id, counts.processing, counts.succeeded + counts.errored)
        if time.time() + poll > deadline:
            return False
        time.sleep(poll)


def save(directory: Path, key: str, page: dict, raw: dict, model: str, effort: Optional[str]) -> dict:
    """Checks one page's raw extraction and saves it as data/extracted/<key>.json."""
    checked = check(page, raw)
    document = {
        "page": key,
        "url": page["url"],
        "title": page["title"],
        "story_date": page.get("story_date", ""),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "effort": effort,
        "extracted_at": _now(),
        **checked,
    }
    path = directory / "extracted" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
    return checked


def recheck(directory: Path) -> dict:
    """Runs every saved extraction through `check` again, as after the check gets stricter.

    What no longer passes moves to `rejected`; what was rejected before stays there.
    """
    pages = load_pages(directory)
    report = {"pages": 0, "newly_rejected": 0}
    for path in sorted((directory / "extracted").glob("*/*.json")):
        document = json.loads(path.read_text())
        page = pages.get(document["page"])
        if page is None:
            continue
        checked = check(page, document)
        newly = len(checked["rejected"])
        checked["rejected"] += document.get("rejected", [])
        path.write_text(json.dumps({**document, **checked}, ensure_ascii=False, indent=1) + "\n")
        report["pages"] += 1
        report["newly_rejected"] += newly
    return report


def collect(client, directory: Path, pages: Dict[str, dict]) -> dict:
    """Saves the finished batch's extractions, and clears the state so the next run submits what is left."""
    state = json.loads(_state_path(directory).read_text())
    report = {"saved": 0, "failed": [], "kept": 0, "rejected": 0, "input_tokens": 0, "output_tokens": 0}
    for result in client.messages.batches.results(state["batch_id"]):
        key = state["ids"].get(result.custom_id)
        if key is None or key not in pages:
            continue
        if result.result.type != "succeeded":
            report["failed"].append(f"{key}: {result.result.type}")
            continue
        message = result.result.message
        report["input_tokens"] += message.usage.input_tokens + (message.usage.cache_read_input_tokens or 0) + (message.usage.cache_creation_input_tokens or 0)
        report["output_tokens"] += message.usage.output_tokens
        if message.stop_reason != "end_turn":
            report["failed"].append(f"{key}: stopped on {message.stop_reason}")
            continue
        text = next((block.text for block in message.content if block.type == "text"), "")
        try:
            raw = json.loads(text)
        except ValueError:
            report["failed"].append(f"{key}: not JSON")
            continue
        checked = save(directory, key, pages[key], raw, message.model, state.get("effort"))
        report["saved"] += 1
        report["kept"] += len(checked["events"]) + len(checked["relations"])
        report["rejected"] += len(checked["rejected"])
    _state_path(directory).unlink()
    return report


def run(client, directory: Path, limit: Optional[int], effort: str, wait_seconds: float) -> Tuple[str, dict]:
    """Collects a batch in flight if there is one, else submits the pages still to do. One step per call."""
    pages = load_pages(directory)
    if _state_path(directory).exists():
        batch_id = json.loads(_state_path(directory).read_text())["batch_id"]
    else:
        keys = pending(directory, pages)
        if limit is not None:
            keys = keys[:limit]
        if not keys:
            return "nothing to do", {}
        batch_id = submit(client, directory, pages, keys, effort)
    if not wait(client, batch_id, time.time() + wait_seconds):
        return f"batch {batch_id} still running; run again to collect it", {}
    return f"collected batch {batch_id}", collect(client, directory, pages)


def _state_path(directory: Path) -> Path:
    return directory / "state" / "batch.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
