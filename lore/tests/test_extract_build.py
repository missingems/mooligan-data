import json

from mtglore.build import _shortening, build, duplicate_pages, text_fragment
from mtglore.extract import check, locate, page_prompt, pending

PAGE = {
    "kind": "story",
    "slug": "episode-1",
    "url": "https://magic.wizards.com/en/news/magic-story/episode-1",
    "title": "Episode 1",
    "description": "",
    "story_date": "2023-04-01",
    "storyline_nav": {"title": "March of the Machine", "chapters": ["https://magic.wizards.com/en/news/magic-story/episode-1"]},
    "paragraphs": [
        {"text": "Jace looked at the sky. “We have to go,” he said.", "scene": 0},
        {"text": "Vraska took his hand—and they planeswalked to Ravnica together.", "scene": 1},
    ],
}

RAW = {
    "storyline": "March of the Machine",
    "entities": [
        {"name": "Jace Beleren", "type": "character", "aliases": ["Jace"], "description": "A mind mage.", "presence": "appears"},
        {"name": "Vraska", "type": "character", "aliases": [], "description": "A gorgon.", "presence": "appears"},
        {"name": "Ravnica", "type": "plane", "aliases": [], "description": "A city plane.", "presence": "mentioned"},
    ],
    "events": [
        {"summary": "They leave for Ravnica.", "participants": ["Jace", "Vraska"], "location": "Ravnica", "importance": "minor", "paragraph": 0, "quote": "Vraska took his hand-and they planeswalked to Ravnica together."},
        {"summary": "Made up.", "participants": ["Jace"], "location": "", "importance": "major", "paragraph": 0, "quote": "Jace lost his spark forever."},
        {"summary": "Unknown person.", "participants": ["Teferi"], "location": "", "importance": "minor", "paragraph": 0, "quote": "Jace looked at the sky."},
    ],
    "relations": [
        {"source": "Vraska", "relation": "romantic", "target": "Jace Beleren", "note": "", "paragraph": 1, "quote": "\"We have to go,\" he said"},
    ],
}


def test_prompt_numbers_paragraphs_and_marks_scenes():
    prompt = page_prompt(PAGE)
    assert "[0] Jace looked at the sky." in prompt and "\n\n[1] Vraska" in prompt
    assert "March of the Machine" in prompt


def test_locate_folds_typography_and_finds_the_right_paragraph():
    assert locate("\"we have to go,\" he said", PAGE["paragraphs"], 1) == 0
    assert locate("Jace lost his spark", PAGE["paragraphs"], 0) is None
    assert locate("Jace", PAGE["paragraphs"], 0) is None  # too short to prove anything
    assert locate("ace looked at the sky", PAGE["paragraphs"], 0) is None  # not on a word boundary


def test_check_keeps_quoted_facts_and_rejects_the_rest():
    checked = check(PAGE, RAW)
    assert [e["summary"] for e in checked["events"]] == ["They leave for Ravnica."]
    event = checked["events"][0]
    assert event["participants"] == ["Jace Beleren", "Vraska"] and event["paragraph"] == 1 and event["location"] == "Ravnica"
    assert sorted(r["reason"] for r in checked["rejected"]) == ["quote not in page", "unlisted participant"]
    assert checked["relations"][0]["paragraph"] == 0 and checked["relations"][0]["target"] == "Jace Beleren"


def test_text_fragment_encodes_dashes_and_commas():
    assert text_fragment("https://x.test/a", "Hi - there, you") == "https://x.test/a#:~:text=Hi%20%2D%20there%2C%20you"
    long = text_fragment("https://x.test/a", "one two three four five six seven eight nine ten")
    assert long.endswith("#:~:text=one%20two%20three%20four,seven%20eight%20nine%20ten")


def test_build_joins_names_across_pages(tmp_path):
    (tmp_path / "stories").mkdir()
    (tmp_path / "stories" / "episode-1.json").write_text(json.dumps(PAGE))
    second = {**PAGE, "slug": "episode-2", "url": PAGE["url"].replace("1", "2"), "title": "Episode 2", "story_date": "2023-04-08", "storyline_nav": None}
    (tmp_path / "stories" / "episode-2.json").write_text(json.dumps(second))
    assert pending(tmp_path, {"stories/episode-1": PAGE}) == ["stories/episode-1"]
    (tmp_path / "extracted" / "stories").mkdir(parents=True)
    first = {"page": "stories/episode-1", "url": PAGE["url"], "title": "Episode 1", "story_date": "2023-04-01", **check(PAGE, RAW)}
    later = {
        "page": "stories/episode-2", "url": second["url"], "title": "Episode 2", "story_date": "2023-04-08",
        "storyline": "", "rejected": [], "relations": [],
        "entities": [{"name": "Jace", "type": "character", "aliases": ["the Mind Sculptor"], "description": "Jace, later.", "presence": "appears"}],
        "events": [{"summary": "Jace thinks.", "participants": ["Jace"], "location": "", "importance": "major", "paragraph": 0, "quote": "Jace looked at the sky."}],
    }
    (tmp_path / "extracted" / "stories" / "episode-1.json").write_text(json.dumps(first))
    (tmp_path / "extracted" / "stories" / "episode-2.json").write_text(json.dumps(later))

    report = build(tmp_path)
    assert report["entities"] == 3 and report["events"] == 2
    jace = json.loads((tmp_path / "index" / "entity" / "jace-beleren.json").read_text())
    assert jace["name"] == "Jace Beleren" and "the Mind Sculptor" in jace["aliases"]
    assert [e["summary"] for e in jace["timeline"]] == ["They leave for Ravnica.", "Jace thinks."]
    assert jace["first_seen"] == "2023-04-01" and jace["last_seen"] == "2023-04-08"
    assert jace["description"] == "Jace, later."
    names = json.loads((tmp_path / "index" / "names.json").read_text())
    assert names["the mind sculptor"] == ["jace-beleren"]
    storylines = json.loads((tmp_path / "index" / "storylines.json").read_text())
    assert storylines[0]["name"] == "March of the Machine"


def test_an_alias_joins_two_named_entities_only_when_it_shortens_the_name():
    assert _shortening("jace", "jace beleren")
    assert not _shortening("ashiok", "jace beleren")
    assert not _shortening("nissa revane", "phyrexian nissa revane")
    assert not _shortening("jace beleren", "jace beleren")


def test_citations_name_the_work_and_who_published_it():
    from mtglore.cite import citation

    story = {**PAGE, "authors": ["Alison Lührs"], "title": "Jace, Alone", "story_date": "2017-09-06"}
    c = citation(story, 1, "Vraska took his hand")
    assert c["text"] == '"Jace, Alone" by Alison Lührs. Magic Story, Wizards of the Coast, 6 Sep 2017.'
    assert c["official"] and c["link"].startswith(PAGE["url"] + "#:~:text=")
    card = {"kind": "cards", "source": "card-text", "title": "Invasion: card flavor text", "story_date": "2000-10-02",
            "url": "https://scryfall.com/sets/inv", "paragraphs": [{"text": "x", "card": "Urza's Rage", "url": "https://scryfall.com/card/inv/10"}]}
    c = citation(card, 0, "I will not be defeated")
    assert c["text"] == "Urza's Rage (Invasion, 2000), flavor text. Wizards of the Coast." and c["url"].endswith("/inv/10")
    wiki = {"kind": "wiki", "source": "mtg-wiki", "title": "Yawgmoth", "url": "https://mtg.wiki/page/Yawgmoth",
            "license": "CC BY-NC-SA 4.0", "paragraphs": [{"text": "x", "section": "Early life"}]}
    c = citation(wiki, 0, "born in the last century")
    assert not c["official"] and c["license"] == "CC BY-NC-SA 4.0"
    assert c["text"] == '"Yawgmoth", section "Early life". MTG Wiki contributors, CC BY-NC-SA 4.0.'
    archived = {"kind": "archive", "source": "wizards-archive", "title": "Ajani Faces", "story_date": "2008-10-27",
                "url": "https://web.archive.org/web/2015/http://www.wizards.com/x?x=mtg/daily/stf/1",
                "original_url": "http://www.wizards.com/x?x=mtg/daily/stf/1", "paragraphs": []}
    c = citation(archived)
    assert c["series"] == "Savor the Flavor" and c["archived"].startswith("https://web.archive.org/")
    assert c["text"] == '"Ajani Faces". Savor the Flavor, Wizards of the Coast, 27 Oct 2008. Archived by the Internet Archive.'


def test_an_old_column_saved_under_several_dates_is_one_page():
    def column(title):
        return {"kind": "archive", "title": title, "paragraphs": []}

    pages = {
        "savor-flavor-tropes-2009-04-01": column("Tropes"),
        "savor-flavor-tropes-2009-03-31": column("Tropes"),
        "savor-flavor-tropes-2009-03-31-0": column("Tropes"),
        "savor-flavor-other-2010-01-01": column("Other"),
    }
    assert duplicate_pages(pages) == {"savor-flavor-tropes-2009-04-01", "savor-flavor-tropes-2009-03-31-0"}
