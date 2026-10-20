from mtglore.app import Matcher, SetLinker, entity_markdown, key_entities, set_entity_markdown

ENTITIES = [
    {"id": "jace-beleren", "name": "Jace Beleren", "type": "character", "pages": 400, "description": "A planeswalker."},
    {"id": "ashiok", "name": "Ashiok", "type": "character", "pages": 30, "description": "A planeswalker."},
    {"id": "dominaria", "name": "Dominaria", "type": "plane", "pages": 300, "description": ""},
    {"id": "llanowar", "name": "Llanowar", "type": "location", "pages": 40, "description": ""},
    {"id": "kolaghan", "name": "Kolaghan", "type": "character", "pages": 20, "description": "A dragon."},
    {"id": "teferi", "name": "Teferi", "type": "character", "pages": 200, "description": "A planeswalker."},
]
# "ashiok" also lists Jace, as a wrong alias in the index would.
NAMES = {"jace": ["jace-beleren"], "jace beleren": ["jace-beleren"], "ashiok": ["ashiok", "jace-beleren"],
         "dominaria": ["dominaria"], "llanowar": ["llanowar"], "kolaghan": ["kolaghan"], "dragonlord kolaghan": ["kolaghan"],
         "teferi": ["teferi"]}


def card(name, type_line, sets=("dom",), faces=()):
    return {"oracle_id": name, "name": name, "type_line": type_line, "sets": list(sets), "faces": list(faces), "first_printed": "2018-04-27"}


def test_cards_map_to_the_entities_they_depict_and_only_when_confident():
    matcher = Matcher(ENTITIES, NAMES)
    assert matcher.match(card("Jace, the Mind Sculptor", "Legendary Planeswalker — Jace")) == ["jace-beleren"]
    assert matcher.match(card("Ashiok, Dream Render", "Legendary Planeswalker — Ashiok")) == ["ashiok"]
    assert matcher.match(card("Dragonlord Kolaghan", "Legendary Creature — Elder Dragon")) == ["kolaghan"]
    assert matcher.match(card("Llanowar", "Plane — Dominaria")) == ["dominaria", "llanowar"]
    assert matcher.match(card("Llanowar", "Land")) == ["llanowar"]
    # Not legendary: a creature named like a place says nothing about who it is.
    assert matcher.match(card("Llanowar Elves", "Creature — Elf Druid")) == []
    # Crossover printings only: someone else's character.
    assert matcher.match(card("Teferi, Hero of Dominaria", "Legendary Planeswalker — Teferi", sets=("sld",))) == []


SETS = [
    {"code": "dom", "name": "Dominaria", "released": "2018-04-27", "type": "expansion"},
    {"code": "war", "name": "War of the Spark", "released": "2019-05-03", "type": "expansion"},
    {"code": "9ed", "name": "Ninth Edition", "released": "2005-07-29", "type": "core"},
]


def event(page, who, storyline="", story_date="", era=None, importance="minor"):
    return {"id": f"{page}-e", "page": page, "participants": who, "storyline": storyline, "story_date": story_date,
            "era": era, "importance": importance}


def test_events_belong_to_the_set_that_told_them():
    linker = SetLinker(SETS)
    assert linker.event(event("cards/dom", [])) == "dom"
    assert linker.event(event("cards/9ed", [])) is None  # a reprint edition tells no story
    assert linker.event(event("wiki/x", [], era={"era": "war"})) == "war"
    assert linker.event(event("stories/x", [], storyline="The War of the Spark")) == "war"
    assert linker.event(event("stories/x", [], story_date="2018-04-10")) == "dom"


def test_a_sets_key_entities_put_its_characters_first():
    linker = SetLinker(SETS)
    pages = [
        {"id": "teferi", "timeline": [event("stories/a", ["teferi"], storyline="Dominaria", importance="major")] * 5, "pages_say": []},
        {"id": "dominaria", "timeline": [event("stories/a", ["dominaria"], storyline="Dominaria")] * 9, "pages_say": []},
        {"id": "jace-beleren", "timeline": [], "pages_say": [{"page": "cards/dom"}]},
    ]
    keyed = key_entities(pages, linker, {"teferi": "planeswalker", "dominaria": "plane", "jace-beleren": "planeswalker"})
    assert [(e["id"], e["role"]) for e in keyed["dom"]] == [("dominaria", "main"), ("teferi", "main"), ("jace-beleren", "supporting")]


def _teferi():
    official = {"official": True, "source": "wizards", "url": "https://example.com/a", "text": "\"A\". Magic Story."}
    wiki = {"official": False, "source": "mtg-wiki", "url": "https://mtg.wiki/page/Teferi", "text": "\"Teferi\". MTG Wiki contributors, CC BY-NC-SA 4.0."}
    return {
        "id": "teferi", "name": "Teferi", "type": "character", "description": "A time mage.",
        "bio": {"summary": {"text": "Teferi is a time mage.", "cites": ["teferi-e0"]}, "bio": [], "status": None},
        "timeline": [
            {"id": "teferi-e0", "summary": "Teferi phases out Zhalfir [[sic]]", "storyline": "Mirage", "story_date": "", "era": None,
             "page": "wiki/teferi", "importance": "major", "participants": ["teferi"], "location": "", "citation": wiki, "link": "https://mtg.wiki/page/Teferi#x"},
            {"id": "teferi-e1", "summary": "Teferi returns.", "storyline": "Dominaria", "story_date": "2018-04-10", "era": None,
             "page": "stories/a", "importance": "major", "participants": ["teferi"], "location": "", "citation": official, "link": "https://example.com/a#y"},
            {"id": "teferi-e2", "summary": "Teferi takes back his spark.", "storyline": "Dominaria", "story_date": "2018-04-17", "era": None,
             "page": "stories/b", "importance": "minor", "participants": ["teferi"], "location": "", "citation": official, "link": "https://example.com/b#z"},
        ],
        "relations": [],
        "pages_say": [],
    }


def test_an_entity_page_tells_its_story_set_by_set_as_prose():
    cards = [card("Teferi, Hero of Dominaria", "Legendary Planeswalker — Teferi")]
    narrative = {"sets": {"dom": [{"text": "Teferi comes home to Dominaria as [[Teferi, Hero of Dominaria]] and [[Not His Card]].", "cites": ["teferi-e1"]}]}}
    md = entity_markdown(_teferi(), "planeswalker", ["Dominaria"], cards, {"dom": "Dominaria"}, SetLinker(SETS), narrative)
    assert md.startswith("---\nid: teferi\nname: Teferi\ntype: planeswalker\ntitle: Teferi\nplanes: [Dominaria]\n")
    assert "## Who they are\n\nTeferi is a time mage.\n" in md
    # A set with a written narrative uses it; card links stay only for the entity's own cards.
    assert "### Dominaria\n\nTeferi comes home to Dominaria as [[Teferi, Hero of Dominaria]] and [Not His Card].\n" in md
    # Without one, its events are told as a paragraph.
    assert "### Mirage\n\nTeferi phases out Zhalfir [sic].\n" in md
    assert "(story)" not in md and "## Sources" not in md and "- " not in md.split(":::cards")[0]
    assert ":::cards\n[[Teferi, Hero of Dominaria]] Dominaria, 2018\n:::" in md
    # The wiki-sourced lines need the CC BY-NC-SA credit, once, in the front matter.
    assert md.count("CC BY-NC-SA 4.0") == 1 and "\ncredit: " in md.split("\n---\n")[0]


def test_a_set_page_has_the_entitys_paragraph_and_timeline_for_that_set():
    md = set_entity_markdown(_teferi(), "dom", "Dominaria", [], {"dom": "Dominaria"}, SetLinker(SETS))
    assert md.startswith("---\nid: teferi\nset: dom\nname: Teferi\ntitle: Teferi in Dominaria\n---\n")
    assert "## In Dominaria\n\nTeferi returns. Teferi takes back his spark.\n" in md
    assert "## Timeline\n\n- Teferi returns.\n- Teferi takes back his spark.\n" in md
    assert "credit:" not in md  # only official sources here


def test_narratives_keep_only_sentences_their_set_events_support():
    from mtglore.narratives import check_sentences
    known = {"e1": {"quote": "the stars fell like rain"}}
    rejected = []
    kept = check_sentences([
        {"text": "The sky broke.", "cites": ["e1"]},
        {"text": "It came from elsewhere.", "cites": ["e9"]},
        {"text": 'They said "the stars fell like rain".', "cites": ["e1"]},
        {"text": 'They said "the moon fell".', "cites": ["e1"]},
        {"text": "See [[Some Card]].", "cites": ["e1"]},
    ], known, set(), "dom", rejected)
    assert [k["text"] for k in kept] == ["The sky broke.", 'They said "the stars fell like rain".']
    assert [r["reason"] for r in rejected] == ["cites", "quote", "card"]
    rejected = []
    check_sentences([{"text": "One.", "cites": ["e1"]}] * 6, known, set(), "dom", rejected)
    assert [r["reason"] for r in rejected] == ["too long"]
