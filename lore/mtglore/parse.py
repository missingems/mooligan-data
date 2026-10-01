"""Turns a story page from magic.wizards.com into plain paragraphs and the facts about the page.

Two kinds of page carry lore:

- a Magic Story article (`/en/news/magic-story/<slug>`): a chapter, a side story, a Planeswalker's Guide.
  Its text is the `<p>`s of `div.article-body`, with `<hr>`s between scenes.
- a profile (`/en/story/<slug>`): the short bio of a planeswalker or a plane.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

SITE = "https://magic.wizards.com"

# Text the profile pages end with, under every bio.
_PROFILE_BOILERPLATE = ("EXPLORE THE LORE", "Take off on your next adventure with stories from across the Magic multiverse!")
# "Affa Protector | Art by Izzy": the caption under a card's art.
_ART_CAPTION = re.compile(r"\|\s*Art by\b", re.I)
# "Editor's Note: This story was originally published on February 24, 2016."
_ORIGINALLY = re.compile(r"originally published on ([A-Z][a-z]+ \d{1,2}, \d{4})")
# "zendikars-last-stand-2016-02-17": old stories kept their date in the slug when they moved.
_SLUG_DATE = re.compile(r"-(\d{4}-\d{2}-\d{2})$")
# "1 | 2 | 3": the chapter links at the top and bottom of an episode.
_NAV_NUMBERS = re.compile(r"(\d+\s*\|\s*){2,}")


def slug_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


def kind_of(url: str) -> Optional[str]:
    path = urlparse(url).path
    if re.fullmatch(r"/en/news/magic-story/[^/]+/?", path):
        return "story"
    if re.fullmatch(r"/en/story/[^/]+/?", path):
        return "profile"
    return None


def text_of(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _article_meta(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Article":
            return data
    return {}


def _meta(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return (tag.get("content") or "").strip() if tag else ""


def _is_link_only(p: Tag) -> bool:
    """A paragraph that is nothing but a link, like the "Planeswalker Profile: Jace Beleren" list under old stories."""
    links = p.find_all("a")
    return len(links) == 1 and text_of(links[0]) == text_of(p)


def _chapter_nav(p: Tag, url: str) -> Optional[dict]:
    """The "Reality Fracture Story 1 | 2 | 3" block: the storyline's name and its chapters in order."""
    text = text_of(p)
    if not _NAV_NUMBERS.search(text):
        return None
    chapters = []
    for node in p.descendants:
        if isinstance(node, Tag) and node.name == "a" and node.get("href"):
            chapters.append(node["href"].split("#")[0].split("?")[0])
        elif not isinstance(node, Tag) and re.fullmatch(r"\s*\|?\s*\d+\s*\|?\s*", str(node)) and (node.parent is None or node.parent.name != "a"):
            # The current chapter is the one number without a link.
            chapters.append(url)
    title = re.split(r"\s+Story\b|\s+\d", text, maxsplit=1)[0].strip()
    return {"title": title, "chapters": list(dict.fromkeys(chapters))}


def story_date(paragraphs: List[dict], slug: str, published: str) -> str:
    """When the story first came out, as YYYY-MM-DD.

    Stories from before the site moved in 2022 were republished, so their `datePublished` is the day they
    moved. The editor's note at the top, or the date in the slug, keeps the original day.
    """
    for paragraph in paragraphs[:4]:
        found = _ORIGINALLY.search(paragraph["text"])
        if found:
            try:
                return datetime.strptime(found.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                pass
    found = _SLUG_DATE.search(slug)
    if found:
        return found.group(1)
    return published[:10]


def parse_story(html: str, url: str) -> dict:
    """A Magic Story article: its facts and paragraphs. `scene` counts the `<hr>` breaks before a paragraph."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("div.article-body")
    if body is None:
        raise ValueError(f"No article body on {url}")
    meta = _article_meta(soup)
    paragraphs: List[dict] = []
    nav = None
    scene = 0
    for node in body.find_all(["p", "hr"]):
        if node.name == "hr":
            scene += 1
            continue
        if node.find_parent("p") is not None or node.find_parent("figure") is not None:
            continue
        found = _chapter_nav(node, url)
        if found:
            nav = nav or found
            continue
        text = text_of(node)
        if not text or _is_link_only(node) or _ART_CAPTION.search(text):
            continue
        paragraphs.append({"text": text, "scene": scene})
    h1 = soup.find("h1")
    published = meta.get("datePublished", "")
    return {
        "kind": "story",
        "slug": slug_of(url),
        "url": url,
        "title": meta.get("headline") or (text_of(h1) if h1 else _meta(soup, "og:title")),
        "description": _meta(soup, "description"),
        "published": published,
        "modified": meta.get("dateModified", ""),
        "story_date": story_date(paragraphs, slug_of(url), published),
        "authors": [a.get("name", "") for a in meta.get("author") or [] if isinstance(a, dict) and a.get("name")],
        "storyline_nav": nav,
        "paragraphs": paragraphs,
    }


def parse_profile(html: str, url: str) -> dict:
    """A planeswalker's or plane's page under /en/story: a short bio."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup.find("main") or soup.body
    paragraphs = []
    for node in article.find_all(["p", "h2", "h3"]):
        text = text_of(node)
        if text and text not in _PROFILE_BOILERPLATE and node.find_parent("p") is None:
            paragraphs.append({"text": text, "scene": 0})
    title = (soup.title.string or "") if soup.title else ""
    return {
        "kind": "profile",
        "slug": slug_of(url),
        "url": url,
        # "Jace Beleren | Planeswalker | Magic: The Gathering" -> "Jace Beleren | Planeswalker"
        "title": re.sub(r"\s*\|\s*Magic: The Gathering\s*$", "", title).strip(),
        "description": _meta(soup, "description"),
        "published": "",
        "modified": "",
        "story_date": "",
        "authors": [],
        "storyline_nav": None,
        "paragraphs": paragraphs,
    }


def parse_page(html: str, url: str) -> dict:
    return parse_profile(html, url) if kind_of(url) == "profile" else parse_story(html, url)


def sitemap_urls(xml: str) -> List[str]:
    """The story and profile pages a sitemap lists, in its order."""
    urls = [loc.strip() for loc in re.findall(r"<loc>([^<]+)</loc>", xml)]
    return [url for url in dict.fromkeys(urls) if kind_of(url)]


def listing_urls(html: str) -> List[str]:
    """The articles a page of /en/news/magic-story links to."""
    paths = re.findall(r'href="(/en/news/magic-story/[^"#?]+)"', html)
    return [SITE + path for path in dict.fromkeys(paths)]


def listing_total(html: str) -> Optional[int]:
    """How many articles the listing says the category has."""
    found = re.search(r"totalRows:(\d+)", html)
    return int(found.group(1)) if found else None
