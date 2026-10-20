from pathlib import Path

from mtglore.parse import kind_of, listing_total, listing_urls, parse_page, sitemap_urls

FIXTURES = Path(__file__).parent / "fixtures"
NEW = "https://magic.wizards.com/en/news/magic-story/reality-fracture-episode-1-tam-alive"
OLD = "https://magic.wizards.com/en/news/magic-story/zendikars-last-stand-2016-02-17"


def read(name):
    return (FIXTURES / name).read_text()


def test_new_story():
    page = parse_page(read("article_reality_fracture_1.html"), NEW)
    assert page["kind"] == "story" and page["slug"] == "reality-fracture-episode-1-tam-alive"
    assert page["title"] == "Reality Fracture | Episode 1: Tam, Alive"
    assert page["authors"] == ["Alison Lührs"]
    assert page["story_date"] == "2026-08-31"
    nav = page["storyline_nav"]
    assert nav["title"] == "Reality Fracture"
    assert nav["chapters"][0] == NEW and len(nav["chapters"]) == 10
    assert page["paragraphs"][0]["text"].startswith("The first time Tam opens her eyes")
    assert page["paragraphs"][-1] == {"text": "I'm in progress.", "scene": 3}
    assert not any("|" in p["text"] and "Story" in p["text"] for p in page["paragraphs"])


def test_old_story_keeps_its_original_date_and_drops_captions_and_link_lists():
    page = parse_page(read("article_zendikars_last_stand.html"), OLD)
    assert page["story_date"] == "2016-02-24"
    texts = [p["text"] for p in page["paragraphs"]]
    assert not any("Art by" in t for t in texts)
    assert "Planeswalker Profile: Jace Beleren" not in texts


def test_profile():
    page = parse_page(read("profile_jace.html"), "https://magic.wizards.com/en/story/jace-beleren-planeswalker")
    assert page["kind"] == "profile" and page["title"] == "Jace Beleren | Planeswalker"
    assert page["paragraphs"][0]["text"].startswith("Jace Beleren may be the most talented mind mage")
    assert all(p["text"] != "EXPLORE THE LORE" for p in page["paragraphs"])


def test_discovery():
    urls = sitemap_urls(read("sitemap.xml"))
    assert len(urls) == 8 and all(kind_of(u) for u in urls)
    assert "https://magic.wizards.com/en/news/making-magic/reality-fracture-vision-design-handoff-part-2" not in urls
    listed = listing_urls(read("listing_page2.html"))
    assert len(listed) == 5 and all(kind_of(u) == "story" for u in listed)
    assert listing_total("perPage:aC,currentPage:1,totalRows:491,") == 491
