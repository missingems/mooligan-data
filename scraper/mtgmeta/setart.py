"""sets/art.json: Wizards' official art for each set, keyed by Scryfall set code, for a hero banner on the set page.

Wizards has no list of set art, so it is read from the pages they publish for each set. Their sitemap lists every
product page (`/en/products/{set}`), every product's card image gallery (`/en/products/{set}/card-image-gallery`) and the
older sets' galleries (`/en/news/card-image-gallery/{set}`). A page is matched to a Scryfall set by the set's name (or a
short alias) against the page's last path segment, and only matching pages are fetched, one `og:image` each: the social
image Wizards sets for the page, which is the set's promo art on a product page and a piece of the set's art on a gallery.

For a set, a gallery's image beats a product page's, because a product page's is a marketing poster with the set's logo and
text on it and a gallery's is clean key art. Among galleries the larger image (by pixels) wins, a product's gallery on a tie
before an older gallery. A product page's image is the fallback for a set with no gallery image. A set with no page, or none
with a usable image, is left out, and the app falls back to a card art crop.

Pages are cached in `state/set-art.json` by URL with the sitemap's `lastmod`, so a page is fetched again only when the
sitemap says it changed, and the file is rebuilt from the cache on every run. See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
import re
import struct
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "sets/art.json"
STATE_PATH = "state/set-art.json"
SITEMAP_URL = "https://magic.wizards.com/en/sitemap.xml"
SETS_URL = "https://api.scryfall.com/sets"
SOURCE = "wizards"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
DELAY = 0.5
FIRST_RELEASE = "2015-01-01"
SET_TYPES = {"expansion", "core", "masters", "draft_innovation", "commander", "funny"}
# A banner is landscape: an image has to be at least this much wider than tall.
MIN_ASPECT = 1.2
# Enough of a file for its size, which a JPEG puts after its metadata.
HEAD_BYTES = 131072
# Images Wizards sets on pages that are not about a set.
GENERIC_IMAGES = ("error-pages", "ShareImage", "default_wizards", "Meta_Archive", "Wizards_Icon", "wizards_icon")
STOPWORDS = {"of", "the", "a", "an", "and", "in", "for", "to"}
# What a gallery's slug adds to the set's name.
SLUG_NOISE = {"card", "image", "gallery", "cig", "en", "edition"}
DATE_SUFFIX = re.compile(r"-\d{4}-\d{2}-\d{2}$")
# Pages that carry a set under a name that is not its Scryfall name.
ALIASES = {
    "afr": ["forgotten-realms"],
    "stx": ["strixhaven"],
    "spm": ["spider-man"],
    "mid": ["midnight-hunt"],
    "vow": ["crimson-vow"],
    "ltr": ["the-lord-of-the-rings-tales-of-middle-earth"],
}
PRODUCT, PRODUCT_GALLERY, GALLERY = 0, 1, 2


class Response(NamedTuple):
    content_type: str
    body: bytes


Fetch = Callable[[str, Optional[int]], Response]


def fetch(url: str, last_byte: Optional[int] = None, user_agent: str = USER_AGENT) -> Response:
    headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if last_byte is not None:
        headers["Range"] = f"bytes=0-{last_byte}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return Response(response.headers.get("Content-Type", ""), response.read())


class Paced:
    """A fetch that leaves `delay` seconds between one request and the next."""

    def __init__(self, inner: Fetch = fetch, delay: float = DELAY, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.inner, self.delay, self.sleep, self.clock = inner, delay, sleep, clock
        self.last: Optional[float] = None

    def __call__(self, url: str, last_byte: Optional[int] = None) -> Response:
        if self.last is not None:
            wait = self.delay - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.inner(url, last_byte)
        finally:
            self.last = self.clock()


class Page(NamedTuple):
    url: str
    kind: int
    slug: str
    lastmod: Optional[str]


def squash(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def name_keys(words: List[str]) -> set:
    """A name's words squashed together, with and without the little words Wizards drops from a slug ("hour-devastation")."""
    return {squash("".join(words)), squash("".join(word for word in words if word not in STOPWORDS))} - {""}


def set_keys(code: str, name: str) -> set:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("'", "").replace("’", "")
    words = re.findall(r"[a-z0-9]+", ascii_name)
    keys = name_keys(words)
    if words and words[0] == "the":
        keys |= name_keys(words[1:])
    for alias in ALIASES.get(code, []):
        keys |= name_keys(alias.split("-"))
    return keys


def page_keys(page: Page) -> set:
    slug = DATE_SUFFIX.sub("", page.slug.lower().replace("'", ""))
    words = [word for word in slug.split("-") if word]
    keys = name_keys(words)
    trimmed = [word for word in words if word not in SLUG_NOISE]
    keys |= name_keys(trimmed)
    keys |= {key[: -len("edition")] for key in keys if key.endswith("edition") and key != "edition"}
    # "frf-cig-en": the set's code and a name's worth of nothing.
    if len(words) > 1 and not trimmed[1:]:
        keys.add("code:" + words[0])
    return keys


def parse_sitemap(xml: bytes) -> List[Page]:
    """The product and card image gallery pages in Wizards' sitemap, with each one's `lastmod`."""
    pages = []
    for node in ET.fromstring(xml):
        loc = next((child.text for child in node if child.tag.endswith("loc")), None)
        lastmod = next((child.text for child in node if child.tag.endswith("lastmod")), None)
        if not loc:
            continue
        parts = [part for part in urlparse(loc.strip()).path.split("/") if part]
        if len(parts) < 3 or parts[0] != "en":
            continue
        if parts[1] == "products":
            if parts[-1] == "card-image-gallery" and len(parts) >= 4:
                kind, slug = PRODUCT_GALLERY, parts[-2]
            elif parts[-1] != "card-image-gallery":
                kind, slug = PRODUCT, parts[-1]
            else:
                continue
        elif parts[1] == "news" and len(parts) == 4 and parts[2] == "card-image-gallery":
            kind, slug = GALLERY, parts[3]
        else:
            continue
        pages.append(Page(loc.strip(), kind, slug, lastmod.strip() if lastmod else None))
    return pages


class SetInfo(NamedTuple):
    code: str
    name: str
    released_at: str


def parse_sets(document: dict) -> List[SetInfo]:
    """Scryfall's sets that have art to show: the paper expansions, cores and the like from 2015 on, and the ones yet to come."""
    sets = []
    for entry in document.get("data", []):
        code, name, released = entry.get("code"), entry.get("name"), entry.get("released_at") or ""
        if not code or not name or entry.get("digital") or entry.get("set_type") not in SET_TYPES or released < FIRST_RELEASE:
            continue
        sets.append(SetInfo(code.lower(), name, released))
    return sets


def pages_by_set(sets: Iterable[SetInfo], pages: Iterable[Page]) -> Dict[str, List[Page]]:
    """Each set's pages: those whose slug reads as its name or alias, or as its code with nothing else."""
    keyed = [(page, page_keys(page)) for page in pages]
    found: Dict[str, List[Page]] = {}
    for info in sets:
        keys = set_keys(info.code, info.name)
        matches = [page for page, page_set in keyed if keys & page_set or f"code:{info.code}" in page_set]
        if matches:
            found[info.code] = matches
    return found


def og_image(html: bytes, page_url: str) -> Optional[str]:
    """The page's social image as an absolute URL, or None when it has none or it is one Wizards uses on any page."""
    soup = BeautifulSoup(html, "html.parser")
    for attribute, value in (("property", "og:image"), ("name", "twitter:image"), ("property", "twitter:image")):
        tag = soup.find("meta", attrs={attribute: value})
        content = (tag.get("content") or "").strip() if tag else ""
        if content:
            url = urljoin(page_url, content)
            if urlparse(url).scheme in ("http", "https") and not any(generic in url for generic in GENERIC_IMAGES):
                return url
    return None


def image_size(data: bytes) -> Optional[Tuple[int, int]]:
    """Width and height of a JPEG, PNG, GIF or WebP from its first bytes, or None when they do not show them."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X" and len(data) >= 30:
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if kind == b"VP8 " and len(data) >= 30:
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        return None
    if data[:2] == b"\xff\xd8":
        position = 2
        while position + 9 < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker = data[position + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                position += 1 if marker == 0xFF else 2
                continue
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[position + 5:position + 9])
                return width, height
            position += 2 + struct.unpack(">H", data[position + 2:position + 4])[0]
    return None


def measure(url: str, get: Fetch) -> Tuple[int, int]:
    """The image's size, read from its first bytes when the server honours a range and from the whole file otherwise.

    Raises when the URL is not an image: that is not a page worth keeping.
    """
    response = get(url, HEAD_BYTES)
    if not response.content_type.lower().startswith("image/"):
        raise ValueError(f"{url} is {response.content_type or 'untyped'}, not an image")
    size = image_size(response.body)
    if size is None and len(response.body) >= HEAD_BYTES:
        size = image_size(get(url, None).body)
    if size is None or not all(size):
        raise ValueError(f"No size in the image at {url}")
    return size


def read_cache(directory: Path) -> Dict[str, dict]:
    try:
        pages = json.loads((directory / STATE_PATH).read_text(encoding="utf-8"))["pages"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {url: entry for url, entry in pages.items() if isinstance(entry, dict)} if isinstance(pages, dict) else {}


def write_cache(directory: Path, pages: Dict[str, dict]) -> None:
    path = directory / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA, "pages": dict(sorted(pages.items()))}, separators=(",", ":")), encoding="utf-8")


def read_page(page: Page, cached: Optional[dict], get: Fetch) -> dict:
    """The page's image and its size: from the cache when the sitemap's `lastmod` has not moved, else from the page.

    Raises when the page or its image cannot be read, so the next run tries it again.
    """
    if cached is not None and cached.get("lastmod") == page.lastmod:
        return cached
    image = og_image(get(page.url, None).body, page.url)
    entry = {"lastmod": page.lastmod, "image": image}
    if image is None:
        return entry
    if cached and cached.get("image") == image and cached.get("width") and cached.get("height"):
        entry.update(width=cached["width"], height=cached["height"])
    else:
        entry["width"], entry["height"] = measure(image, get)
    return entry


def pick(candidates: List[Tuple[Page, dict]]) -> Optional[Tuple[Page, dict]]:
    """The largest landscape gallery image, a product's gallery before an older gallery on a tie; a product page's image only when there is no gallery's."""
    landscape = [
        (page, entry) for page, entry in candidates
        if entry.get("image") and entry.get("width") and entry.get("height") and entry["width"] >= MIN_ASPECT * entry["height"]
    ]
    return min(
        landscape,
        key=lambda found: (found[0].kind == PRODUCT, -found[1]["width"] * found[1]["height"], found[0].kind, found[0].url),
        default=None,
    )


def build(sets: List[SetInfo], matches: Dict[str, List[Page]], cache: Dict[str, dict], now: datetime) -> dict:
    names = {info.code: info.name for info in sets}
    art = {}
    for code in sorted(matches):
        chosen = pick([(page, cache[page.url]) for page in matches[code] if page.url in cache])
        if chosen:
            page, entry = chosen
            art[code] = {"url": entry["image"], "width": entry["width"], "height": entry["height"], "title": names[code], "source": SOURCE, "page": page.url}
    return {"schema": SCHEMA, "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sets": art}


def write_set_art(directory: Path, now: datetime, get: Fetch, scryfall: Callable[[str], bytes]) -> List[str]:
    """Writes sets/art.json into `directory` and returns its path.

    `get` fetches Wizards' pages and images, already paced; `scryfall` returns the bytes of a Scryfall API URL. A page or image that fails
    is logged and tried again next run; the sitemap or Scryfall's sets failing is raised, and writes nothing, so the published file stays.
    """
    pages = parse_sitemap(get(SITEMAP_URL, None).body)
    sets = parse_sets(json.loads(scryfall(SETS_URL)))
    matches = pages_by_set(sets, pages)
    wanted = {page.url: page for found in matches.values() for page in found}
    cache = read_cache(directory)
    fetched = 0
    for url, page in sorted(wanted.items()):
        previous = cache.get(url)
        try:
            entry = read_page(page, previous, get)
        except Exception as error:  # noqa: BLE001 - one page must not stop the others
            log.warning("Set art: %s failed: %s", url, error)
            continue
        if entry is not previous:
            fetched += 1
        cache[url] = entry
    write_cache(directory, {url: entry for url, entry in cache.items() if url in wanted})
    document = build(sets, matches, cache, now)
    path = directory / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Set art: %d of %d sets have art (%d pages read this run, %d cached)", len(document["sets"]), len(sets), fetched, len(wanted) - fetched)
    return [PATH]


def scryfall_fetch(url: str, user_agent: str = USER_AGENT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(args: List[str]) -> int:
    """`python -m mtgmeta set-art DIR`: writes DIR/sets/art.json and DIR/state/set-art.json."""
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="mtgmeta set-art", description=main.__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args(args)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = os.environ.get("SET_ART_USER_AGENT", USER_AGENT)
    delay = float(os.environ.get("SET_ART_DELAY", str(DELAY)))
    get = Paced(lambda url, last_byte=None: fetch(url, last_byte, agent), delay)
    write_set_art(options.directory, datetime.now(timezone.utc), get, lambda url: scryfall_fetch(url, agent))
    return 0
