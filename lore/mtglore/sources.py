"""The story from before magic.wizards.com's Magic Story: card flavor text, wizards.com's old story columns
on the Internet Archive, and MTG Wiki's summaries of the novels and characters.

Each becomes pages in the same shape as data/stories (title, url, story_date, paragraphs), with a `source`
the index carries onto every fact from them:

- "card-text" (data/cards/<set>.json): one page per set, a paragraph per card's flavor text, from Scryfall's
  bulk data. A paragraph keeps its card's name and Scryfall page, which its facts link to.
- "wizards-archive" (data/archive/<slug>.json): Savor the Flavor, Uncharted Realms, Magic Arcana and the other
  story columns of wizards.com from 2002 on, as the Internet Archive saved them.
- "mtg-wiki" (data/wiki/<slug>.json): MTG Wiki's articles on characters, planes, places, storylines and novels.
  The wiki is fan-written, under CC BY-NC-SA 4.0: an app showing it must say so and link back. Its pages are
  not dated, so their facts sort after the dated ones.

The novels themselves are not here: they are not free to copy, and the wiki's summaries are what stands in.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

USER_AGENT = "mooligan-lore/1.0 (+https://data.mooligan.com)"


class Fetcher:
    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._last = 0.0

    def get(self, url: str, attempts: int = 4, accept: str = "*/*") -> bytes:
        for attempt in range(1, attempts + 1):
            wait = self._last + self._delay - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == attempts:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == attempts:
                    raise
            time.sleep(10 * attempt)
        raise AssertionError("unreachable")


def _text(node: Tag) -> str:
    for sup in node.find_all("sup"):
        sup.decompose()
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:120] or "page"


def _save(directory: Path, folder: str, slug: str, page: dict) -> None:
    path = directory / folder / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n")


# --- card flavor text -----------------------------------------------------------------------------------


def card_pages(cards: Iterable[dict]) -> Dict[str, dict]:
    """One page per set: each distinct flavor text of the set's cards, in collector order."""
    sets: Dict[str, dict] = {}
    seen: Dict[str, Set[str]] = defaultdict(set)
    rows: Dict[str, List[Tuple[str, dict]]] = defaultdict(list)
    for card in cards:
        if card.get("lang", "en") != "en" or card.get("layout") in ("art_series", "token", "double_faced_token", "emblem"):
            continue
        faces = card.get("card_faces") or [card]
        for face in faces:
            flavor = (face.get("flavor_text") or "").strip()
            if not flavor or flavor in seen[card["set"]]:
                continue
            seen[card["set"]].add(flavor)
            code = card["set"]
            sets.setdefault(code, {"name": card.get("set_name", code), "released": card.get("released_at", "")})
            number = card.get("collector_number", "")
            rows[code].append((number, {
                "text": re.sub(r"\s+", " ", flavor),
                "scene": 0,
                "card": face.get("name") or card.get("name", ""),
                "url": (card.get("scryfall_uri") or "").split("?")[0],
            }))
    pages = {}
    for code, info in sets.items():
        def order(row):
            digits = re.match(r"\d+", row[0])
            return (int(digits.group()) if digits else 10**6, row[0])
        pages[code] = {
            "kind": "cards",
            "source": "card-text",
            "slug": code,
            "url": f"https://scryfall.com/sets/{code}",
            "title": f"{info['name']}: card flavor text",
            "description": "",
            "published": info["released"],
            "modified": "",
            "story_date": info["released"],
            "authors": [],
            "storyline_nav": None,
            "paragraphs": [paragraph for _, paragraph in sorted(rows[code], key=order)],
        }
    return pages


def scryfall_cards(fetcher: Fetcher) -> Iterator[dict]:
    """Every printing of every card, from Scryfall's default_cards bulk file, streamed a card at a time."""
    listing = json.loads(fetcher.get("https://api.scryfall.com/bulk-data", accept="application/json"))
    item = next(item for item in listing["data"] if item["type"] == "default_cards")
    uri = item.get("jsonl_download_uri") or item.get("download_uri")
    request = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        stream = gzip.GzipFile(fileobj=response) if uri.endswith(".gz") else response
        for line in stream:
            line = line.strip().rstrip(b",")
            if line.startswith(b"{"):
                yield json.loads(line)


def scrape_cards(fetcher: Fetcher, directory: Path) -> dict:
    pages = card_pages(scryfall_cards(fetcher))
    for code, page in pages.items():
        _save(directory, "cards", code, page)
    return {"sets": len(pages), "flavor_texts": sum(len(p["paragraphs"]) for p in pages.values())}


# --- wizards.com on the Internet Archive ----------------------------------------------------------------

# The story columns, by the URL prefix the Internet Archive knows them under.
ARCHIVE_PREFIXES = [
    "wizards.com/magic/magazine/article.aspx?x=mtg/daily/stf/",      # Savor the Flavor, 2008-2014
    "wizards.com/magic/magazine/article.aspx?x=mtg/daily/ur/",       # Uncharted Realms, 2012-2014
    "wizards.com/magic/magazine/article.aspx?x=mtg/daily/arcana/",   # Magic Arcana, 2002-2014
    "wizards.com/magic/magazine/article.aspx?x=mtgcom/arcana/",
    "wizards.com/magic/magazine/article.aspx?x=mtgcom/feature/",     # early features, story ones among them
    "wizards.com/magic/magazine/article.aspx?x=mtg/daily/feature/",
    "magic.wizards.com/en/articles/archive/savor-flavor/",
    "magic.wizards.com/en/articles/archive/uncharted-realms/",
    "magic.wizards.com/en/articles/archive/magic-story/",
]
_STORY_FEATURE = re.compile(r"story|tale|chronicle|planeswalker|guide|legend|lore|fiction|journal|diary|chapter|part", re.I)


def archive_snapshots(fetcher: Fetcher, prefix: str) -> List[Tuple[str, str]]:
    """(timestamp, original url) of the last good snapshot of each page under `prefix`."""
    query = urllib.parse.urlencode({
        "url": prefix + "*", "output": "json", "fl": "original,timestamp", "filter": "statuscode:200",
        "collapse": "urlkey", "limit": "50000",
    })
    rows = json.loads(fetcher.get(f"https://web.archive.org/cdx/search/cdx?{query}", accept="application/json") or b"[]")
    latest: Dict[str, Tuple[str, str]] = {}
    for original, stamp in rows[1:]:
        key = _archive_key(original)
        if key and (key not in latest or stamp > latest[key][0]):
            latest[key] = (stamp, original)
    return sorted(latest.values(), key=lambda row: row[1])


def _archive_key(url: str) -> Optional[str]:
    """What identifies an article across http/https, ports, case and tracking parameters; None for non-articles."""
    url = url.lower().replace(":80/", "/").replace("https://", "http://").replace("http://www.", "http://")
    found = re.search(r"x=(mtg[a-z]*/[a-z/]+/[a-z0-9_\-]+)", url)
    if found:
        return found.group(1)
    found = re.search(r"/en/articles/archive/([a-z\-]+)/([a-z0-9\-]+)/?$", url)
    if found:
        return f"{found.group(1)}/{found.group(2)}"
    return None


def archive_page(html: str, original: str, stamp: str) -> Optional[dict]:
    """An archived article: its title, a date, and the paragraphs of whichever block holds most of the text."""
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup.find_all(["script", "style", "nav", "header", "footer", "form"]):
        junk.decompose()
    best, best_size = None, 0
    for block in soup.find_all(["div", "td", "article", "section"]):
        size = sum(len(p.get_text()) for p in block.find_all("p", recursive=False))
        if size > best_size:
            best, best_size = block, size
    if best is None or best_size < 400:
        return None
    paragraphs, scene = [], 0
    for node in best.find_all(["p", "hr"], recursive=False):
        if node.name == "hr":
            scene += 1
            continue
        text = _text(node)
        if text and not re.search(r"(^|\|)\s*Art by\b", text, re.I):
            paragraphs.append({"text": text, "scene": scene})
    title_tag = soup.find("h1") or soup.find("title")
    title = _text(title_tag) if title_tag else original
    title = re.sub(r"\s*[|:-]\s*(Daily MTG|Magic: The Gathering|MAGIC: THE GATHERING).*$", "", title).strip()
    key = _archive_key(original) or original
    dated = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", key)
    if dated:
        story_date = f"{dated.group(1)}-{int(dated.group(2)):02d}-{int(dated.group(3)):02d}"
    else:
        found = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})\b", soup.get_text(" "))
        story_date = datetime.strptime(" ".join(found.groups()), "%B %d %Y").strftime("%Y-%m-%d") if found else ""
    return {
        "kind": "archive",
        "source": "wizards-archive",
        "slug": _slug(key),
        "url": f"https://web.archive.org/web/{stamp}/{original}",
        "original_url": original,
        "title": title,
        "description": "",
        "published": story_date,
        "modified": "",
        "story_date": story_date,
        "authors": [],
        "storyline_nav": None,
        "paragraphs": paragraphs,
    }


def scrape_archive(fetcher: Fetcher, directory: Path, known_titles: Set[str]) -> dict:
    """Every story column the Archive holds, less what the current site already gave (matched by title)."""
    report = {"listed": 0, "saved": 0, "skipped": 0, "not_story": 0, "failed": []}
    for prefix in ARCHIVE_PREFIXES:
        try:
            snapshots = archive_snapshots(fetcher, prefix)
        except Exception as error:  # noqa: BLE001 - one listing must not stop the rest
            report["failed"].append(f"{prefix}: {error}")
            continue
        log.info("Archive: %d pages under %s", len(snapshots), prefix)
        report["listed"] += len(snapshots)
        for stamp, original in snapshots:
            key = _archive_key(original)
            if not key or "/" not in key:
                continue
            if "feature/" in key and not _STORY_FEATURE.search(key):
                report["not_story"] += 1
                continue
            if (directory / "archive" / f"{_slug(key)}.json").exists():
                report["skipped"] += 1
                continue
            try:
                html = fetcher.get(f"https://web.archive.org/web/{stamp}id_/{original}").decode("utf-8", "replace")
                page = archive_page(html, original, stamp)
            except Exception as error:  # noqa: BLE001
                report["failed"].append(f"{original}: {error}")
                continue
            if page is None or len(page["paragraphs"]) < 3:
                report["not_story"] += 1
                continue
            if page["title"].strip().lower() in known_titles:
                report["skipped"] += 1
                continue
            _save(directory, "archive", page["slug"], page)
            report["saved"] += 1
            if report["saved"] % 50 == 0:
                log.info("Archive: saved %d", report["saved"])
    return report


# --- MTG Wiki -------------------------------------------------------------------------------------------

WIKI_API = "https://mtg.wiki/api.php"
# Where the story lives on the wiki; each is walked down its subcategories.
WIKI_ROOTS = [
    "Category:Characters", "Category:Planes", "Category:Locations", "Category:Storylines",
    "Category:Novels", "Category:Short stories", "Category:Organizations", "Category:Events",
    "Category:Artifacts (storyline)", "Category:Deities",
]
# Sections that are lists, galleries or bookkeeping rather than story.
WIKI_SKIP = re.compile(r"^(contents|gallery|references|notes|see also|external links|in-game references|"
                       r"story appearances|planes visited|card list|cards|trivia|appearances|other appearances|"
                       r"rules|rulings|tokens|reprints|art|artwork|art depiction controversy|flavor text quotes|quotes)$", re.I)


def _wiki(fetcher: Fetcher, **params) -> dict:
    params = {"format": "json", "formatversion": "2", **params}
    return json.loads(fetcher.get(f"{WIKI_API}?{urllib.parse.urlencode(params)}", accept="application/json"))


def wiki_titles(fetcher: Fetcher, roots: Iterable[str], depth: int) -> Dict[str, str]:
    """Every article under the roots, down `depth` levels of subcategories, to the category it was found in."""
    titles: Dict[str, str] = {}
    seen: Set[str] = set()
    frontier = [(root, 0) for root in roots]
    while frontier:
        category, level = frontier.pop(0)
        if category in seen:
            continue
        seen.add(category)
        cont: dict = {}
        while True:
            data = _wiki(fetcher, action="query", list="categorymembers", cmtitle=category, cmlimit="500", cmtype="page|subcat", **cont)
            for member in data.get("query", {}).get("categorymembers", []):
                if member["ns"] == 14 and level < depth:
                    frontier.append((member["title"], level + 1))
                elif member["ns"] == 0:
                    titles.setdefault(member["title"], category)
            if "continue" not in data:
                break
            cont = {"cmcontinue": data["continue"]["cmcontinue"]}
    return titles


def wiki_page(title: str, html: str, category: str) -> dict:
    """An article's story paragraphs, each under the section it is in; infoboxes, tables and lists of cards left out."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup
    paragraphs, section, skip, scene = [], "", False, 0
    for node in root.find_all(["h2", "h3", "h4", "p", "ul", "ol"], recursive=True):
        if node.find_parent(["table", "figure"]) is not None or node.find_parent(class_=re.compile("toc|navbox|infobox")) is not None:
            continue
        if node.name in ("h2", "h3", "h4"):
            heading = re.sub(r"\s*\[\s*edit\b.*$", "", node.get_text(" ", strip=True)).strip()
            if node.name == "h2":
                skip = bool(WIKI_SKIP.match(heading))
            section = heading
            scene += 1
            continue
        if skip or node.find_parent(["ul", "ol"]) is not None:
            continue
        items = [node] if node.name == "p" else node.find_all("li", recursive=False)
        for item in items:
            text = _text(item)
            if len(text) > 20:
                paragraphs.append({"text": text, "scene": scene, "section": section})
    return {
        "kind": "wiki",
        "source": "mtg-wiki",
        "slug": _slug(title),
        "url": "https://mtg.wiki/page/" + urllib.parse.quote(title.replace(" ", "_")),
        "title": title,
        "description": f"MTG Wiki ({category})",
        "license": "CC BY-NC-SA 4.0, MTG Wiki contributors",
        "published": "",
        "modified": "",
        "story_date": "",
        "authors": [],
        "storyline_nav": None,
        "paragraphs": paragraphs,
    }


def scrape_wiki(fetcher: Fetcher, directory: Path, depth: int, limit: Optional[int]) -> dict:
    titles = wiki_titles(fetcher, WIKI_ROOTS, depth)
    (directory / "wiki").mkdir(parents=True, exist_ok=True)
    (directory / "wiki" / "_titles.json").write_text(json.dumps(titles, ensure_ascii=False, indent=1) + "\n")
    log.info("Wiki: %d articles under the story categories", len(titles))
    report = {"listed": len(titles), "saved": 0, "skipped": 0, "short": 0, "failed": []}
    for title, category in sorted(titles.items()):
        if limit is not None and report["saved"] >= limit:
            break
        if (directory / "wiki" / f"{_slug(title)}.json").exists():
            report["skipped"] += 1
            continue
        try:
            data = _wiki(fetcher, action="parse", page=title, prop="text", redirects="1")
            page = wiki_page(title, data["parse"]["text"], category)
        except Exception as error:  # noqa: BLE001
            report["failed"].append(f"{title}: {error}")
            continue
        if sum(len(p["text"].split()) for p in page["paragraphs"]) < 60:
            report["short"] += 1
            continue
        _save(directory, "wiki", page["slug"], page)
        report["saved"] += 1
        if report["saved"] % 100 == 0:
            log.info("Wiki: saved %d", report["saved"])
    return report
