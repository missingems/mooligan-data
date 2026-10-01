"""Citations: where each fact in the index comes from, in a form an app can show as is.

Every event, relation, bio sentence and description in the index carries one:

    {"source": "wizards", "official": true, "publisher": "Wizards of the Coast",
     "work": "Jace, Alone", "series": "Magic Story", "authors": ["Alison Lührs"], "date": "2017-09-06",
     "url": <the original page>, "link": <the page, scrolled to the quote>, "archived": null, "license": null,
     "text": "\"Jace, Alone\" by Alison Lührs. Magic Story, Wizards of the Coast, 6 Sep 2017."}

`source` is one of:

- "wizards": magic.wizards.com's Magic Story articles and story profiles;
- "wizards-archive": wizards.com's old story columns, read from the Internet Archive (`archived` is the copy,
  `url` the page as Wizards published it);
- "card-text": a card's flavor text (`work` is the card, `series` its set, `url` its Scryfall page);
- "mtg-wiki": MTG Wiki, fan-written (`official` false), under CC BY-NC-SA 4.0, which asks for the credit in
  `text` and a link back wherever it is shown.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from urllib.parse import quote as url_quote

def text_fragment(url: str, quote: str) -> str:
    """The page's URL with a #:~:text= fragment, so a browser scrolls to the quote and highlights it."""

    def encode(text: str) -> str:
        return url_quote(text, safe="").replace("-", "%2D")

    words = quote.split()
    if len(words) <= 8:
        return f"{url}#:~:text={encode(quote)}"
    return f"{url}#:~:text={encode(' '.join(words[:4]))},{encode(' '.join(words[-4:]))}"


# The old wizards.com columns, by the key their URLs carry.
_COLUMNS = {
    "stf": "Savor the Flavor", "savor-flavor": "Savor the Flavor",
    "ur": "Uncharted Realms", "uncharted-realms": "Uncharted Realms",
    "arcana": "Magic Arcana", "feature": "Daily MTG", "magic-story": "Magic Story",
}


def _day(date: str) -> str:
    try:
        return datetime.strptime(date[:10], "%Y-%m-%d").strftime("%-d %b %Y")
    except ValueError:
        return date


def _column(url: str) -> str:
    for key, name in _COLUMNS.items():
        if re.search(rf"[/=]({re.escape(key)})(/|-\d{{4}}|$)", url.lower()) or f"/{key}/" in url.lower():
            return name
    return "wizards.com"


def citation(page: dict, paragraph: Optional[int] = None, quote: Optional[str] = None) -> dict:
    """The citation for a page, or for one quote in one paragraph of it."""
    source = page.get("source", "wizards")
    kind = page.get("kind", "story")
    paragraphs = page.get("paragraphs", [])
    para = paragraphs[paragraph] if paragraph is not None and 0 <= paragraph < len(paragraphs) else {}
    title = page.get("title", "")
    authors = page.get("authors", [])
    date = page.get("story_date", "")
    archived, license_ = None, None
    if source == "card-text":
        work = para.get("card") or title
        series = re.sub(r":\s*card flavor text$", "", title)
        url = para.get("url") or page.get("url", "")
        publisher, official = "Wizards of the Coast", True
        text = f"{work} ({series}, {date[:4]}), flavor text. Wizards of the Coast." if date else f"{work} ({series}), flavor text. Wizards of the Coast."
    elif source == "mtg-wiki":
        work, series, url = title, "MTG Wiki", page.get("url", "")
        publisher, official, license_ = "MTG Wiki contributors", False, page.get("license") or "CC BY-NC-SA 4.0"
        section = f", section \"{para['section']}\"" if para.get("section") else ""
        text = f"\"{title}\"{section}. MTG Wiki contributors, {license_}."
    elif source == "wizards-archive":
        work, url, archived = title, page.get("original_url") or page.get("url", ""), page.get("url")
        series, publisher, official = _column(url), "Wizards of the Coast", True
        when = f", {_day(date)}" if date else ""
        text = f"\"{title}\". {series}, Wizards of the Coast{when}. Archived by the Internet Archive."
    else:
        work, url = re.sub(r"\s*\|\s*(Planeswalker|Plane)$", "", title) if kind == "profile" else title, page.get("url", "")
        series = "Magic Story" if kind == "story" else "Magic: The Gathering story profiles"
        publisher, official = "Wizards of the Coast", True
        by = f" by {', '.join(authors)}" if authors else ""
        when = f", {_day(date)}" if date else ""
        text = f"\"{work}\"{by}. {series}, Wizards of the Coast{when}."
    target = archived or url
    return {
        "source": source,
        "official": official,
        "publisher": publisher,
        "work": work,
        "series": series,
        "authors": authors,
        "date": date,
        "url": url,
        "link": text_fragment(target, quote) if quote else target,
        "archived": archived,
        "license": license_,
        "text": text,
    }
