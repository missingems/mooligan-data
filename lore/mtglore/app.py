"""The lore feed the Mooligan app reads, published under lore/app/ on data.mooligan.com.

    python -m mtglore app [--out DIR]

- `cards.json`: each card (by Scryfall oracle_id) to the lore entities it depicts. Only confident matches:
  legendary creatures and planeswalkers by their name, the part before the comma or the planeswalker type; lands and
  planes by the place they're named for; legendary artifacts by name.
- `sets.json`: each set's key characters and places, most important first, from the stories, wiki sections and
  flavor text that set told; and `summaries`, a few sentences of each set's story (data/set_summaries).
- `entities.json`: a summary of every entity that has a page, with the card whose art shows it best and its sets.
- `entities/<id>.md`: the entity's page in playgraph primer markdown, as prose: who they are, then a paragraph per
  set (data/narratives where written, else its events), a `:::cards` block, and the MTG Wiki credit in the front
  matter when the page uses the wiki. The citations stay in the index.
- `sets/<code>/<id>.md`: what happened to one of a set's key entities in that set, and a short timeline.

Needs the index (`build`) and Scryfall's catalog (`scrape-scryfall`, data/scryfall).
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

SCHEMA = 1
MAX_SET_ENTITIES = 12

# Universes Beyond and other crossover sets: their legends are other franchises' characters, whatever their names.
CROSSOVER_SETS = set("""40k ltr ltc who pip acr fin fic pfin tla tle ptla spm spe pspm msh msc hob hoc tmt tmc trk trc rex
afr afc clb hbg sld slp slc pmei spg unf ust und unk unh ugl""".split())

# The set types that tell the story; supplements and promos only reprint it.
STORY_SET_TYPES = {"expansion", "core", "draft_innovation"}

REPRINT_EDITIONS = re.compile(r"^(Unlimited|Revised|Fourth|Fifth|Classic Sixth|Seventh|Eighth|Ninth|Tenth) Edition$")

APP_TYPES = {"character", "creature", "deity", "plane", "location", "faction", "artifact"}
CHARACTER_TYPES = {"character", "creature", "deity"}


def fold(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' -]+", " ", text)).strip()


# --- cards to entities -----------------------------------------------------------------------------------

class Matcher:
    """Finds the entity a card depicts from the index's names."""

    def __init__(self, entities: List[dict], names: Dict[str, List[str]]) -> None:
        self.entities = {e["id"]: e for e in entities}
        self.names = names

    @staticmethod
    def _agrees(query: str, name: str) -> bool:
        """The card's name and the entity's own name share their words: "Teyo" and "Teyo Verada", "Dragonlord
        Kolaghan" and "Kolaghan". An alias alone isn't enough; some aliases in the index are wrong."""
        q, n = fold(query).split(), fold(name).split()
        if not q or not n:
            return False
        starts = n[: len(q)] == q or q[: len(n)] == n
        contained = any(q[i: i + len(n)] == n for i in range(len(q) - len(n) + 1))
        return starts or contained

    def _best(self, name: str, types: Set[str], min_pages: int = 2) -> Optional[str]:
        ids = [i for i in self.names.get(fold(name), [])
               if self.entities.get(i, {}).get("type") in types and self._agrees(name, self.entities[i]["name"])]
        if not ids:
            return None
        ids.sort(key=lambda i: -self.entities[i]["pages"])
        top = self.entities[ids[0]]["pages"]
        second = self.entities[ids[1]]["pages"] if len(ids) > 1 else 0
        # Two entities sharing a name about equally: not confident which.
        if top < min_pages or (second and top < 2 * second):
            return None
        return ids[0]

    def match(self, card: dict) -> List[str]:
        if card["sets"] and all(code in CROSSOVER_SETS for code in card["sets"]):
            return []
        type_line = card["type_line"]
        front = type_line.split("//")[0]
        names = card["faces"] or [card["name"]]
        found: List[str] = []

        def add(entity: Optional[str]) -> None:
            if entity and entity not in found:
                found.append(entity)

        subtypes = front.split("—", 1)[1].strip() if "—" in front else ""
        if front.startswith("Plane ") or front.startswith("Plane—"):
            add(self._best(subtypes, {"plane"}, 1))
            add(self._best(names[0], {"location", "plane"}, 1))
            return found
        legendary = "Legendary" in front
        if "Planeswalker" in front:
            # "Jace, the Mind Sculptor": the planeswalker type names the character; so does the part before the comma.
            add(self._best(names[0].split(",")[0], CHARACTER_TYPES, 3) or self._best(subtypes, CHARACTER_TYPES, 3))
            return found
        for name in names:
            short = name.split(",")[0].strip()
            if legendary and "Creature" in front:
                exact = self._best(name, CHARACTER_TYPES)
                by_short = self._best(short, CHARACTER_TYPES, 3) if short != name else None
                # The character the short name means, unless the full name is its own better-known entity.
                if exact and by_short and exact != by_short:
                    add(max((exact, by_short), key=lambda i: self.entities[i]["pages"]))
                else:
                    add(exact or by_short)
            elif "Land" in front:
                add(self._best(name, {"location", "plane"}))
            elif legendary and "Artifact" in front:
                add(self._best(name, {"artifact"}))
        return found


def map_cards(cards: List[dict], matcher: Matcher) -> Dict[str, List[str]]:
    return {card["oracle_id"]: ids for card in cards if (ids := matcher.match(card))}


# --- sets to entities ------------------------------------------------------------------------------------

def _day(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class SetLinker:
    """Which set a page or event belongs to: the set itself for flavor text, the set code a wiki section is tagged
    with, the set a storyline is named for, or else the set released soonest after a story came out."""

    def __init__(self, sets: List[dict]) -> None:
        # Revised to Tenth Edition reprinted older cards' flavor text; they told no story of their own.
        self.story_sets = [s for s in sets if s["type"] in STORY_SET_TYPES and s["code"] not in CROSSOVER_SETS and s["released"]
                           and not REPRINT_EDITIONS.match(s["name"])]
        self.by_code = {s["code"]: s for s in sets}
        self.story_codes = {s["code"] for s in self.story_sets}
        self.by_name: Dict[str, str] = {}
        for s in sorted(self.story_sets, key=lambda s: s["released"]):
            self.by_name.setdefault(re.sub(r"^the ", "", fold(s["name"])), s["code"])

    def storyline(self, name: str) -> Optional[str]:
        key = re.sub(r"^the ", "", fold(name))
        if not key:
            return None
        if key in self.by_name:
            return self.by_name[key]
        for set_name, code in self.by_name.items():
            if len(key) > 5 and (set_name.startswith(key) or key.startswith(set_name)):
                return code
        return None

    def by_date(self, text: str) -> Optional[str]:
        day = _day(text)
        if not day:
            return None
        best = None
        for s in self.story_sets:
            released = _day(s["released"])
            delta = (released - day).days
            if -45 <= delta <= 120 and (best is None or abs(delta) < abs(best[0])):
                best = (delta, s["code"])
        return best[1] if best else None

    def event(self, event: dict) -> Optional[str]:
        page = event["page"]
        if page.startswith("cards/"):
            code = page.split("/", 1)[1]
            return code if code in self.story_codes else None
        era = (event.get("era") or {}).get("era", "")
        if era in self.by_code:
            return era
        return self.storyline(event.get("storyline", "")) or (self.by_date(event["story_date"]) if event.get("story_date") else None)


def app_type(entity: dict, planeswalkers: Set[str]) -> Optional[str]:
    kind = entity["type"]
    if kind not in APP_TYPES:
        return None
    if kind in CHARACTER_TYPES:
        if entity["id"] in planeswalkers or "planeswalker" in (entity.get("description") or "").lower():
            return "planeswalker"
        return "character"
    return kind


def key_entities(entity_pages: Iterable[dict], linker: SetLinker, types: Dict[str, str]) -> Dict[str, List[dict]]:
    """Per set, the entities it is about: story events count double, flavor-text mentions once."""
    score: Dict[str, Counter] = defaultdict(Counter)
    mentions: Dict[str, Counter] = defaultdict(Counter)
    for page in entity_pages:
        entity = page["id"]
        if entity not in types:
            continue
        for event in page["timeline"]:
            code = linker.event(event)
            if not code:
                continue
            weight = 1 if event["page"].startswith("cards/") else 2
            if event["importance"] == "major":
                weight += 1
            score[code][entity] += weight
            mentions[code][entity] += 1
        for said in page["pages_say"]:
            if said["page"].startswith("cards/"):
                code = said["page"].split("/", 1)[1]
                if code in linker.story_codes:
                    score[code][entity] += 1
                    mentions[code][entity] += 1
    result = {}
    for code, counter in score.items():
        if code not in linker.story_codes:
            continue
        ranked = counter.most_common(MAX_SET_ENTITIES)
        if not ranked:
            continue
        # Main: the four characters the set is most about, and its leading place; the rest support them.
        people = [e for e, _ in ranked if types[e] in ("character", "planeswalker")]
        places = [e for e, _ in ranked if types[e] in ("plane", "location")]
        top_people = {e for e, v in ranked if e in people[:4] and v >= 0.3 * counter[people[0]]}
        main = top_people | set(places[:1])
        result[code] = [{
            "id": entity,
            "type": types[entity],
            "role": "main" if entity in main else "supporting",
            "mentions": mentions[code][entity],
        } for entity, _ in ranked]
    return result


# --- an entity as primer markdown ------------------------------------------------------------------------

WIKI_CREDIT = "Parts adapted from MTG Wiki (https://mtg.wiki) by MTG Wiki contributors, CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)."
# A set's paragraph, where no narrative was written for it, tells at most this many of its events.
FALLBACK_EVENTS = 4
MAX_TIMELINE = 10


def _yaml(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_yaml(v) for v in value) + "]"
    text = str(value)
    return json.dumps(text, ensure_ascii=False) if re.search(r"[:#\[\]{},&*!|>'\"%@`]", text) or not text else text


def _clean(text: str, cards: Set[str] = frozenset()) -> str:
    """Text for a primer, where [[ ]] mean a card: keeps links to the cards named in `cards`, flattens the rest."""
    parts = re.split(r"(\[\[[^\[\]]*\]\])", text)
    return "".join(part if part[2:-2] in cards and part.startswith("[[") else part.replace("[[", "[").replace("]]", "]")
                   for part in parts).strip()


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?\"”’)" else text + "."


# Pages that tell the story itself, rather than look back on it (the wiki) or glimpse it (flavor text).
STORY_PAGES = ("stories/", "profiles/", "archive/")


def _spread(items: List[dict], count: int) -> List[dict]:
    """`count` of `items` spaced evenly from the first to the last, so a story keeps its start and its ending."""
    if count <= 0:
        return []
    if len(items) <= count:
        return items
    if count == 1:
        return items[-1:]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


def _pick(events: List[dict], count: int) -> List[dict]:
    """The `count` events that tell the arc: the story's own events before the wiki's look back, the major ones
    first, spread from beginning to end so the climax stays in; kept in story order."""
    if len(events) <= count:
        return events
    story = [e for e in events if e["page"].startswith(STORY_PAGES)]
    pool = story if len(story) >= count else events
    major = [e for e in pool if e["importance"] == "major"]
    if len(major) >= count:
        chosen = _spread(major, count)
    else:
        minor = [e for e in pool if e["importance"] != "major"]
        chosen = major + _spread(minor, count - len(major))
    order = {id(e): i for i, e in enumerate(events)}
    return sorted(chosen, key=lambda e: order[id(e)])


class Story:
    """An entity's story by set, told from the narratives written for it, else from its events; tracks what it rests on."""

    def __init__(self, entity: dict, narrative: Optional[dict], linker: SetLinker, set_names: Dict[str, str],
                 card_names: Set[str]) -> None:
        self.entity = entity
        self.paragraphs = (narrative or {}).get("sets", {})
        self.linker = linker
        self.set_names = set_names
        self.card_names = card_names
        self.facts: Dict[str, dict] = {e["id"]: e["citation"] for e in entity["timeline"]}
        self.facts.update({r["id"]: r["citation"] for r in entity["relations"]})
        self.facts.update({f"p:{s['page']}": s["citation"] for s in entity["pages_say"]})
        self.used: List[dict] = []

    def _uses(self, cites: Iterable[str]) -> None:
        self.used += [self.facts[c] for c in cites if c in self.facts]

    def prose(self, items: Iterable[dict]) -> str:
        """Cited sentences as plain prose; their sources count towards the credit."""
        items = [i for i in items if i and i.get("text")]
        for item in items:
            self._uses(item.get("cites", []))
        return " ".join(_sentence(_clean(i["text"], self.card_names)) for i in items)

    def groups(self) -> Dict[str, Tuple[Optional[str], List[dict]]]:
        """Heading to (set code, events): one per set, else storyline, era or year, in the order the story reaches them."""
        groups: Dict[str, Tuple[Optional[str], List[dict]]] = {}
        for event in self.entity["timeline"]:
            code = self.linker.event(event)
            name = (self.set_names.get(code, "") if code else "") or event["storyline"] or (event.get("era") or {}).get("label", "") \
                or (event["story_date"][:4] if event["story_date"] else "Other tales")
            groups.setdefault(_clean(name), (code if code in self.set_names else None, []))[1].append(event)
        return groups

    def paragraph(self, code: Optional[str], events: List[dict]) -> str:
        if code and self.paragraphs.get(code):
            return self.prose(self.paragraphs[code])
        picked = _pick(events, FALLBACK_EVENTS)
        self._uses(e["id"] for e in picked)
        return " ".join(_sentence(_clean(e["summary"])) for e in picked)

    def timeline(self, events: List[dict]) -> List[str]:
        picked = _pick(events, MAX_TIMELINE)
        self._uses(e["id"] for e in picked)
        return [f"- {_sentence(_clean(e['summary']))}" for e in picked]

    def credit(self) -> Optional[str]:
        return WIKI_CREDIT if any(not c["official"] for c in self.used) else None


def _front(fields: List[Tuple[str, object]], credit: Optional[str]) -> List[str]:
    lines = ["---", *(f"{key}: {_yaml(value)}" for key, value in fields)]
    if credit:
        lines.append(f"credit: {_yaml(credit)}")
    return lines + ["---", ""]


def entity_markdown(entity: dict, kind: str, planes: List[str], cards: List[dict], set_names: Dict[str, str],
                    linker: SetLinker, narrative: Optional[dict] = None) -> str:
    """The entity's page: who they are, then their story set by set, as prose; the sources stay in the index."""
    card_names = {c["name"] for c in cards}
    story = Story(entity, narrative, linker, set_names, card_names)
    body = ["## Who they are" if kind in ("character", "planeswalker") else "## What it is", ""]
    bio = entity.get("bio") or {}
    if bio.get("summary"):
        body.append(story.prose([bio["summary"], *bio.get("bio", [])]))
        if bio.get("status"):
            body += ["", story.prose([bio["status"]])]
    else:
        body.append(_sentence(_clean(entity.get("description") or entity["name"])))
    groups = story.groups()
    if groups:
        body += ["", "## Story"]
        for heading, (code, events) in groups.items():
            body += ["", f"### {heading}", "", story.paragraph(code, events)]
    if cards:
        body += ["", "## Cards", "", ":::cards"]
        for card in cards:
            first = card["sets"][0] if card["sets"] else ""
            body.append(f"[[{card['name']}]] {set_names.get(first, first.upper())}{', ' + card['first_printed'][:4] if card['first_printed'] else ''}")
        body.append(":::")
    front = [("id", entity["id"]), ("name", entity["name"]), ("type", kind), ("title", entity["name"]), ("planes", planes),
             ("updated", datetime.now(timezone.utc).strftime("%Y-%m-%d"))]
    return "\n".join(_front(front, story.credit()) + body) + "\n"


def set_entity_markdown(entity: dict, code: str, set_name: str, cards: List[dict], set_names: Dict[str, str],
                        linker: SetLinker, narrative: Optional[dict] = None) -> str:
    """What happened to the entity in one set: a paragraph or two, then a short timeline of that set's events."""
    story = Story(entity, narrative, linker, set_names, {c["name"] for c in cards})
    events = [e for e in entity["timeline"] if linker.event(e) == code]
    paragraph = story.paragraph(code, events) if events or story.paragraphs.get(code) else ""
    if not paragraph:
        said = [s for s in entity["pages_say"] if s["page"] == f"cards/{code}"]
        paragraph = _sentence(_clean(said[0]["description"])) if said and said[0].get("description") else \
            f"{entity['name']} appears on the cards of {set_name}."
        story._uses(f"p:{s['page']}" for s in said[:1])
    body = [f"## In {set_name}", "", paragraph]
    lines = story.timeline(events)
    if lines:
        body += ["", "## Timeline", "", *lines]
    short = entity["name"].split(",")[0].split(" ")[0] if entity["type"] in CHARACTER_TYPES else entity["name"]
    front = [("id", entity["id"]), ("set", code), ("name", entity["name"]), ("title", f"{short} in {set_name}")]
    return "\n".join(_front(front, story.credit()) + body) + "\n"


def _planes(entity: dict, entities: Dict[str, dict]) -> List[str]:
    if entity["type"] == "plane":
        return [entity["name"]]
    counts: Counter = Counter()
    for event in entity["timeline"]:
        where = event.get("location") or ""
        if entities.get(where, {}).get("type") == "plane":
            counts[where] += 1
        for other in event["participants"]:
            if entities.get(other, {}).get("type") == "plane":
                counts[other] += 1
    for relation in entity["relations"]:
        if relation["relation"] == "located_in" and relation["source"] == entity["id"] and entities.get(relation["target"], {}).get("type") == "plane":
            counts[relation["target"]] += 3
    return [entities[i]["name"] for i, _ in counts.most_common(5)]


# --- the export ------------------------------------------------------------------------------------------

class Feed:
    """What the feed is cut from: the index, Scryfall's catalog, the cards each entity is on and each set's key entities."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self.index = data / "index"
        self.entities = json.loads((self.index / "entities.json").read_text())
        self.by_id = {e["id"]: e for e in self.entities}
        names = json.loads((self.index / "names.json").read_text())
        cards = json.loads((data / "scryfall" / "cards.json").read_text())
        self.sets = json.loads((data / "scryfall" / "sets.json").read_text())
        self.set_names = {s["code"]: s["name"] for s in self.sets}
        self.released = {s["code"]: s["released"] for s in self.sets}
        self.card_map = map_cards(cards, Matcher(self.entities, names))
        cards_by_id = {c["oracle_id"]: c for c in cards}
        self.entity_cards: Dict[str, List[dict]] = defaultdict(list)
        planeswalkers: Set[str] = set()
        for oracle_id, ids in self.card_map.items():
            card = cards_by_id[oracle_id]
            for entity in ids:
                self.entity_cards[entity].append(card)
                if "Planeswalker" in card["type_line"]:
                    planeswalkers.add(entity)
        for owned in self.entity_cards.values():
            owned.sort(key=lambda c: (c["first_printed"], c["name"]))
        self.types = {e["id"]: t for e in self.entities if (t := app_type(e, planeswalkers))}
        self.linker = SetLinker(self.sets)
        self.with_bio = {path.stem for path in (data / "bios").glob("*.json")}

    @cached_property
    def keyed(self) -> Dict[str, List[dict]]:
        return key_entities(self.pages(), self.linker, self.types)

    @cached_property
    def entity_sets(self) -> Dict[str, Set[str]]:
        owned_sets: Dict[str, Set[str]] = defaultdict(set)
        for code, items in self.keyed.items():
            for item in items:
                owned_sets[item["id"]].add(code)
        story = {s["code"] for s in self.linker.story_sets}
        for entity, owned in self.entity_cards.items():
            for card in owned:
                owned_sets[entity].update(code for code in card["sets"][:1] if code in story)
        return owned_sets

    @cached_property
    def included(self) -> Set[str]:
        return {e["id"] for e in self.entities if e["id"] in self.types and (
            e["id"] in self.with_bio or e["id"] in self.entity_cards or e["id"] in self.entity_sets)}

    def page(self, entity_id: str) -> dict:
        return json.loads((self.index / "entity" / f"{entity_id}.json").read_text())

    def pages(self) -> Iterable[dict]:
        for e in self.entities:
            yield self.page(e["id"])

    def narrative(self, entity_id: str) -> Optional[dict]:
        path = self.data / "narratives" / f"{entity_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def set_summary(self, code: str) -> Optional[dict]:
        path = self.data / "set_summaries" / f"{code}.json"
        return json.loads(path.read_text()) if path.exists() else None


def export(data: Path, out: Path) -> dict:
    feed = Feed(data)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if out.exists():
        shutil.rmtree(out)
    (out / "entities").mkdir(parents=True)

    def write(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    included = feed.included
    write(out / "cards.json", {"schema": SCHEMA, "generated_at": generated, "cards": {k: v for k, v in sorted(feed.card_map.items()) if all(i in included for i in v)}})
    ordered = sorted(feed.keyed.items(), key=lambda kv: feed.released.get(kv[0], ""))
    summaries = {}
    for code, _ in ordered:
        written = feed.set_summary(code)
        if written and written.get("summary"):
            summaries[code] = " ".join(_sentence(_clean(s["text"])) for s in written["summary"])
    write(out / "sets.json", {"schema": SCHEMA, "generated_at": generated, "sets": {
        code: [{"id": i["id"], "name": feed.by_id[i["id"]]["name"], "type": i["type"], "role": i["role"], "mentions": i["mentions"]} for i in items]
        for code, items in ordered}, "summaries": summaries})

    entities = {}
    set_pages = 0
    for page in feed.pages():
        entity = page["id"]
        if entity not in included:
            continue
        owned = feed.entity_cards.get(entity, [])
        bio = page.get("bio") or {}
        summary = (bio.get("summary") or {}).get("text") or page.get("description") or ""
        exact = [c for c in owned if fold(c["name"]) == fold(page["name"])]
        walkers = [c for c in owned if "Planeswalker" in c["type_line"]]
        portrait = (exact or walkers[-1:] or owned[-1:] or [None])[0]
        entities[entity] = {
            "name": page["name"],
            "type": feed.types[entity],
            "summary": summary,
            "portrait_oracle_id": portrait["oracle_id"] if portrait else None,
            "sets": sorted(feed.entity_sets.get(entity, set()), key=lambda c: feed.released.get(c, "")),
        }
        narrative = feed.narrative(entity)
        md = entity_markdown(page, feed.types[entity], _planes(page, feed.by_id), owned, feed.set_names, feed.linker, narrative)
        (out / "entities" / f"{entity}.md").write_text(md)
        for code, items in feed.keyed.items():
            if any(i["id"] == entity for i in items):
                (out / "sets" / code).mkdir(parents=True, exist_ok=True)
                md = set_entity_markdown(page, code, feed.set_names[code], owned, feed.set_names, feed.linker, narrative)
                (out / "sets" / code / f"{entity}.md").write_text(md)
                set_pages += 1
    write(out / "entities.json", {"schema": SCHEMA, "generated_at": generated, "entities": entities})
    narratives = {p.stem for p in (data / "narratives").glob("*.json")}
    report = {
        "cards_mapped": sum(1 for v in feed.card_map.values() if all(i in included for i in v)),
        "entities": len(entities),
        "sets_with_key_entities": len(feed.keyed),
        "set_pages": set_pages,
        "set_summaries": len(summaries),
        "entities_with_bio": sum(1 for i in entities if i in feed.with_bio),
        "entities_with_narrative": sum(1 for i in entities if i in narratives),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report
