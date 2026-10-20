"""sets/products/{code}.json: the sealed products of each recent set, keyed by Scryfall set code, for a set page's shelf.

TCGCSV (https://tcgcsv.com) mirrors TCGplayer's catalog once a day as plain JSON. Category 1 is Magic: `/tcgplayer/1/groups`
lists TCGplayer's sets (a group each, with an abbreviation and a name), `/tcgplayer/1/{group}/products` its products and
`/tcgplayer/1/{group}/prices` their prices. A product with no card number and no rarity is sealed (a booster, a box, a bundle,
a deck), and TCGplayer files it under its set's group.

A group is matched to a Scryfall set by abbreviation (it is the set's code for most sets) when the two names also read alike,
else by name alone; the names are compared by their words, with TCGplayer's "Commander: X" read as Scryfall's "X Commander".
Only sets released since 2023 and the ones yet to come are looked up.

TCGplayer's CDN does not have the picture of some products not out yet although TCGCSV counts one, so each picture is asked
for once (a `Range` request for its first byte) and a product whose picture is not served is left out until a later read finds it.

TCGCSV asks for one sync a day, a custom User-Agent and at least 100 ms between requests. `last-updated.txt` says when its files
were built. A group read is kept in `state/set-products.json` with that build and the group's own `modifiedOn`: a set released
or yet to come within `ACTIVE_DAYS` (whose prices still move and whose products are still added) is read again after every
build, an older set only when its `modifiedOn` changed or its copy is `STALE_DAYS` old. The files are rebuilt from the state on
every run. See docs/data-format.md.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = 1
DIRECTORY = "sets/products"
STATE_PATH = "state/set-products.json"
BASE_URL = "https://tcgcsv.com/tcgplayer/1"
LAST_UPDATED_URL = "https://tcgcsv.com/last-updated.txt"
SETS_URL = "https://api.scryfall.com/sets"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
DELAY = 0.25
PICTURE_WORKERS = 6
FIRST_RELEASE = "2023-01-01"
SKIPPED_SET_TYPES = {"token", "memorabilia", "minigame", "vanguard", "alchemy"}
ACTIVE_DAYS = 120
STALE_DAYS = 14
# Below this, two names are not the same set; an abbreviation that agrees with a set's code needs less.
NAME_MATCH = 0.8
ABBREVIATION_MATCH = 0.6
STOPWORDS = {"the", "of", "a", "an", "and", "in", "for", "to"}
KINDS = (
    "booster-box", "collector-booster-box", "bundle", "play-booster", "collector-booster",
    "prerelease", "commander-deck", "starter-kit", "other",
)
LANGUAGES = "japanese|chinese|simplified chinese|traditional chinese|korean|german|french|italian|spanish|portuguese|russian"
FOREIGN = re.compile(rf"\((?:{LANGUAGES})\)", re.I)
IMAGE_SIZE = re.compile(r"_\d+w(\.[A-Za-z]+)$")
TIMESTAMP = "%Y-%m-%dT%H:%M:%S%z"


class SetInfo(NamedTuple):
    code: str
    name: str
    released_at: str


class Group(NamedTuple):
    id: int
    name: str
    abbreviation: str
    modified: str


def parse_sets(document: dict, today: str) -> List[SetInfo]:
    """Scryfall's paper sets released since 2023, and the ones not out yet (Scryfall lists those with a future date)."""
    sets = []
    for entry in document.get("data", []):
        code, name, released = entry.get("code"), entry.get("name"), entry.get("released_at") or today
        if not code or not name or entry.get("digital") or entry.get("set_type") in SKIPPED_SET_TYPES or released < FIRST_RELEASE:
            continue
        sets.append(SetInfo(code.lower(), name, entry.get("released_at") or today))
    return sets


def parse_groups(document: dict) -> List[Group]:
    groups = []
    for entry in document.get("results", []):
        if entry.get("groupId") is None or not entry.get("name"):
            continue
        groups.append(Group(int(entry["groupId"]), entry["name"], (entry.get("abbreviation") or "").lower(), entry.get("modifiedOn") or ""))
    return groups


def words(name: str) -> frozenset:
    """A set's name as the words it is told apart by: TCGplayer's "Commander: X" is Scryfall's "X Commander", and its "Universes Beyond" is dropped."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().replace("'", "")
    text = re.sub(r"\buniverses beyond\b", " ", text)
    text = re.sub(r"\beternal[- ]legal\b", " eternal ", text)
    found = re.findall(r"[a-z0-9]+", text)
    if found[:1] == ["commander"] and len(found) > 1:
        found = found[1:] + ["commander"]
    return frozenset(word for word in found if word not in STOPWORDS)


def similarity(left: frozenset, right: frozenset) -> float:
    return len(left & right) / len(left | right) if left | right else 0.0


def match_groups(sets: Iterable[SetInfo], groups: Iterable[Group]) -> Dict[str, Group]:
    """Each set's group: the one with the same abbreviation whose name reads alike (or holds the other's), else the one named like it.

    The best match wins, and a group serves one set, the one it matches best (two groups can share an abbreviation:
    "Planechase: March of the Machine" is "MOC" like "Commander: March of the Machine").
    """
    groups = list(groups)
    keyed = [(group, words(group.name)) for group in groups]
    scored: List[Tuple[float, int, str, Group]] = []
    for info in sets:
        target = words(info.name)
        best: Optional[Tuple[float, int, Group]] = None
        for group, group_words in keyed:
            score = similarity(target, group_words)
            agrees = group.abbreviation == info.code
            contained = agrees and bool(group_words) and bool(target) and (group_words <= target or target <= group_words)
            if not (score >= NAME_MATCH or (agrees and score >= ABBREVIATION_MATCH) or contained):
                continue
            candidate = (int(agrees), score, group)
            if best is None or candidate[:2] > best[:2] or (candidate[:2] == best[:2] and group.id < best[2].id):
                best = candidate
        if best:
            scored.append((best[1], best[0], info.code, best[2]))
    matched: Dict[str, Group] = {}
    taken: set = set()
    for score, agrees, code, group in sorted(scored, key=lambda row: (-row[1], -row[0], row[2])):
        if group.id not in taken:
            matched[code] = group
            taken.add(group.id)
    return matched


def classify(name: str) -> str:
    """The kind of sealed product from its name; see KINDS. A case, a sample pack and what TCGplayer sells that is none of these is "other"."""
    text = name.lower()
    if re.search(r"\bcases?\b", text):
        return "other"
    if "prerelease" in text:
        return "prerelease"
    box = re.search(r"\b(?:box|display)\b", text) is not None
    odd = re.search(r"sample|omega|minimal packaging", text) is not None
    if "commander deck" in text:
        return "other" if box else "commander-deck"
    if "collector booster" in text:
        return "other" if odd else "collector-booster-box" if box else "collector-booster"
    if re.search(r"play booster|play pack", text):
        return "other" if odd else "booster-box" if box else "play-booster"
    if "booster" in text:
        if box:
            return "booster-box"
        return "play-booster" if re.fullmatch(r"(?:sleeved )?booster(?: pack)?", text.split(" - ", 1)[-1]) else "other"
    if re.search(r"\bbundle\b|\bfat pack\b", text):
        return "bundle"
    if re.search(r"starter (?:kit|deck|set)", text):
        return "starter-kit"
    return "other"


def is_sealed(product: dict) -> bool:
    """TCGplayer gives a single card a number and a rarity; a product with neither is sealed."""
    return not any(item.get("name") in ("Number", "Rarity") for item in product.get("extendedData") or [])


def larger_image(url: str) -> str:
    """TCGplayer's CDN has the picture at 200 and 400 pixels wide; the larger one is for a shelf."""
    return IMAGE_SIZE.sub(r"_400w\1", url)


def prices_by_product(prices: Iterable[dict]) -> Dict[int, float]:
    """Each product's market price, else its mid price; the normal printing's when there are several."""
    found: Dict[int, Tuple[int, float]] = {}
    for row in prices:
        product = row.get("productId")
        value = next((row[key] for key in ("marketPrice", "midPrice") if isinstance(row.get(key), (int, float))), None)
        if product is None or value is None:
            continue
        rank = 0 if row.get("subTypeName") == "Normal" else 1
        if product not in found or rank < found[product][0]:
            found[product] = (rank, round(float(value), 2))
    return {product: price for product, (rank, price) in found.items()}


def sealed_products(products: Iterable[dict], prices: Dict[int, float]) -> List[dict]:
    """A group's sealed products in the file's shape. One TCGplayer has no picture of yet (it is not out), or sells in another language, is left out."""
    found = []
    for product in products:
        name, url, image = product.get("name"), product.get("url"), product.get("imageUrl")
        if not name or not url or not image or not product.get("imageCount") or not is_sealed(product) or FOREIGN.search(name):
            continue
        found.append({
            "id": product.get("productId"),
            "name": name,
            "kind": classify(name),
            "image": larger_image(image),
            "url": url,
            "price": prices.get(product.get("productId")),
        })
    found.sort(key=lambda item: (KINDS.index(item["kind"]), item["id"] or 0))
    return found


def read_state(directory: Path) -> Dict[str, dict]:
    try:
        groups = json.loads((directory / STATE_PATH).read_text(encoding="utf-8"))["groups"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {key: entry for key, entry in groups.items() if isinstance(entry, dict)} if isinstance(groups, dict) else {}


def write_state(directory: Path, built: str, groups: Dict[str, dict]) -> None:
    path = directory / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA, "tcgcsv": built, "groups": dict(sorted(groups.items()))}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def parse_built(text: str) -> datetime:
    """TCGCSV's build time, from the line in last-updated.txt."""
    return datetime.strptime(text.strip(), TIMESTAMP).astimezone(timezone.utc)


def needs_read(entry: Optional[dict], group: Group, info: SetInfo, built: datetime) -> bool:
    """Whether the group is read again: it was never read, its `modifiedOn` moved, or its copy is older than a set of its age should have."""
    if entry is None or entry.get("modified") != group.modified or not isinstance(entry.get("products"), list):
        return True
    try:
        read_at = parse_built(entry["built"])
    except (KeyError, ValueError, TypeError):
        return True
    if info.released_at >= (built - timedelta(days=ACTIVE_DAYS)).strftime("%Y-%m-%d"):
        return read_at < built
    return read_at < built - timedelta(days=STALE_DAYS)


def read_group(group: Group, get: Callable[[str], bytes], loads: Callable[[str], bool], known: Iterable[str] = ()) -> List[dict]:
    """A group's sealed products, each with a picture that loads: `loads` is asked of a picture not in `known` (the pictures the last read found)."""
    products = json.loads(get(f"{BASE_URL}/{group.id}/products")).get("results") or []
    prices = json.loads(get(f"{BASE_URL}/{group.id}/prices")).get("results") or []
    seen = set(known)
    found = sealed_products(products, prices_by_product(prices))
    unknown = [product["image"] for product in found if product["image"] not in seen]
    with ThreadPoolExecutor(max_workers=PICTURE_WORKERS) as pool:
        there = dict(zip(unknown, pool.map(loads, unknown)))
    return [product for product in found if product["image"] in seen or there[product["image"]]]


def product_file(code: str, now: datetime, products: List[dict]) -> dict:
    return {
        "schema": SCHEMA,
        "set": code,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "products": [{key: product[key] for key in ("name", "kind", "image", "url", "price")} for product in products],
    }


def write_set_products(
    directory: Path, now: datetime, get: Callable[[str], bytes], scryfall: Callable[[str], bytes], loads: Callable[[str], bool],
) -> List[str]:
    """Writes sets/products/{code}.json into `directory` for each recent set with sealed products, and returns the paths.

    `get` fetches TCGCSV's files, already paced; `scryfall` returns the bytes of a Scryfall API URL; `loads` (called from several threads) says whether a picture on
    TCGplayer's CDN is there (it is not, for some products not out yet, though TCGCSV counts an image). A group that fails is logged
    and read again next run (its last copy is used meanwhile); TCGCSV's build time, group list or Scryfall's sets failing is
    raised, and writes nothing, so the published files stay.
    """
    built_text = get(LAST_UPDATED_URL).decode("utf-8").strip()
    built = parse_built(built_text)
    sets = parse_sets(json.loads(scryfall(SETS_URL)), now.strftime("%Y-%m-%d"))
    matched = match_groups(sets, parse_groups(json.loads(get(f"{BASE_URL}/groups"))))
    info_by_code = {info.code: info for info in sets}
    state = read_state(directory)
    kept: Dict[str, dict] = {}
    read = 0
    for code, group in sorted(matched.items()):
        entry = state.get(str(group.id))
        if needs_read(entry, group, info_by_code[code], built):
            try:
                known = [product["image"] for product in (entry or {}).get("products") or []]
                entry = {"modified": group.modified, "built": built_text, "products": read_group(group, get, loads, known)}
                read += 1
            except Exception as error:  # noqa: BLE001 - one group must not stop the others
                log.warning("Set products: %s (%s) failed: %s", group.name, group.id, error)
        if entry is not None:
            kept[str(group.id)] = entry
    write_state(directory, built_text, kept)
    written = []
    for code, group in sorted(matched.items()):
        products = kept.get(str(group.id), {}).get("products")
        if not products:
            continue
        path = directory / DIRECTORY / f"{code}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(product_file(code, now, products), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        written.append(f"{DIRECTORY}/{code}.json")
    log.info(
        "Set products: %d of %d recent sets have sealed products (%d groups read this run, %d from the state)",
        len(written), len(sets), read, len(matched) - read,
    )
    return written


def fetch(url: str, user_agent: str = USER_AGENT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json,text/plain"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def image_loads(url: str, user_agent: str = USER_AGENT) -> bool:
    """Whether the picture is served as an image. A 4xx is no (TCGplayer's CDN answers 403 for a picture it does not have); any other failure is raised."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "image/*", "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.headers.get("Content-Type", "").lower().startswith("image/")
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500:
            return False
        raise


def main(args: List[str]) -> int:
    """`python -m mtgmeta set-products DIR`: writes DIR/sets/products/{code}.json and DIR/state/set-products.json."""
    import argparse
    import os

    from .setart import Paced, Response, scryfall_fetch

    parser = argparse.ArgumentParser(prog="mtgmeta set-products", description=main.__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args(args)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = os.environ.get("SET_PRODUCTS_USER_AGENT", USER_AGENT)
    paced = Paced(lambda url, last_byte=None: Response("", fetch(url, agent)), float(os.environ.get("SET_PRODUCTS_DELAY", str(DELAY))))
    write_set_products(
        options.directory, datetime.now(timezone.utc), lambda url: paced(url).body, lambda url: scryfall_fetch(url, agent),
        lambda url: image_loads(url, agent),
    )
    return 0
