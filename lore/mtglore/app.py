"""The lore feed the Mooligan app reads, published under lore/app/ on data.mooligan.com.

    python -m mtglore app [--out DIR]

- `cards.json`: each card (by Scryfall oracle_id) to the lore entities it depicts. Only confident matches:
  legendary creatures and planeswalkers by their name, the part before the comma or the planeswalker type; lands and
  planes by the place they're named for; legendary artifacts by name.
- `sets.json`: each set's key characters and places, most important first, from the stories, wiki sections and
  flavor text that set told.
- `entities.json`: a summary of every entity that has a page, with the card whose art shows it best and its sets.
- `entities/<id>.md`: the entity's page in playgraph primer markdown: front matter, `##` sections, `[[Card]]` links
  and a `:::cards` block, with each fact linking to its source.

Needs the index (`build`) and Scryfall's catalog (`scrape-scryfall`, data/scryfall).
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

SCHEMA = 1
MAX_SET_ENTITIES = 12
MAX_STORY_EVENTS = 80
MAX_RELATIONS = 30

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

def _yaml(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_yaml(v) for v in value) + "]"
    text = str(value)
    return json.dumps(text, ensure_ascii=False) if re.search(r"[:#\[\]{},&*!|>'\"%@`]", text) or not text else text


def _cite(citation: dict, link: str) -> str:
    label = "MTG Wiki" if not citation["official"] else "card" if citation["source"] == "card-text" else "story"
    return f"[{label}]({link})" if link else label


def _clean(text: str) -> str:
    # [[ ]] mean cards in a primer; keep stray brackets in story text from being read as card links.
    return text.replace("[[", "[").replace("]]", "]").strip()


def entity_markdown(entity: dict, kind: str, names: Dict[str, str], planes: List[str], cards: List[dict],
                    set_names: Dict[str, str], linker: SetLinker) -> str:
    facts: Dict[str, Tuple[dict, str]] = {}
    for event in entity["timeline"]:
        facts[event["id"]] = (event["citation"], event["link"])
    for relation in entity["relations"]:
        facts[relation["id"]] = (relation["citation"], relation["link"])
    for said in entity["pages_say"]:
        facts[f"p:{said['page']}"] = (said["citation"], said["citation"]["url"])
    used: Dict[str, dict] = {}

    def sentence(item: dict) -> str:
        cites = [facts[c] for c in item["cites"] if c in facts]
        if not cites:
            return _clean(item["text"])
        # An official source first, where the sentence has one.
        citation, link = sorted(cites, key=lambda c: not c[0]["official"])[0]
        used[citation["url"]] = citation
        return f"{_clean(item['text'])} ({_cite(citation, link)})"

    lines = [
        "---",
        f"id: {_yaml(entity['id'])}",
        f"name: {_yaml(entity['name'])}",
        f"type: {kind}",
        f"title: {_yaml(entity['name'])}",
        f"planes: {_yaml(planes)}",
        f"updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "---",
        "",
        "## Who they are" if kind in ("character", "planeswalker") else "## What it is",
        "",
    ]
    bio = entity.get("bio") or {}
    if bio.get("summary"):
        lines.append(" ".join(sentence(s) for s in [bio["summary"], *bio.get("bio", [])]))
        if bio.get("status"):
            lines += ["", f"**Where things stand:** {sentence(bio['status'])}"]
    else:
        lines.append(_clean(entity.get("description") or entity["name"]))

    events = entity["timeline"]
    if len(events) > MAX_STORY_EVENTS:
        major = [e for e in events if e["importance"] == "major"]
        events = major if len(major) >= MAX_STORY_EVENTS // 2 else events
    if len(events) > MAX_STORY_EVENTS:
        step = len(events) / MAX_STORY_EVENTS
        events = [events[int(i * step)] for i in range(MAX_STORY_EVENTS)]
    if events:
        # One heading per set (or storyline, or era, for what no set told), in the order the story reaches them.
        groups: Dict[str, List[dict]] = {}
        for event in events:
            code = linker.event(event)
            group = (set_names.get(code, "") if code else "") or event["storyline"] or (event.get("era") or {}).get("label", "") or (event["story_date"][:4] if event["story_date"] else "Other tales")
            groups.setdefault(group, []).append(event)
        lines += ["", "## Story"]
        for group, items in groups.items():
            lines += ["", f"### {_clean(group)}", ""]
            for event in items:
                used[event["citation"]["url"]] = event["citation"]
                lines.append(f"- {_clean(event['summary'])} ({_cite(event['citation'], event['link'])})")

    relations = []
    seen = set()
    for relation in sorted(entity["relations"], key=lambda r: not r["citation"]["official"]):
        other = relation["target"] if relation["source"] == entity["id"] else relation["source"]
        key = (relation["relation"], other)
        if key in seen or other not in names:
            continue
        seen.add(key)
        relations.append((relation, other))
    if relations:
        lines += ["", "## Relationships", ""]
        for relation, other in relations[:MAX_RELATIONS]:
            outgoing = relation["source"] == entity["id"]
            label = relation["relation"].replace("_", " ")
            text = f"{entity['name']} {label} {names[other]}" if outgoing else f"{names[other]} {label} {entity['name']}"
            note = f": {_clean(relation['note'])}" if relation["note"] else ""
            used[relation["citation"]["url"]] = relation["citation"]
            lines.append(f"- {text}{note} ({_cite(relation['citation'], relation['link'])})")

    if cards:
        lines += ["", "## Cards", "", ":::cards"]
        for card in cards:
            first = card["sets"][0] if card["sets"] else ""
            lines.append(f"[[{card['name']}]] {set_names.get(first, first.upper())}{', ' + card['first_printed'][:4] if card['first_printed'] else ''}")
        lines.append(":::")

    official = sorted({c["text"] for c in used.values() if c["official"]})
    wiki = sorted({c["text"] for c in used.values() if not c["official"]})
    lines += ["", "## Sources", ""]
    lines += [f"- {_clean(text)}" for text in official]
    if wiki:
        lines += ["", "From MTG Wiki, by MTG Wiki contributors under CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/):", ""]
        lines += [f"- {_clean(text)}" for text in wiki]
    lines += ["", "Magic: The Gathering story text, card names and flavor text are © Wizards of the Coast. This page summarises them and links to each source."]
    return "\n".join(lines) + "\n"


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

def export(data: Path, out: Path) -> dict:
    index = data / "index"
    entities = json.loads((index / "entities.json").read_text())
    by_id = {e["id"]: e for e in entities}
    names = json.loads((index / "names.json").read_text())
    cards = json.loads((data / "scryfall" / "cards.json").read_text())
    sets = json.loads((data / "scryfall" / "sets.json").read_text())
    set_names = {s["code"]: s["name"] for s in sets}
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    matcher = Matcher(entities, names)
    card_map = map_cards(cards, matcher)
    cards_by_id = {c["oracle_id"]: c for c in cards}
    entity_cards: Dict[str, List[dict]] = defaultdict(list)
    planeswalkers: Set[str] = set()
    for oracle_id, ids in card_map.items():
        card = cards_by_id[oracle_id]
        for entity in ids:
            entity_cards[entity].append(card)
            if "Planeswalker" in card["type_line"]:
                planeswalkers.add(entity)
    types = {e["id"]: t for e in entities if (t := app_type(e, planeswalkers))}

    def pages():
        for e in entities:
            yield json.loads((index / "entity" / f"{e['id']}.json").read_text())

    linker = SetLinker(sets)
    keyed = key_entities(pages(), linker, types)
    entity_sets: Dict[str, Set[str]] = defaultdict(set)
    for code, items in keyed.items():
        for item in items:
            entity_sets[item["id"]].add(code)
    for entity, owned in entity_cards.items():
        for card in owned:
            story = {s["code"] for s in linker.story_sets}
            entity_sets[entity].update(code for code in card["sets"][:1] if code in story)

    with_bio = {path.stem for path in (data / "bios").glob("*.json")}
    included = {e["id"] for e in entities if e["id"] in types and (e["id"] in with_bio or e["id"] in entity_cards or e["id"] in entity_sets)}

    if out.exists():
        shutil.rmtree(out)
    (out / "entities").mkdir(parents=True)

    def write(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    write(out / "cards.json", {"schema": SCHEMA, "generated_at": generated, "cards": {k: v for k, v in sorted(card_map.items()) if all(i in included for i in v)}})
    released = {s["code"]: s["released"] for s in sets}
    write(out / "sets.json", {"schema": SCHEMA, "generated_at": generated, "sets": {
        code: [{"id": i["id"], "name": by_id[i["id"]]["name"], "type": i["type"], "role": i["role"], "mentions": i["mentions"]} for i in items]
        for code, items in sorted(keyed.items(), key=lambda kv: released.get(kv[0], ""))}})

    summaries = {}
    all_names = {e["id"]: e["name"] for e in entities}
    for page in pages():
        if page["id"] not in included:
            continue
        owned = sorted(entity_cards.get(page["id"], []), key=lambda c: (c["first_printed"], c["name"]))
        bio = page.get("bio") or {}
        summary = (bio.get("summary") or {}).get("text") or page.get("description") or ""
        exact = [c for c in owned if fold(c["name"]) == fold(page["name"])]
        walkers = [c for c in owned if "Planeswalker" in c["type_line"]]
        portrait = (exact or walkers[-1:] or owned[-1:] or [None])[0]
        summaries[page["id"]] = {
            "name": page["name"],
            "type": types[page["id"]],
            "summary": summary,
            "portrait_oracle_id": portrait["oracle_id"] if portrait else None,
            "sets": sorted(entity_sets.get(page["id"], set()), key=lambda c: released.get(c, "")),
        }
        md = entity_markdown(page, types[page["id"]], all_names, _planes(page, by_id), owned, set_names, linker)
        (out / "entities" / f"{page['id']}.md").write_text(md)
    write(out / "entities.json", {"schema": SCHEMA, "generated_at": generated, "entities": summaries})
    report = {
        "cards_mapped": sum(1 for v in card_map.values() if all(i in included for i in v)),
        "entities": len(summaries),
        "sets_with_key_entities": len(keyed),
        "entities_with_bio": sum(1 for i in summaries if i in with_bio),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report
