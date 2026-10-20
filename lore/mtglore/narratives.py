"""The app's story prose: a short paragraph per set on each key entity, and a summary of each set's story.

    python -m mtglore narrative-prep DIR          write the input for every key entity and set to DIR
    python -m mtglore narrative-ingest <id> raw.json   check an entity's paragraphs and save them
    python -m mtglore set-summary-ingest <code> raw.json   check a set's summary and save it

Like the bios, the prose is written from the index alone and every sentence cites the events it tells. A sentence
citing nothing, or an event that is not in that set's list, is dropped, and so is a sentence quoting words that
are not in the quotes of the events it cites. The app export (`app`) uses the saved paragraphs in
`entities/<id>.md` and `sets/<code>/<id>.md`, and the summaries in `sets.json`; without one, it tells the set's
events instead.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from .app import Feed, _pick

# Per set, at most this many of an entity's events go into its input; per set summary, this many of the set's.
MAX_ENTITY_EVENTS = 40
MAX_SET_EVENTS = 120
MAX_SENTENCES = 5

ENTITY_INSTRUCTIONS = """Write, for each set below, a short paragraph telling what happened to this entity in \
that set's story, for a Magic fan reading its page in an app. Use only the events listed under that set: do not \
add anything you know from elsewhere, and do not use one set's events in another set's paragraph.

Return JSON: {"sets": {"<set code>": [{"text": "...", "cites": ["<event id>", ...]}, ...], ...}}

- One entry per set code below, 2 to 4 sentences each (1 if the set has a single small event), in story order.
- Write it as a story, not a list of facts: connect the events, say why things happen where the events say so,
  and lead with what matters most. Plain, warm, neutral prose; no headings, lists or markdown.
- cites: the ids in square brackets of the events the sentence tells, from that set's list. Every sentence needs
  at least one.
- A short quote is fine, in double quotes, but only words found in a cited event's quote (shown after "quote:").
- You may name one of the entity's cards as [[Card Name]], exactly as listed, where it reads naturally.
- Name people by name; refer to this entity by name in each paragraph's first sentence."""

SET_INSTRUCTIONS = """Write a 2 to 3 sentence summary of this Magic set's story, for the set's About tab in an \
app. Use only the events below: do not add anything you know from elsewhere.

Return JSON: {"summary": [{"text": "...", "cites": ["<event id>", ...]}, ...]}

- Say where the story happens, who it follows and what is at stake or what happens, in that order of priority.
- A story, not a list: plain, neutral prose; no headings, lists or markdown.
- cites: the ids in square brackets of the events the sentence rests on. Every sentence needs at least one.
- A short quote is fine, in double quotes, but only words found in a cited event's quote."""


def _event_line(event: dict) -> str:
    quote = f' | quote: "{event["quote"]}"' if event.get("quote") and event["citation"]["official"] else ""
    return f"[{event['id']}] {event['summary']}{quote}"


def entity_input(feed: Feed, entity_id: str, codes: List[str]) -> str:
    page = feed.page(entity_id)
    bio = page.get("bio") or {}
    lines = [ENTITY_INSTRUCTIONS, "", "---", "", f"Entity: {page['name']} ({feed.types.get(entity_id, page['type'])})"]
    summary = (bio.get("summary") or {}).get("text") or page.get("description")
    if summary:
        lines.append(f"Who they are: {summary}")
    cards = [c["name"] for c in feed.entity_cards.get(entity_id, [])]
    if cards:
        lines.append("Its cards: " + "; ".join(cards[:30]))
    for code in codes:
        events = [e for e in page["timeline"] if feed.linker.event(e) == code]
        said = [s for s in page["pages_say"] if s["page"] == f"cards/{code}"]
        lines += ["", f"## {feed.set_names[code]} (set code: {code})"]
        lines += [_event_line(e) for e in _pick(events, MAX_ENTITY_EVENTS)]
        for s in said:
            if s.get("description"):
                lines.append(f"[p:{s['page']}] On the set's cards: {s['description']}")
    return "\n".join(lines)


def set_input(feed: Feed, code: str, events: List[dict]) -> str:
    keyed = ", ".join(feed.by_id[i["id"]]["name"] for i in feed.keyed.get(code, [])[:8])
    lines = [SET_INSTRUCTIONS, "", "---", "", f"Set: {feed.set_names[code]} ({code}), released {feed.released.get(code, '?')}"]
    if keyed:
        lines.append(f"Its key characters and places: {keyed}")
    lines += ["", "Its events, in story order:", *[_event_line(e) for e in events]]
    return "\n".join(lines)


def prep(data: Path, out: Path) -> dict:
    """Writes `<id>.txt` for each key entity (its key sets) and `set-<code>.txt` for each set, with lists of both."""
    feed = Feed(data)
    out.mkdir(parents=True, exist_ok=True)
    codes: Dict[str, List[str]] = {}
    for code, items in sorted(feed.keyed.items(), key=lambda kv: feed.released.get(kv[0], "")):
        for item in items:
            codes.setdefault(item["id"], []).append(code)
    for entity_id, mine in codes.items():
        (out / f"{entity_id}.txt").write_text(entity_input(feed, entity_id, mine))
    (out / "entities.txt").write_text("\n".join(codes) + "\n")
    events = json.loads((feed.index / "events.json").read_text())
    by_set: Dict[str, List[dict]] = {}
    for event in events:
        code = feed.linker.event(event)
        if code in feed.keyed:
            by_set.setdefault(code, []).append(event)
    for code, mine in by_set.items():
        story = [e for e in mine if not e["page"].startswith("cards/")]
        chosen = _pick(story, MAX_SET_EVENTS) if len(story) >= 10 else _pick(mine, MAX_SET_EVENTS)
        (out / f"set-{code}.txt").write_text(set_input(feed, code, chosen))
    (out / "sets.txt").write_text("\n".join(sorted(by_set)) + "\n")
    return {"entities": len(codes), "pairs": sum(len(v) for v in codes.values()), "sets": len(by_set)}


def _quotes_hold(text: str, events: List[dict]) -> bool:
    quoted = re.findall(r'"([^"]+)"|“([^”]+)”', text)
    sources = " ".join((e.get("quote") or "") for e in events).lower()
    return all((a or b).strip(" .,!?").lower() in sources for a, b in quoted)


def _cards_hold(text: str, cards: Set[str]) -> bool:
    return all(name in cards for name in re.findall(r"\[\[([^\[\]]*)\]\]", text))


def check_sentences(items: List[dict], known: Dict[str, dict], cards: Set[str], part: str, rejected: List[dict]) -> List[dict]:
    kept = []
    # Past the limit, sentences are refused out loud, so the writer merges them rather than losing an ending.
    rejected += [{"part": part, "reason": "too long", **item} for item in items[MAX_SENTENCES:]]
    for item in items[:MAX_SENTENCES]:
        text = (item.get("text") or "").strip()
        cites = [c.strip() for c in item.get("cites", []) if c.strip()]
        cited = [known[c] for c in cites if c in known]
        if not text or not cites or len(cited) < len(cites):
            rejected.append({"part": part, "reason": "cites", **item})
        elif not _quotes_hold(text, cited):
            rejected.append({"part": part, "reason": "quote", **item})
        elif not _cards_hold(text, cards):
            rejected.append({"part": part, "reason": "card", **item})
        else:
            kept.append({"text": text, "cites": cites})
    return kept


def check_entity(feed: Feed, entity_id: str, raw: dict) -> dict:
    page = feed.page(entity_id)
    cards = {c["name"] for c in feed.entity_cards.get(entity_id, [])}
    rejected: List[dict] = []
    sets = {}
    for code, items in (raw.get("sets") or {}).items():
        known = {e["id"]: e for e in page["timeline"] if feed.linker.event(e) == code}
        known.update({f"p:{s['page']}": {"quote": ""} for s in page["pages_say"] if s["page"] == f"cards/{code}"})
        if code not in feed.set_names:
            rejected.append({"part": code, "reason": "unknown set"})
            continue
        kept = check_sentences(items, known, cards, code, rejected)
        if kept:
            sets[code] = kept
    return {"sets": sets, "rejected": rejected}


def _save(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n")


def ingest_entity(data: Path, entity_id: str, raw: dict, model: str, feed: Optional[Feed] = None) -> dict:
    feed = feed or Feed(data)
    checked = check_entity(feed, entity_id, raw)
    path = data / "narratives" / f"{entity_id}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    _save(path, {
        "id": entity_id,
        "name": feed.by_id[entity_id]["name"],
        "model": model,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # A rewrite of some sets keeps the others.
        "sets": {**old.get("sets", {}), **checked["sets"]},
    })
    return checked


def ingest_set(data: Path, code: str, raw: dict, model: str, feed: Optional[Feed] = None) -> dict:
    feed = feed or Feed(data)
    known = {e["id"]: e for e in json.loads((feed.index / "events.json").read_text()) if feed.linker.event(e) == code}
    rejected: List[dict] = []
    summary = check_sentences(raw.get("summary") or [], known, set(), "summary", rejected)
    _save(data / "set_summaries" / f"{code}.json", {
        "code": code,
        "name": feed.set_names.get(code, code),
        "model": model,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
    })
    return {"summary": summary, "rejected": rejected}
