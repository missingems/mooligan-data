"""Joins the per-page extractions into one index under data/index.

The same character turns up under different names on different pages ("Jace", "Jace Beleren", "the Mind
Sculptor"), so names are first grouped into entities:

- every name a page lists for an entity, and each alias it gives, is the same entity, unless that alias is
  claimed by more than one name (two characters called "Father" stay apart);
- data/merges.json, kept by hand, then joins (`same`) or keeps apart (`different`) what the rules got wrong.

Then each event and relation is pointed at entity ids and put in story order: by the day a page first came
out, then by its place in its storyline's chapter list.

Written:

- entities.json     every entity: id, name, type, aliases, description, how many pages it is on
- entity/<id>.json  one entity with its timeline (events in story order), relations and what each page says of it
- events.json, relations.json, storylines.json, pages.json
- names.json        each name and alias, folded, to the entity ids it may mean, for lookups
- review.json       what to check by hand: shared aliases, entities typed differently on different pages
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote as url_quote

from .extract import fold

log = logging.getLogger(__name__)


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "entity"


def text_fragment(url: str, quote: str) -> str:
    """The page's URL with a #:~:text= fragment, so a browser scrolls to the quote and highlights it."""

    def encode(text: str) -> str:
        return url_quote(text, safe="").replace("-", "%2D")

    words = quote.split()
    if len(words) <= 8:
        return f"{url}#:~:text={encode(quote)}"
    return f"{url}#:~:text={encode(' '.join(words[:4]))},{encode(' '.join(words[-4:]))}"


_PRONOUNS = {"he", "him", "his", "she", "her", "hers", "they", "them", "it", "you", "i", "me", "we", "us"}

# Words that make a name a different version of someone ("Phyrexian Nissa"), not a longer name for them.
_VARIANT_WORDS = {"phyrexian", "compleated", "young", "younger", "old", "elder", "past", "future", "ghost", "spirit", "alternate"}


def _shortening(alias: str, name: str) -> bool:
    """Whether `alias` is `name` with words left out: "jace" of "jace beleren", but not "nissa" of "phyrexian nissa".

    An alias only joins two entities that each have pages of their own when it is this kind of shortening;
    otherwise "Ashiok", given once as an alias of Jace (whom Ashiok was disguised as), would make them one.
    """
    alias_words, name_words = alias.split(), name.split()
    return bool(alias_words) and set(alias_words) < set(name_words) and not (set(name_words) - set(alias_words)) & _VARIANT_WORDS


class _Groups:
    """Union-find over folded names, which refuses to join two groups `apart` says differ."""

    def __init__(self, apart: Iterable[Tuple[str, str]]) -> None:
        self._parent: Dict[str, str] = {}
        self._members: Dict[str, Set[str]] = {}
        self._apart = {frozenset(pair) for pair in apart}

    def add(self, name: str) -> None:
        if name not in self._parent:
            self._parent[name] = name
            self._members[name] = {name}

    def find(self, name: str) -> str:
        self.add(name)
        while self._parent[name] != name:
            self._parent[name] = self._parent[self._parent[name]]
            name = self._parent[name]
        return name

    def join(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if any(frozenset((x, y)) in self._apart for x in self._members[ra] for y in self._members[rb]):
            return False
        if len(self._members[ra]) < len(self._members[rb]):
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._members[ra] |= self._members.pop(rb)
        return True

    def groups(self) -> Dict[str, Set[str]]:
        return {root: members for root, members in self._members.items()}


def _page_order(extractions: List[dict], pages: Dict[str, dict]) -> List[dict]:
    """The extractions in story order: first-publication day, then place in the storyline's chapter list."""

    def key(extraction: dict) -> tuple:
        page = pages.get(extraction["page"], {})
        nav = page.get("storyline_nav") or {}
        chapters = nav.get("chapters") or []
        position = chapters.index(page["url"]) if page.get("url") in chapters else 0
        # A profile has no date: it sorts after every story, as the latest word on who someone is.
        return (extraction.get("story_date") or "9999", nav.get("title", ""), position, extraction["title"])

    return sorted(extractions, key=key)


def duplicate_pages(pages: Dict[str, dict]) -> Set[str]:
    """Pages the site has twice ("krenko-mob-boss-2012-07-16" and "-07-18"; "oracle-ephara-2014-03-19" and "-0").

    Two stories are the same when their titles match and every paragraph after the first does (the first is
    where a copy differs, in a split drop cap), or when one is the other's slug plus "-0" under the same title.
    The one kept is the first by slug, a "-0" copy sorting last.
    """
    by_title: Dict[tuple, List[str]] = defaultdict(list)
    for key, page in pages.items():
        if page.get("kind") == "story":
            by_title[(page["title"].strip().lower(), tuple(p["text"] for p in page["paragraphs"][1:]))].append(key)
    dropped: Set[str] = set()
    for keys in by_title.values():
        keys.sort(key=lambda k: (k.endswith("-0"), k))
        dropped.update(keys[1:])
    # A "-0" copy with the same title as its original is a re-upload, even with a word changed.
    for key, page in pages.items():
        original = pages.get(key[:-2]) if key.endswith("-0") else None
        if original and original["title"].strip().lower() == page["title"].strip().lower():
            dropped.add(key)
    return dropped


def build(directory: Path) -> dict:
    pages = {}
    for folder in ("stories", "profiles"):
        for path in (directory / folder).glob("*.json"):
            pages[f"{folder}/{path.stem}"] = json.loads(path.read_text())
    extractions = [json.loads(path.read_text()) for path in sorted((directory / "extracted").glob("*/*.json"))]
    duplicates = duplicate_pages(pages)
    extractions = _page_order([e for e in extractions if e["page"] not in duplicates], pages)
    merges = json.loads((directory / "merges.json").read_text()) if (directory / "merges.json").exists() else {}
    storyline_names = merges.get("storylines", {})

    # 1. Group names into entities.
    groups = _Groups((fold(a), fold(b)) for a, b in merges.get("different", []))
    alias_owners: Dict[str, Set[str]] = defaultdict(set)
    for extraction in extractions:
        for entity in extraction["entities"]:
            groups.add(fold(entity["name"]))
            for alias in entity["aliases"]:
                alias_owners[fold(alias)].add(fold(entity["name"]))
    shared = {alias: owners for alias, owners in alias_owners.items() if len(owners) > 1}
    names = set(groups.groups())
    name_pages = Counter(fold(entity["name"]) for extraction in extractions for entity in extraction["entities"])
    for alias, owners in alias_owners.items():
        owner = next(iter(owners))
        if len(owners) == 1 and (alias not in names or _shortening(alias, owner)):
            groups.join(owner, alias)
        elif len(owners) > 1 and alias in names:
            # "Jace" is short for "Jace Beleren" and for "Jace, Reality Sculptor": it goes with the one on most pages.
            longer = [o for o in owners if _shortening(alias, o)]
            if longer:
                groups.join(max(longer, key=lambda o: (name_pages[o], o)), alias)
    for same in merges.get("same", []):
        for other in same[1:]:
            if not groups.join(fold(same[0]), fold(other)):
                log.warning("merges.json: %s and %s are also listed as different", same[0], other)

    # 2. Name, type and id for each group.
    name_counts: Dict[str, Counter] = defaultdict(Counter)
    type_counts: Dict[str, Counter] = defaultdict(Counter)
    spellings: Dict[str, Counter] = defaultdict(Counter)
    for extraction in extractions:
        for entity in extraction["entities"]:
            root = groups.find(fold(entity["name"]))
            name_counts[root][entity["name"]] += 1
            type_counts[root][entity["type"]] += 1
            for alias in entity["aliases"]:
                spellings[root][alias] += 1
    renames = {fold(old): new for old, new in merges.get("rename", {}).items()}
    entity_of: Dict[str, str] = {}
    entities: Dict[str, dict] = {}
    used: Set[str] = set()
    for root in sorted(name_counts, key=lambda r: -sum(name_counts[r].values())):
        counted = name_counts[root]
        name = max(counted, key=lambda n: (counted[n], len(n), n))
        name = next((renames[member] for member in groups.groups()[root] if member in renames), name)
        entity_id = slugify(name)
        suffix = 2
        while entity_id in used:
            entity_id, suffix = f"{slugify(name)}-{suffix}", suffix + 1
        used.add(entity_id)
        # Not another entity's own name (a page that called Ashiok "Jace" in disguise), and not a pronoun.
        aliases = sorted({
            n for n in list(counted) + list(spellings[root])
            if fold(n) != fold(name) and fold(n) not in _PRONOUNS and (fold(n) not in names or groups.find(fold(n)) == root)
        }, key=str.lower)
        entities[entity_id] = {
            "id": entity_id,
            "name": name,
            "type": type_counts[root].most_common(1)[0][0],
            "aliases": aliases,
            "description": "",
            "pages": 0,
            "first_seen": None,
            "last_seen": None,
        }
        for member in groups.groups()[root]:
            entity_of[member] = entity_id

    def resolve(name: str) -> Optional[str]:
        return entity_of.get(groups.find(fold(name))) if name else None

    # 3. Events, relations and what each page says of each entity, in story order.
    events, relations, storylines = [], [], {}
    said: Dict[str, List[dict]] = defaultdict(list)
    page_index = []
    for order, extraction in enumerate(extractions):
        page = pages.get(extraction["page"], {})
        nav = page.get("storyline_nav") or {}
        storyline = nav.get("title") or extraction.get("storyline") or ""
        storyline = storyline_names.get(storyline, storyline)
        slug = extraction["page"].split("/", 1)[1]
        page_index.append({
            "page": extraction["page"],
            "order": order,
            "title": extraction["title"],
            "url": extraction["url"],
            "kind": page.get("kind", ""),
            "story_date": extraction.get("story_date", ""),
            "storyline": storyline,
        })
        if storyline:
            storylines.setdefault(storyline, {"name": storyline, "pages": []})["pages"].append(extraction["page"])
        seen = set()
        for entity in extraction["entities"]:
            entity_id = resolve(entity["name"])
            if entity_id in seen:
                continue
            seen.add(entity_id)
            said[entity_id].append({
                "page": extraction["page"],
                "order": order,
                "story_date": extraction.get("story_date", ""),
                "presence": entity["presence"],
                "description": entity["description"],
            })
        common = {"page": extraction["page"], "order": order, "story_date": extraction.get("story_date", ""), "storyline": storyline}
        for number, event in enumerate(extraction["events"]):
            events.append({
                "id": f"{slug}-e{number}",
                "summary": event["summary"],
                "participants": list(dict.fromkeys(filter(None, (resolve(n) for n in event["participants"])))),
                "location": resolve(event["location"]),
                "importance": event["importance"],
                **common,
                "paragraph": event["paragraph"],
                "quote": event["quote"],
                "link": text_fragment(extraction["url"], event["quote"]),
            })
        for number, relation in enumerate(extraction["relations"]):
            relations.append({
                "id": f"{slug}-r{number}",
                "source": resolve(relation["source"]),
                "relation": relation["relation"],
                "target": resolve(relation["target"]),
                "note": relation["note"],
                **common,
                "paragraph": relation["paragraph"],
                "quote": relation["quote"],
                "link": text_fragment(extraction["url"], relation["quote"]),
            })

    for entity_id, statements in said.items():
        entity = entities[entity_id]
        dated = [s for s in statements if s["story_date"]]
        entity["pages"] = len(statements)
        entity["first_seen"] = dated[0]["story_date"] if dated else None
        entity["last_seen"] = dated[-1]["story_date"] if dated else None
        # A profile page is written to say who someone is; else the latest page where they appear.
        own_names = {fold(n) for n in [entity["name"], *entity["aliases"]]}
        profile = next((s for s in statements if s["page"].startswith("profiles/")
                        and fold(pages.get(s["page"], {}).get("title", "").split("|")[0]) in own_names), None)
        appears = [s for s in statements if s["presence"] == "appears"] or statements
        entity["description"] = (profile or appears[-1])["description"]

    # 4. Write it all.
    out = directory / "index"
    if out.exists():
        shutil.rmtree(out)
    (out / "entity").mkdir(parents=True)

    def write(path: Path, data) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    by_entity: Dict[str, Dict[str, list]] = defaultdict(lambda: {"events": [], "relations": []})
    for event in events:
        # A place's timeline is what happens there, as a character's is what they take part in.
        for entity_id in dict.fromkeys([*event["participants"], *([event["location"]] if event["location"] else [])]):
            by_entity[entity_id]["events"].append(event)
    for relation in relations:
        for entity_id in (relation["source"], relation["target"]):
            by_entity[entity_id]["relations"].append(relation)
    for entity_id, entity in entities.items():
        # A bio written for the entity (see bios.py) gives it a better description than any one page.
        bio_path = directory / "bios" / f"{entity_id}.json"
        bio = json.loads(bio_path.read_text()) if bio_path.exists() else None
        if bio and bio.get("summary"):
            entity["description"] = bio["summary"]["text"]
        write(out / "entity" / f"{entity_id}.json", {
            **entity,
            "bio": {k: bio[k] for k in ("summary", "bio", "status")} if bio else None,
            "timeline": by_entity[entity_id]["events"],
            "relations": by_entity[entity_id]["relations"],
            "pages_say": said[entity_id],
        })
    ranked = sorted(entities.values(), key=lambda e: (-e["pages"], e["name"]))
    names: Dict[str, Set[str]] = defaultdict(set)
    for entity in entities.values():
        for name in [entity["name"], *entity["aliases"]]:
            names[fold(name)].add(entity["id"])
    for alias, owners in shared.items():
        for owner in owners:
            names[alias].add(entity_of[groups.find(owner)])
    write(out / "entities.json", ranked)
    write(out / "events.json", events)
    write(out / "relations.json", relations)
    write(out / "storylines.json", list(storylines.values()))
    write(out / "pages.json", page_index)
    write(out / "names.json", {name: sorted(ids) for name, ids in sorted(names.items())})
    mixed = [
        {"id": entity_of[root_member], "types": dict(type_counts[root])}
        for root, root_member in ((r, next(iter(m))) for r, m in groups.groups().items() if r in type_counts)
        if len(type_counts[root]) > 1
    ]
    write(out / "review.json", {
        "shared_aliases": {alias: sorted(entity_of[groups.find(o)] for o in owners) for alias, owners in sorted(shared.items())},
        "mixed_types": mixed,
        "rejected": sum(len(e.get("rejected", [])) for e in extractions),
        "duplicate_pages": sorted(duplicates),
    })
    report = {"pages": len(extractions), "entities": len(entities), "events": len(events), "relations": len(relations), "storylines": len(storylines)}
    log.info("Index: %s", report)
    return report
