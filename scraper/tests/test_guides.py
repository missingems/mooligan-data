import json
from datetime import datetime, timedelta, timezone

from mtgmeta import guides

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
SLUG = "atraxa-praetors-voice"
EDHREC = "https://json.edhrec.com/pages/commanders"
SPELLBOOK = "https://backend.commanderspellbook.com/estimate-bracket"
CHANGERS = {card["name"]: card["oracle_id"] for card in guides.load_game_changers()}

CATALOG = {}


def add(name, type_line, text="", colours=(), mana_value=2.0, cost="{2}", price=1.0, oracle_id=None):
    CATALOG[guides.card_slug(name)] = {
        "name": name, "oracle_id": oracle_id or f"{guides.card_slug(name)}-oracle", "type_line": type_line, "oracle_text": text,
        "color_identity": list(colours), "mana_value": mana_value, "mana_cost": cost, "price": price,
    }


add("Atraxa, Praetors' Voice", "Legendary Creature — Phyrexian Angel Horror", "Flying, vigilance, deathtouch, lifelink", "WUBG", 4.0, "{G}{W}{U}{B}")
for basic in ("Plains", "Island", "Swamp", "Forest"):
    add(basic, f"Basic Land — {basic}", mana_value=0.0, cost="", price=0.25)
JOBS = {
    "ramp": ("Artifact", "{T}: Add {G}.", "{1}{G}"),
    "draw": ("Sorcery", "Draw two cards.", "{1}{U}"),
    "removal": ("Instant", "Destroy target creature.", "{1}{B}"),
    "counter": ("Instant", "Counter target spell.", "{U}{U}"),
    "wipe": ("Sorcery", "Destroy all creatures.", "{2}{W}{W}"),
    "protection": ("Instant", "Creatures you control gain hexproof until end of turn.", "{G}"),
    "payoff": ("Creature — Phyrexian", "Infect", "{2}{G}"),
    "land": ("Land", "{T}: Add {W} or {U}.", ""),
}
for job, (type_line, text, cost) in JOBS.items():
    for number in range(30 if job == "payoff" else 14):
        add(f"{job.title()} {number}", type_line, text, "G" if job in ("ramp", "payoff", "protection") else "", 0.0 if job == "land" else 2.0, cost)
for name in ("Demonic Tutor", "Vampiric Tutor", "Rhystic Study", "Smothering Tithe", "Cyclonic Rift"):
    add(name, "Sorcery", "Search your library for a card.", "B", 2.0, "{1}{B}", 30.0, CHANGERS[name])
add("Armageddon", "Sorcery", "Destroy all lands.", "W", 4.0, "{3}{W}")
add("Time Warp", "Sorcery", "Take an extra turn after this one.", "U", 5.0, "{3}{U}{U}")
add("Thassa's Oracle", "Creature — Merfolk Wizard", "When this enters, look at the top X cards.", "U", 2.0, "{U}{U}", 20.0, CHANGERS["Thassa's Oracle"])
add("Demonic Consultation", "Instant", "Exile cards from the top of your library.", "B", 1.0, "{B}")
add("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.", "R", 1.0, "{R}")
add("Mana Crypt", "Artifact", "{T}: Add {C}{C}.", "", 0.0, "{0}")

FILLERS = [entry["name"] for entry in CATALOG.values() if entry["name"].split()[0] in {job.title() for job in JOBS}]
POWER = ["Demonic Tutor", "Vampiric Tutor", "Rhystic Study", "Smothering Tithe", "Cyclonic Rift", "Armageddon", "Time Warp",
         "Thassa's Oracle", "Demonic Consultation", "Lightning Bolt"]


def rates(names, base=0.5):
    return {name: max(0.05, base - index * 0.004) for index, name in enumerate(names)}


def published(**changes):
    cards = [{"name": name, "decks": int(rate * 1000), "of_decks": 1000, "synergy": 0.1} for name, rate in rates(FILLERS + POWER).items()]
    page = {
        "schema": 1, "slug": SLUG, "name": "Atraxa, Praetors' Voice", "decks": 1000, "url": f"https://edhrec.com/commanders/{SLUG}",
        "color_identity": ["W", "U", "B", "G"], "scryfall_id": "atraxa-printing",
        "sections": [{"tag": "newcards", "header": "New Cards", "cards": [{"name": "Mana Crypt", "decks": 900, "of_decks": 1000}]},
                     {"tag": "creatures", "header": "Creatures", "cards": cards}],
        "average_deck": [],
        "themes": [{"slug": "infect", "name": "Infect", "decks": 400}, {"slug": "superfriends", "name": "Superfriends", "decks": 200},
                   {"slug": "tiny", "name": "Tiny", "decks": 12}],
        "bracket_decks": {"1": 5, "2": 300, "3": 400, "4": 250, "5": 45},
        "lands": 36, "basics": 26,
    }
    return {**page, **changes}


def edhrec_page(decks, inclusion, brackets=None, lands=36, basics=26):
    views = [{"name": name, "num_decks": int(rate * decks), "potential_decks": decks, "synergy": 0.2} for name, rate in inclusion.items()]
    return {
        "container": {"json_dict": {"card": {"num_decks": decks}, "cardlists": [{"tag": "creatures", "cardviews": views}]}},
        "bracket_counts": brackets or {}, "land": lands, "basic": basics,
    }


INFECT = {**rates(FILLERS, 0.6), "Payoff 29": 0.95, "Payoff 28": 0.9}
PAGES = {
    f"{EDHREC}/{SLUG}/infect.json": edhrec_page(400, INFECT, {"2": 150, "3": 200, "4": 50}),
    f"{EDHREC}/{SLUG}/superfriends.json": edhrec_page(200, rates(FILLERS, 0.5), {"3": 5}),
    f"{EDHREC}/{SLUG}/core.json": edhrec_page(300, rates(FILLERS, 0.5)),
    f"{EDHREC}/{SLUG}/upgraded.json": edhrec_page(400, {**rates(FILLERS, 0.5), "Rhystic Study": 0.9, "Smothering Tithe": 0.9, "Demonic Tutor": 0.9, "Vampiric Tutor": 0.9}),
    f"{EDHREC}/{SLUG}/optimized.json": edhrec_page(250, {**rates(FILLERS, 0.5), **{name: 0.99 for name in POWER}}),
    f"{EDHREC}/{SLUG}/cedh.json": edhrec_page(45, {**rates(FILLERS, 0.4), **{name: 0.99 for name in POWER}}),
    f"{EDHREC}/{SLUG}/exhibition.json": edhrec_page(5, {"Payoff 0": 1.0}),
}


def combo(id, names, tag, two_card=False, popularity=100):
    return {
        "combo": {
            "id": id, "status": "OK", "spoiler": False, "legalities": {"commander": True}, "bracketTag": tag, "popularity": popularity,
            "uses": [{"card": {"name": name, "oracleId": CATALOG[guides.card_slug(name)]["oracle_id"]}} for name in names],
            "requires": [], "produces": [{"feature": {"name": "Win the game", "status": "S"}}],
        },
        "definitelyTwoCard": two_card, "arguablyTwoCard": two_card, "relevant": True,
    }


class Spellbook:
    def __init__(self, fail=False):
        self.decks = []
        self.fail = fail

    def __call__(self, url, deck):
        assert url == SPELLBOOK
        if self.fail:
            raise OSError("Spellbook is down")
        self.decks.append(deck)
        names = {each["card"] for each in deck["main"]}
        flags = {"Armageddon": "massLandDenial", "Time Warp": "extraTurn", "Lightning Bolt": "banned"}
        return {
            "bracketTag": "R",
            "cards": [{"card": {"name": name}, "gameChanger": name in CHANGERS, **({flags[name]: True} if name in flags else {})} for name in names],
            "combos": [
                combo("oracle-consult", ["Thassa's Oracle", "Demonic Consultation"], "R", two_card=True, popularity=900),
                combo("casual-three", ["Payoff 0", "Payoff 1", "Payoff 2"], "E", popularity=50),
            ],
        }


class Fetch:
    def __init__(self, pages=None):
        self.urls = []
        self.pages = PAGES if pages is None else pages

    def __call__(self, url):
        self.urls.append(url)
        return self.pages.get(url)


def source(tmp_path):
    return guides.Source(tmp_path, "https://data.example", lambda url: None)


def setup(tmp_path, page=None):
    path = tmp_path / "edh" / "commanders" / f"{SLUG}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page or published()))


def build(tmp_path, fetch=None, spellbook=None, now=NOW, **options):
    if not (tmp_path / "edh" / "commanders" / f"{SLUG}.json").exists():
        setup(tmp_path)
    return guides.run(
        tmp_path, [SLUG], source(tmp_path), CATALOG, fetch_edhrec=fetch or Fetch(), post_spellbook=spellbook or Spellbook(),
        delay=0, now=lambda: now, **options,
    )


def guide(tmp_path):
    return json.loads((tmp_path / "edh" / "commanders" / SLUG / "guide.json").read_text())


def test_each_theme_with_enough_decks_is_a_play_style(tmp_path):
    result = build(tmp_path)

    assert result.written == [f"edh/commanders/{SLUG}/guide.json"] and not result.failed
    written = guide(tmp_path)
    assert (written["schema"], written["slug"], written["name"], written["generator"], written["model"]) == (1, SLUG, "Atraxa, Praetors' Voice", guides.GENERATOR, None)
    # Tiny has 12 decks, under the 30 a theme needs.
    assert [(style["id"], style["name"], style["decks"]) for style in written["styles"]] == [("infect", "Infect", 400), ("superfriends", "Superfriends", 200)]
    infect = written["styles"][0]
    assert infect["url"] == f"https://edhrec.com/commanders/{SLUG}/infect"
    assert infect["summary"].startswith("Infect is how 400 of Atraxa's 1,000 decks on EDHREC are built (40%). It leans on Payoff 29, Payoff 28")
    # Its brackets come from its own decks: a tenth or more at 2, 3 and 4.
    assert infect["brackets"] == [2, 3, 4]
    # Too few of Superfriends' decks say a bracket, so the commander's split stands in.
    assert written["styles"][1]["brackets"] == [2, 3, 4]


def test_every_style_has_a_whole_deck_for_each_of_its_brackets(tmp_path):
    build(tmp_path)

    for style in guide(tmp_path)["styles"]:
        assert [deck["level"] for deck in style["lists"]] == style["brackets"]
        for deck in style["lists"]:
            names = [card["name"] for card in deck["cards"]]
            basics = sum(basic["count"] for basic in deck["basics"])
            assert len(names) + basics == 99 and len(set(names)) == len(names)
            assert not {"Atraxa, Praetors' Voice", "Lightning Bolt", "Mana Crypt"} & set(names)
            assert deck["lands"] == 36 and {basic["name"] for basic in deck["basics"]} <= {"Plains", "Island", "Swamp", "Forest"}
            assert deck["price"] > 0
        lowest = {card["name"] for card in style["lists"][0]["cards"]}
        assert all(card["name"] in lowest and card["role"] != "land" for card in style["cards"]) and len(style["cards"]) <= 60
    # The style's cards are its theme's most played first.
    assert [card["name"] for card in guide(tmp_path)["styles"][0]["cards"][:2]] == ["Payoff 29", "Payoff 28"]


def test_the_decks_fill_the_app_builders_role_aims(tmp_path):
    build(tmp_path)

    roles = {}
    for card in guide(tmp_path)["styles"][0]["lists"][0]["cards"]:
        roles[card["role"]] = roles.get(card["role"], 0) + 1
    assert roles["ramp"] == 10 and roles["draw"] == 10 and roles.get("removal", 0) + roles.get("counter", 0) == 10
    assert roles["wipe"] == 3 and roles["protection"] == 3
    # EDHREC's decks play 10 nonbasic lands of their 36.
    assert roles["land"] == 10


def test_each_deck_keeps_its_brackets_rules(tmp_path):
    build(tmp_path)

    decks = {deck["level"]: deck for deck in guide(tmp_path)["styles"][0]["lists"]}
    two, three, four = ({card["name"] for card in decks[level]["cards"]} for level in (2, 3, 4))
    assert not two & set(CHANGERS) and decks[2]["game_changers"] == 0 and decks[2]["bracket"] <= 2
    assert len(three & set(CHANGERS)) == 3 and decks[3]["game_changers"] == 3 and decks[3]["bracket"] == 3
    assert "Armageddon" not in two | three and "Time Warp" not in two
    assert not {"Thassa's Oracle", "Demonic Consultation"} <= three
    # Bracket 4 holds anything legal, and its deck plays the two-card combo, whose pieces have the combo role.
    assert "Armageddon" in four and decks[4]["mass_land_denial"] == 1 and decks[4]["bracket"] == 4
    assert "oracle-consult" in decks[4]["combos"] and "oracle-consult" not in decks[3]["combos"]
    assert {card["role"] for card in decks[4]["cards"] if card["name"] in ("Thassa's Oracle", "Demonic Consultation")} == {"combo"}


def test_combos_are_spellbooks_with_two_card_ones_kept_from_bracket_three(tmp_path):
    spellbook = Spellbook()
    build(tmp_path, spellbook=spellbook)

    combos = {each["id"]: each for each in guide(tmp_path)["combos"]}
    assert combos["oracle-consult"]["bracket"] == 4 and combos["oracle-consult"]["two_card"] is True
    assert combos["casual-three"]["bracket"] == 1 and combos["casual-three"]["two_card"] is False
    assert [card["name"] for card in combos["oracle-consult"]["cards"]] == ["Thassa's Oracle", "Demonic Consultation"]
    # One estimate for the whole pool: the commander, and every card it may play from all its pages.
    assert len(spellbook.decks) == 1
    deck = spellbook.decks[0]
    assert deck["commanders"] == [{"card": "Atraxa, Praetors' Voice"}]
    main = {each["card"] for each in deck["main"]}
    assert {"Payoff 29", "Thassa's Oracle"} <= main and "Mana Crypt" not in main


def test_a_card_spellbook_calls_banned_is_left_out(tmp_path):
    build(tmp_path)

    names = {card["name"] for style in guide(tmp_path)["styles"] for deck in style["lists"] for card in deck["cards"]}
    names |= {card["name"] for bracket in guide(tmp_path)["brackets"] for card in bracket["cards"]}
    assert "Lightning Bolt" not in names


def test_the_five_brackets_name_what_sets_each_apart(tmp_path):
    build(tmp_path)

    brackets = guide(tmp_path)["brackets"]
    assert [(bracket["level"], bracket["name"]) for bracket in brackets] == [(1, "Exhibition"), (2, "Core"), (3, "Upgraded"), (4, "Optimized"), (5, "cEDH")]
    upgraded = brackets[2]
    assert upgraded["decks"] == 400
    assert len({card["name"] for card in upgraded["cards"]} & set(CHANGERS)) == 3
    assert upgraded["summary"].startswith("400 of Atraxa's decks on EDHREC are built for Bracket 3, Upgraded. Up to three Game Changers")
    # Bracket 1 has 5 decks, too few, so the nearest bracket with enough stands in, within bracket 1's rules.
    assert not {card["name"] for card in brackets[0]["cards"]} & set(CHANGERS)
    assert all(len(bracket["cards"]) <= 30 for bracket in brackets)


def test_a_guide_is_built_again_only_when_due(tmp_path):
    build(tmp_path)
    state = json.loads((tmp_path / "state" / "guides.json").read_text())
    assert state[SLUG]["generator"] == guides.GENERATOR and state[SLUG]["built_at"] == "2026-10-21T14:00:00Z" and state[SLUG]["decks"] == 1000

    fetch = Fetch()
    assert build(tmp_path, fetch=fetch, now=NOW + timedelta(days=6)).unchanged == [SLUG] and fetch.urls == []
    assert build(tmp_path, now=NOW + timedelta(days=7)).written

    later = NOW + timedelta(days=8)
    setup(tmp_path, published(decks=1200))
    assert build(tmp_path, now=later).written
    setup(tmp_path, published(decks=1250, themes=[{"slug": "infect", "name": "Infect", "decks": 400}]))
    assert build(tmp_path, now=later).written
    assert build(tmp_path, now=later).unchanged == [SLUG]
    assert build(tmp_path, now=later, force=True).written


def test_a_run_builds_the_never_built_first_and_leaves_the_rest_for_later(tmp_path):
    state = {SLUG: {"generator": "data-1", "fingerprint": "old", "built_at": "2026-10-01T00:00:00Z", "decks": 1000}}
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "guides.json").write_text(json.dumps(state))
    setup(tmp_path)
    (tmp_path / "edh" / "commanders" / "atraxa-grand-unifier.json").write_text(json.dumps(published(name="Atraxa, Grand Unifier")))

    result = guides.run(
        tmp_path, [SLUG, "atraxa-grand-unifier"], source(tmp_path), CATALOG,
        fetch_edhrec=Fetch({}), post_spellbook=Spellbook(), delay=0, now=lambda: NOW, limit=1,
    )

    assert result.written == ["edh/commanders/atraxa-grand-unifier/guide.json"] and result.deferred == [SLUG]


def test_style_ids_are_edhrecs_theme_slugs_so_counters_themes_stay_apart(tmp_path):
    themes = [{"slug": "plus-1-plus-1-counters", "name": "+1/+1 Counters", "decks": 400}, {"slug": "minus-1-minus-1-counters", "name": "-1/-1 Counters", "decks": 300}]
    setup(tmp_path, published(themes=themes))
    pages = {**PAGES, f"{EDHREC}/{SLUG}/plus-1-plus-1-counters.json": PAGES[f"{EDHREC}/{SLUG}/infect.json"],
             f"{EDHREC}/{SLUG}/minus-1-minus-1-counters.json": PAGES[f"{EDHREC}/{SLUG}/infect.json"]}

    build(tmp_path, fetch=Fetch(pages))

    assert [(style["id"], style["name"]) for style in guide(tmp_path)["styles"]] == [
        ("plus-1-plus-1-counters", "+1/+1 Counters"), ("minus-1-minus-1-counters", "-1/-1 Counters")]


def test_every_combo_a_deck_names_is_in_the_guide(tmp_path):
    build(tmp_path)

    written = guide(tmp_path)
    ids = {combo["id"] for combo in written["combos"]}
    assert {each for style in written["styles"] for deck in style["lists"] for each in deck["combos"]} == ids


def test_a_commander_spellbook_cannot_read_is_not_written(tmp_path):
    result = build(tmp_path, spellbook=Spellbook(fail=True))

    assert result.failed == [SLUG] and not (tmp_path / "edh" / "commanders" / SLUG).exists()
    assert not (tmp_path / "state" / "guides.json").exists()


def test_a_commander_with_no_theme_pages_gets_the_average_deck(tmp_path):
    build(tmp_path, fetch=Fetch({}))

    styles = guide(tmp_path)["styles"]
    assert [(style["id"], style["name"], style["decks"]) for style in styles] == [("average-deck", "Average Deck", 1000)]
    assert styles[0]["summary"].startswith("The cards most of Atraxa's 1,000 decks on EDHREC play.")
    assert styles[0]["url"] == f"https://edhrec.com/commanders/{SLUG}"


def test_a_page_published_before_it_had_themes_is_read_again_from_edhrec(tmp_path):
    old = published()
    for key in ("themes", "bracket_decks", "lands", "basics"):
        old.pop(key)
    setup(tmp_path, old)
    body = edhrec_page(1000, rates(FILLERS, 0.5), {"3": 900})
    body["container"]["json_dict"]["card"].update({"name": "Atraxa, Praetors' Voice", "color_identity": ["W", "U", "B", "G"]})
    body["tag_counts"] = [{"slug": "infect", "value": "Infect", "count": 400}]
    fetch = Fetch({**PAGES, f"{EDHREC}/{SLUG}.json": body})

    build(tmp_path, fetch=fetch)

    assert fetch.urls[0] == f"{EDHREC}/{SLUG}.json"
    assert [style["id"] for style in guide(tmp_path)["styles"]] == ["infect"]


def test_polish_replaces_only_what_it_returns(tmp_path):
    def polish(written):
        return {**written, "model": "claude-test", "styles": [{**style, "summary": "Prose."} for style in written["styles"]]}

    build(tmp_path, polish=polish)

    written = guide(tmp_path)
    assert written["model"] == "claude-test" and {style["summary"] for style in written["styles"]} == {"Prose."}
    assert json.loads((tmp_path / "state" / "guides.json").read_text())[SLUG]["model"] == "claude-test"


def test_the_command_builds_the_top_commanders(tmp_path, capsys):
    setup(tmp_path)
    top = {"schema": 1, "windows": {"7d": {"commanders": [{"rank": 1, "slug": SLUG}]}, "30d": {"commanders": [{"rank": 1, "slug": "other"}]}}}
    (tmp_path / "edh" / "top.json").write_text(json.dumps(top))

    code = guides.main([str(tmp_path), "--top", "1", "--delay", "0"], load_catalog=lambda: CATALOG, fetch_edhrec=Fetch(), post_spellbook=Spellbook())

    assert code == 0 and "1 written, 0 unchanged, 0 failed" in capsys.readouterr().out


def test_polish_without_a_key_stops_the_command(tmp_path, caplog):
    setup(tmp_path)
    assert guides.main([str(tmp_path), "--slug", SLUG, "--polish"], load_catalog=lambda: CATALOG, make_polisher=lambda: None) == 2
    assert "--polish needs ANTHROPIC_API_KEY" in caplog.text


def test_top_takes_the_weeks_commanders_first():
    top = {"windows": {"7d": {"commanders": [{"slug": "a"}, {"slug": "b"}]}, "30d": {"commanders": [{"slug": "c"}, {"slug": "a"}]}}}
    assert guides.commander_slugs(top, 3) == ["a", "b", "c"]
    assert guides.commander_slugs(None, 5) == []


def test_the_game_changers_file_names_each_card_with_its_oracle_id():
    cards = guides.load_game_changers()
    assert len(cards) == 53
    assert all(card["name"] and len(card["oracle_id"]) == 36 for card in cards)


def test_pages_missing_locally_come_from_the_live_site(tmp_path):
    requested = []
    live = guides.Source(tmp_path, "https://data.example/", lambda url: requested.append(url) or {"name": "live"})
    assert live.read(f"edh/commanders/{SLUG}.json") == {"name": "live"}
    assert requested == [f"https://data.example/edh/commanders/{SLUG}.json"]
