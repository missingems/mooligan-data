import json
from pathlib import Path

from mtglore.extract import page_prompt
from mtglore.sources import _archive_key, archive_page, card_pages, wiki_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_wiki_page_keeps_the_story_sections_only():
    html = json.loads((FIXTURES / "wiki_yawgmoth.json").read_text())["parse"]["text"]["*"]
    page = wiki_page("Yawgmoth", html, "Category:Characters")
    sections = {p["section"] for p in page["paragraphs"]}
    assert {"Early life", "Thran-Phyrexian War", "Phyrexian Invasion"} <= sections
    assert not sections & {"Gallery", "References", "In-game references"}
    assert page["source"] == "mtg-wiki" and page["url"] == "https://mtg.wiki/page/Yawgmoth"
    assert "## Early life" in page_prompt(page)


def test_card_pages_group_flavor_text_by_set_and_keep_the_card():
    cards = [
        {"set": "inv", "set_name": "Invasion", "released_at": "2000-10-02", "lang": "en", "collector_number": "10",
         "name": "Urza's Rage", "flavor_text": "\"I will not be defeated.\"\n—Urza", "scryfall_uri": "https://scryfall.com/card/inv/10?x=1"},
        {"set": "inv", "set_name": "Invasion", "released_at": "2000-10-02", "lang": "en", "collector_number": "2",
         "name": "Reprint", "flavor_text": "\"I will not be defeated.\"\n—Urza", "scryfall_uri": "https://scryfall.com/card/inv/2"},
        {"set": "inv", "lang": "ja", "collector_number": "3", "name": "Japanese", "flavor_text": "x"},
    ]
    page = card_pages(cards)["inv"]
    assert page["story_date"] == "2000-10-02" and len(page["paragraphs"]) == 1
    paragraph = page["paragraphs"][0]
    assert paragraph["text"] == "\"I will not be defeated.\" —Urza" and paragraph["url"] == "https://scryfall.com/card/inv/10"
    assert "[0] (Urza's Rage) \"I will not be defeated.\"" in page_prompt(page)


def test_archive_page_finds_the_article_text_and_its_date():
    body = "".join(f"<p>Paragraph {i} of the story, long enough to count as text in the article body.</p>" for i in range(12))
    html = f"<html><head><title>The Last Stand | Daily MTG</title></head><body><div id='nav'><p>Home</p></div><div id='content'>{body}</div></body></html>"
    page = archive_page(html, "http://www.wizards.com/Magic/Magazine/Article.aspx?x=mtg/daily/stf/42", "20090101000000")
    assert page["title"] == "The Last Stand" and len(page["paragraphs"]) == 12
    assert page["url"].startswith("https://web.archive.org/web/20090101000000/")
    assert _archive_key("http://magic.wizards.com:80/en/articles/archive/savor-flavor/ajani-2008-10-27") == "savor-flavor/ajani-2008-10-27"
    assert archive_page("<p>short</p>", "x", "1") is None
