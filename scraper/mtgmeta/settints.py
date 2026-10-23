"""sets/tints.json: one tint colour per Scryfall set, for a set icon tile (a coloured rounded square with the set's white symbol).

A main set (one with no `parent_set_code`) gets its colour from its art: Wizards' art for the set in `sets/art.json` (a small
copy of the image, `w=96` on Wizards' CDN), else the art crop of the set's most played card (EDHREC rank). A set with neither is
left out, and the app draws a neutral tile. The colour is the dominant hue of the picture, which is the hue bin of 12 with the most
saturation and brightness in a 16 by 16 copy of it, and then made dark enough, or light enough, for a white symbol to read on it.

Every child set (a token set, a promo set, a Commander deck's set) has the colour of the main set at the top of its chain of
`parent_set_code`s, with `source` `"parent"`.

The colours are kept in `state/set-tints.json` by set code with the picture's URL, so a set is looked at again only when it is new
or Wizards' art for it changed. A set found to have no cards is looked at again only when its card count changes.
See docs/data-format.md.
"""
from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

log = logging.getLogger(__name__)

SCHEMA = 1
PATH = "sets/tints.json"
STATE_PATH = "state/set-tints.json"
ART_PATH = "sets/art.json"
SETS_URL = "https://api.scryfall.com/sets"
SEARCH_URL = "https://api.scryfall.com/cards/search?q={query}&unique=cards"
USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
DELAY = 0.1
ATTEMPTS = 3
WIZARDS, CARD, PARENT = "wizards", "card", "parent"
BINS = 12
GRID = 16
MIN_WEIGHT = 0.02 * GRID * GRID
MIN_VALUE = 0.12
LUMINANCE = (0.06, 0.24)
Colour = Tuple[float, float, float]
Get = Callable[[str], bytes]


def dominant(image: Image.Image) -> Colour:
    """The colour of the picture's strongest hue: the mean colour of the pixels in the hue bin with the most saturation times value.

    Pixels darker than 0.12 in value and greys do not count. A picture with almost nothing left is its mean colour.
    """
    small = image.convert("RGB").resize((GRID, GRID), Image.LANCZOS)
    weights = [0.0] * BINS
    sums = [[0.0, 0.0, 0.0] for _ in range(BINS)]
    mean = [0.0, 0.0, 0.0]
    total = 0.0
    pixels = small.tobytes()
    for index in range(0, len(pixels), 3):
        red, green, blue = pixels[index:index + 3]
        rgb = (red / 255, green / 255, blue / 255)
        mean = [m + c for m, c in zip(mean, rgb)]
        value = max(rgb)
        if value < MIN_VALUE:
            continue
        spread = value - min(rgb)
        if spread <= 0:
            continue
        weight = (spread / value) * value
        if value == rgb[0]:
            sextant = ((rgb[1] - rgb[2]) / spread) % 6
        elif value == rgb[1]:
            sextant = (rgb[2] - rgb[0]) / spread + 2
        else:
            sextant = (rgb[0] - rgb[1]) / spread + 4
        sextant %= 6
        index = min(int(sextant / 6 * BINS), BINS - 1)
        weights[index] += weight
        sums[index] = [s + c * weight for s, c in zip(sums[index], rgb)]
        total += weight
    mean = [m / (GRID * GRID) for m in mean]
    if total < MIN_WEIGHT:
        return mean[0], mean[1], mean[2]
    best = max(range(BINS), key=lambda i: weights[i])
    return sums[best][0] / weights[best], sums[best][1] / weights[best], sums[best][2] / weights[best]


def decode(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def encode(value: float) -> float:
    value = min(max(value, 0.0), 1.0)
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055


def readable(colour: Colour, low: float = LUMINANCE[0], high: float = LUMINANCE[1]) -> Colour:
    """The colour with its luminance, in linear sRGB, brought into `low`...`high`, so a white symbol reads on it."""
    linear = [decode(x) for x in colour]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    if luminance < 1e-4:
        return 0.2, 0.2, 0.24
    scale = min(max(luminance, low), high) / luminance
    red, green, blue = (encode(x * scale) for x in linear)
    return red, green, blue


def to_hex(colour: Colour) -> str:
    return "#" + "".join(f"{round(min(max(x, 0.0), 1.0) * 255):02x}" for x in colour)


def tint_of(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        return to_hex(readable(dominant(image)))


def small_url(url: str) -> str:
    """Wizards' CDN serves the image at the width asked for, and the tint needs 16 pixels."""
    if "ctfassets" not in url:
        return url
    return url + ("&" if "?" in url else "?") + "w=96"


def read_state(directory: Path) -> Dict[str, dict]:
    try:
        sets = json.loads((directory / STATE_PATH).read_text(encoding="utf-8"))["sets"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {code: entry for code, entry in sets.items() if isinstance(entry, dict)} if isinstance(sets, dict) else {}


def write_state(directory: Path, sets: Dict[str, dict]) -> None:
    path = directory / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA, "sets": dict(sorted(sets.items()))}, separators=(",", ":")), encoding="utf-8")


def load_art(directory: Path, get: Get, published_url: str) -> Optional[Dict[str, str]]:
    """Wizards' art url by set code, from `sets/art.json` in `directory` when the set-art step wrote it, else the published file.

    None when neither can be read: the sets whose colour came from Wizards' art then keep it.
    """
    try:
        document = json.loads((directory / ART_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        try:
            document = json.loads(get(published_url))
        except Exception as error:  # noqa: BLE001 - the card art still works without it
            log.warning("Set tints: no set art to read: %s", error)
            return None
    sets = document.get("sets") if isinstance(document, dict) else None
    if not isinstance(sets, dict):
        return None
    return {code: entry["url"] for code, entry in sets.items() if isinstance(entry, dict) and entry.get("url")}


def card_art_url(code: str, get: Get) -> Optional[str]:
    """The art crop of the set's most played card, or None when Scryfall has no card of the set."""
    url = SEARCH_URL.format(query=urllib.parse.quote(f"e:{code} order:edhrec"))
    try:
        cards = json.loads(get(url)).get("data") or []
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not cards:
        return None
    uris = cards[0].get("image_uris") or (cards[0].get("card_faces") or [{}])[0].get("image_uris") or {}
    return uris.get("art_crop")


def tint_set(entry: dict, art_url: Optional[str], known: bool, cached: Optional[dict], get: Get) -> Optional[dict]:
    """The state entry for a main set: from `cached` when nothing it was made from changed, else read again.

    `known` is whether Wizards' art could be read at all; `art_url` is the set's, if any. Raises when a picture cannot be read.
    """
    hit = cached if cached and cached.get("tint") else None
    if art_url:
        if hit and hit["source"] == WIZARDS and hit["url"] == art_url:
            return hit
        try:
            return {"source": WIZARDS, "url": art_url, "tint": tint_of(get(small_url(art_url)))}
        except Exception as error:  # noqa: BLE001 - the card art still works
            log.warning("Set tints: %s's art %s failed: %s", entry["code"], art_url, error)
            if hit:
                return hit
    elif hit and (hit["source"] == CARD or not known):
        return hit
    count = entry.get("card_count") or 0
    if count <= 0:
        return None
    if cached and cached.get("miss") == count:
        return cached
    crop = card_art_url(entry["code"], get)
    if crop is None:
        return {"miss": count}
    return {"source": CARD, "url": crop, "tint": tint_of(get(crop))}


def root_of(code: str, parents: Dict[str, str]) -> Optional[str]:
    """The main set at the top of a set's chain of parents, or None when the chain loops or leaves the list."""
    seen = set()
    while code in parents:
        if code in seen:
            return None
        seen.add(code)
        code = parents[code]
    return code


def build(sets: List[dict], state: Dict[str, dict], now: datetime) -> dict:
    parents = {entry["code"]: entry["parent_set_code"] for entry in sets if entry.get("parent_set_code")}
    codes = {entry["code"] for entry in sets}
    tints: Dict[str, dict] = {}
    for code in sorted(codes):
        root = root_of(code, parents)
        found = state.get(root) if root in codes else None
        if root is None or not found or not found.get("tint"):
            continue
        tints[code] = {"tint": found["tint"], "source": found["source"] if root == code else PARENT}
    return {"schema": SCHEMA, "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sets": tints}


def write_set_tints(directory: Path, now: datetime, get: Get, published_art_url: str) -> List[str]:
    """Writes sets/tints.json into `directory` and returns its path.

    `get` returns the bytes at a URL, already paced. A set whose picture cannot be read is logged and tried again next run; Scryfall's
    sets failing is raised, and writes nothing, so the published file stays.
    """
    sets = [entry for entry in json.loads(get(SETS_URL)).get("data", []) if entry.get("code")]
    for entry in sets:
        entry["code"] = entry["code"].lower()
        if entry.get("parent_set_code"):
            entry["parent_set_code"] = entry["parent_set_code"].lower()
    art = load_art(directory, get, published_art_url)
    previous = read_state(directory)
    state: Dict[str, dict] = {}
    read = 0
    for entry in sets:
        if entry.get("parent_set_code"):
            continue
        code = entry["code"]
        try:
            found = tint_set(entry, (art or {}).get(code), art is not None, previous.get(code), get)
        except Exception as error:  # noqa: BLE001 - one set must not stop the others
            log.warning("Set tints: %s failed: %s", code, error)
            found = previous.get(code)
        if found is not None:
            state[code] = found
            read += found is not previous.get(code)
    write_state(directory, state)
    document = build(sets, state, now)
    path = directory / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts: Dict[str, int] = {}
    for tint in document["sets"].values():
        counts[tint["source"]] = counts.get(tint["source"], 0) + 1
    log.info("Set tints: %d of %d sets have a tint (%s); %d sets read this run", len(document["sets"]), len(sets), ", ".join(f"{n} {s}" for s, n in sorted(counts.items())), read)
    return [PATH]


def fetch(url: str, user_agent: str = USER_AGENT, sleep: Callable[[float], None] = time.sleep) -> bytes:
    """The bytes at `url`; a rate limit or a server error is tried again after a pause, a 404 is raised at once."""
    headers = {"User-Agent": user_agent, "Accept": "application/json;q=0.9,*/*;q=0.8" if "api.scryfall.com" in url else "*/*"}
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == ATTEMPTS:
                raise
        sleep(2 * attempt)
    raise AssertionError("unreachable")


def paced_get(user_agent: str = USER_AGENT, delay: float = DELAY) -> Get:
    from .setart import Paced, Response

    paced = Paced(lambda url, last_byte=None: Response("", fetch(url, user_agent)), delay)
    return lambda url: paced(url).body


def main(args: List[str]) -> int:
    """`python -m mtgmeta set-tints DIR`: writes DIR/sets/tints.json and DIR/state/set-tints.json, reading the art from DIR/sets/art.json or the published file."""
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="mtgmeta set-tints", description=main.__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args(args)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    data_url = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")
    get = paced_get(os.environ.get("SET_TINTS_USER_AGENT", USER_AGENT), float(os.environ.get("SET_TINTS_DELAY", str(DELAY))))
    write_set_tints(options.directory, datetime.now(timezone.utc), get, f"{data_url}/{ART_PATH}")
    return 0
