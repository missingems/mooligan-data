"""Short "who is X" bios for the entities the index mentions most, as data/bios/<id>.json.

A bio is written from what the index already holds on the entity (what each page says of it, its timeline,
its relations), not from memory, and every sentence cites the events, relations or pages it rests on. A
sentence citing nothing, or an id that is not in the entity's own material, is dropped, so a bio can say no
more than the quotes and pages behind it.

    python -m mtglore bio-input <id>          what to write a bio from
    python -m mtglore bio-ingest <id> raw.json   check one and save it

The build puts a saved bio into the entity's file, and its summary becomes the entity's description.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# Past this many events, only the major ones go into the input.
MAX_EVENTS = 150

INSTRUCTIONS = """Write a short bio of this entity from the official Magic: The Gathering story, for a fan asking \
"who is X?" or "what happened to X?". Use only what the material below says: what each page says of it, its \
events in story order, and its relations. Do not add anything you know from elsewhere.

Return JSON:
{"summary": {"text": "...", "cites": [...]},
 "bio": [{"text": "...", "cites": [...]}, ...],
 "status": {"text": "...", "cites": [...]}}

- summary: one sentence on who or what it is (for a character: what they are, where from, what they are known for).
- bio: 3 to 8 sentences telling the story in order, the turning points first among equals; fewer for a minor entity.
- status: one sentence on where things stand as of the latest story that mentions it (alive, dead, compleated,
  missing, ruling somewhere...). If the material does not say, say what the last event shows, plainly.
- cites: the ids in square brackets from the material (events like "some-page-e4", relations like "some-page-r2",
  what a page says like "p:stories/some-page") that support the sentence. Every sentence needs at least one; a sentence the ids don't support will be dropped.
- Plain, neutral prose; no headings, no lists inside text."""


def material(index: Path, entity_id: str) -> str:
    entity = json.loads((index / "entity" / f"{entity_id}.json").read_text())
    titles = {page["page"]: page["title"] for page in json.loads((index / "pages.json").read_text())}
    lines = [f"Entity: {entity['name']} ({entity['type']})"]
    if entity["aliases"]:
        lines.append("Also called: " + ", ".join(entity["aliases"][:25]))
    lines.append(f"On {entity['pages']} pages, {entity['first_seen'] or '?'} to {entity['last_seen'] or '?'}.")
    lines.append("")
    lines.append("What each page says of it:")
    for said in entity["pages_say"]:
        source = "" if said.get("source", "wizards") == "wizards" else f" ({said['source']})"
        lines.append(f"[p:{said['page']}] {said['story_date'] or 'undated'} | {titles.get(said['page'], said['page'])}{source} | {said['presence']} | {said['description']}")
    events = entity["timeline"]
    if len(events) > MAX_EVENTS:
        events = [event for event in events if event["importance"] == "major"]
        lines.append("")
        lines.append(f"Its major events, in story order ({len(events)} of {len(entity['timeline'])}):")
    else:
        lines.append("")
        lines.append("Its events, in story order:")
    for event in events:
        storyline = f" | {event['storyline']}" if event["storyline"] else ""
        lines.append(f"[{event['id']}] {event['story_date'] or 'profile'}{storyline} | {event['summary']}")
    if entity["relations"]:
        lines.append("")
        lines.append("Its relations:")
        for relation in entity["relations"][:40]:
            note = f" ({relation['note']})" if relation["note"] else ""
            lines.append(f"[{relation['id']}] {relation['source']} {relation['relation']} {relation['target']}{note}")
    return "\n".join(lines)


def check(entity: dict, raw: dict, urls: Dict[str, str]) -> dict:
    """Keeps the sentences whose cites are all the entity's own events, relations or pages, with links to them.

    An event or relation links to its quote; a page ("p:stories/<slug>") links to the page.
    """
    known: Dict[str, dict] = {event["id"]: event for event in entity["timeline"]}
    known.update({relation["id"]: relation for relation in entity["relations"]})
    known.update({f"p:{said['page']}": {"link": urls.get(said["page"], "")} for said in entity["pages_say"]})
    rejected: List[dict] = []

    def sentence(item: dict, part: str):
        cites = [c.strip() for c in item.get("cites", []) if c.strip()]
        if not item.get("text", "").strip() or not cites or any(c not in known for c in cites):
            rejected.append({"part": part, **item})
            return None
        return {"text": item["text"].strip(), "cites": cites, "links": [known[c]["link"] for c in cites]}

    summary = sentence(raw.get("summary", {}), "summary")
    bio = [s for s in (sentence(item, "bio") for item in raw.get("bio", [])) if s]
    status = sentence(raw.get("status", {}), "status")
    return {"summary": summary, "bio": bio, "status": status, "rejected": rejected}


def ingest(data: Path, entity_id: str, raw: dict, model: str) -> dict:
    entity = json.loads((data / "index" / "entity" / f"{entity_id}.json").read_text())
    urls = {page["page"]: page["url"] for page in json.loads((data / "index" / "pages.json").read_text())}
    checked = check(entity, raw, urls)
    document = {
        "id": entity_id,
        "name": entity["name"],
        "model": model,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **checked,
    }
    path = data / "bios" / f"{entity_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")
    return checked
