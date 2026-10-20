"""The site's data: the index cut down to what a browser loads, as site/dist/data.

    python -m mtglore publish [--out DIR]

- `search.json`: every entity, most pages first, with its name, type, a few aliases and a short description, for the
  search box and for spotting names in a question.
- `e/<id>.json`: one entity as its page shows it: bio, timeline, relations and what each page says of it. Facts carry
  the quote and a link to it; each page they come from is described once, under `sources`.
- `meta.json`: counts, the build date and the credit lines to show.

Only short quotes leave the index: no page text is published.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

# How much of each list an entity page carries, most important first.
MAX_ALIASES_IN_SEARCH = 8
DESCRIPTION_CHARS = 180


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _when(item: dict) -> str:
    era = item.get("era") or {}
    return item.get("story_date") or era.get("date") or ""


def _source(citation: dict) -> dict:
    return {
        "work": citation["work"],
        "series": citation["series"],
        "kind": citation["source"],
        "official": citation["official"],
        "url": citation["url"],
        "date": citation["date"],
        # A page is credited as a whole here, so not by the section the first fact from it happened to be in.
        "credit": re.sub(r', section "[^"]*"', "", citation["text"]),
    }


def _sentence(sentence: dict) -> dict:
    return {"text": sentence["text"], "cites": sentence["cites"]}


def entity_page(entity: dict, names: Dict[str, str]) -> dict:
    sources: Dict[str, dict] = {}
    mentioned = set()

    def cite(item: dict) -> str:
        sources.setdefault(item["page"], _source(item["citation"]))
        return item["page"]

    timeline = []
    for event in entity["timeline"]:
        era = event.get("era") or {}
        timeline.append({
            "id": event["id"],
            "date": event["story_date"],
            "era": era.get("label", "") if not event["story_date"] else "",
            "when": _when(event),
            "storyline": event["storyline"],
            "summary": event["summary"],
            "who": event["participants"],
            "where": event["location"],
            "major": event["importance"] == "major",
            "quote": event["quote"],
            "link": event["link"],
            "page": cite(event),
        })
        mentioned.update(event["participants"])
        if event["location"]:
            mentioned.add(event["location"])
    relations = []
    for relation in entity["relations"]:
        relations.append({
            "id": relation["id"],
            "source": relation["source"],
            "relation": relation["relation"],
            "target": relation["target"],
            "note": relation["note"],
            "when": relation["story_date"],
            "quote": relation["quote"],
            "link": relation["link"],
            "page": cite(relation),
        })
        mentioned.update((relation["source"], relation["target"]))
    said = []
    for item in entity["pages_say"]:
        said.append({
            "page": cite(item),
            "when": item["story_date"],
            "presence": item["presence"],
            "description": item["description"],
        })
    bio = entity.get("bio") or {}
    page = {
        "id": entity["id"],
        "name": entity["name"],
        "type": entity["type"],
        "aliases": entity["aliases"],
        "description": entity["description"],
        "pages": entity["pages"],
        "first_seen": entity["first_seen"],
        "last_seen": entity["last_seen"],
        "bio": {
            "summary": _sentence(bio["summary"]) if bio.get("summary") else None,
            "bio": [_sentence(s) for s in bio.get("bio", [])],
            "status": _sentence(bio["status"]) if bio.get("status") else None,
        } if bio else None,
        "timeline": timeline,
        "relations": relations,
        "said": said,
        "sources": sources,
        "names": {i: names[i] for i in sorted(mentioned) if i in names and i != entity["id"]},
    }
    return page


def publish(data: Path, out: Path) -> dict:
    index = data / "index"
    entities = json.loads((index / "entities.json").read_text())
    names = {e["id"]: e["name"] for e in entities}
    search = [{
        "id": e["id"],
        "name": e["name"],
        "type": e["type"],
        "aliases": [a for a in e["aliases"] if a.lower() != e["name"].lower()][:MAX_ALIASES_IN_SEARCH],
        "pages": e["pages"],
        "description": _short(e["description"], DESCRIPTION_CHARS),
    } for e in entities]

    if out.exists():
        shutil.rmtree(out)
    (out / "e").mkdir(parents=True)

    def write(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    write(out / "search.json", search)
    events = set()
    for e in entities:
        entity = json.loads((index / "entity" / f"{e['id']}.json").read_text())
        events.update(event["id"] for event in entity["timeline"])
        write(out / "e" / f"{e['id']}.json", entity_page(entity, names))
    pages = json.loads((index / "pages.json").read_text())
    meta = {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "entities": len(entities),
        "events": len(events),
        "pages": len(pages),
        "credits": [
            "Magic: The Gathering story text, card flavor text and names are © Wizards of the Coast. Quotes are short excerpts; follow each link to read the original.",
            "MTG Wiki content is by MTG Wiki contributors under CC BY-NC-SA 4.0.",
        ],
    }
    write(out / "meta.json", meta)
    return {"entities": len(entities), "out": str(out)}
