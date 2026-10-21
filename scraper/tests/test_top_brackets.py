import json
from datetime import datetime, timedelta, timezone

from mtgmeta import top_brackets
from mtgmeta.top import build_top
from mtgmeta.top_brackets import Counts, cached_edhtop16, edhrec_slugs, edhtop16_rows, rank_brackets

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
EDHREC = "https://json.edhrec.com/pages/commanders"


def page(name, decks, brackets):
    return {"container": {"json_dict": {"card": {"name": name, "num_decks": decks}}}, "bracket_counts": brackets}


PAGES = {
    f"{EDHREC}/atraxa.json": page("Atraxa, Praetors' Voice", 40000, {"1": 50, "2": 3000, "3": 5000, "4": 900, "5": 100}),
    f"{EDHREC}/krenko.json": page("Krenko, Mob Boss", 30000, {"1": 80, "2": 4000, "3": 3000, "4": 700, "5": 20}),
    f"{EDHREC}/kraum-ludevics-opus-tymna-the-weaver.json": page("Kraum, Ludevic's Opus // Tymna the Weaver", 12131, {"5": 4142, "4": 255}),
    f"{EDHREC}/etali-primal-conqueror.json": page("Etali, Primal Conqueror", 17393, {"3": 981, "5": 2532}),
}


class Fetch:
    def __init__(self, pages=PAGES):
        self.urls, self.pages = [], pages

    def __call__(self, url):
        self.urls.append(url)
        return self.pages.get(url)


EDHTOP16 = [
    {"name": "Kraum, Ludevic's Opus / Tymna the Weaver", "entries": 1051, "top_cuts": 309, "conversion_rate": 29.4},
    {"name": "Nobody Edhrec Knows", "entries": 500, "top_cuts": 10, "conversion_rate": 2.0},
    {"name": "Etali, Primal Conqueror // Etali, Primal Sickness", "entries": 120, "top_cuts": 30, "conversion_rate": 25.0},
]


def test_edhtop16_names_become_edhrec_slugs():
    assert edhrec_slugs("Kraum, Ludevic's Opus / Tymna the Weaver") == ["kraum-ludevics-opus-tymna-the-weaver", "tymna-the-weaver-kraum-ludevics-opus"]
    # EDHREC orders a pair alphabetically, whatever order EDHTop16 gives it.
    assert edhrec_slugs("Tymna the Weaver / Kraum, Ludevic's Opus")[0] == "kraum-ludevics-opus-tymna-the-weaver"
    assert edhrec_slugs("Etali, Primal Conqueror // Etali, Primal Sickness") == ["etali-primal-conqueror"]
    assert edhrec_slugs("Kinnan, Bonder Prodigy") == ["kinnan-bonder-prodigy"]


def test_brackets_one_to_four_rank_edhrecs_decks_and_cedh_ranks_tournament_entries(tmp_path):
    fetch = Fetch()
    brackets = rank_brackets(tmp_path, ["atraxa", "krenko", "etali-primal-conqueror", "gone"], NOW, fetch_edhrec=fetch, read_edhtop16=lambda: EDHTOP16, delay=0)

    assert [row["slug"] for row in brackets[2]["rows"]] == ["krenko", "atraxa"]
    assert [row["slug"] for row in brackets[3]["rows"]] == ["atraxa", "krenko", "etali-primal-conqueror"]
    assert brackets[3]["rows"][0] == {"slug": "atraxa", "name": "Atraxa, Praetors' Voice", "decks": 5000, "of_decks": 40000}
    assert brackets[5]["source"] == "edhtop16" and brackets[5]["window"] == "3m"
    # Etali has more EDHREC "cEDH" decks than Atraxa, but tournaments rank Kraum and Tymna first; one EDHREC lacks is left out.
    assert brackets[5]["rows"] == [
        {"slug": "kraum-ludevics-opus-tymna-the-weaver", "name": "Kraum, Ludevic's Opus // Tymna the Weaver", "entries": 1051,
         "top_cuts": 309, "conversion_rate": 29.4, "decks": 4142, "of_decks": 12131},
        {"slug": "etali-primal-conqueror", "name": "Etali, Primal Conqueror", "entries": 120, "top_cuts": 30, "conversion_rate": 25.0,
         "decks": 2532, "of_decks": 17393},
    ]


def test_cedh_is_matched_before_the_candidates_use_up_the_runs_pages(tmp_path):
    fetch = Fetch()
    brackets = rank_brackets(tmp_path, ["atraxa", "krenko"], NOW, fetch_edhrec=fetch, read_edhtop16=lambda: EDHTOP16, limit=2, delay=0)
    assert [row["slug"] for row in brackets[5]["rows"]] == ["kraum-ludevics-opus-tymna-the-weaver"]
    assert fetch.urls[0] == f"{EDHREC}/kraum-ludevics-opus-tymna-the-weaver.json"


def test_cedh_falls_back_to_edhrecs_counts_when_edhtop16_cannot_be_read(tmp_path):
    brackets = rank_brackets(tmp_path, ["atraxa", "krenko", "etali-primal-conqueror"], NOW, fetch_edhrec=Fetch(), read_edhtop16=lambda: None, delay=0)
    assert brackets[5]["source"] == "edhrec" and [row["slug"] for row in brackets[5]["rows"]] == ["etali-primal-conqueror", "atraxa", "krenko"]


def test_counts_come_from_this_runs_pages_then_the_cache_then_edhrec_a_few_a_run(tmp_path):
    written = tmp_path / "edh" / "commanders" / "atraxa.json"
    written.parent.mkdir(parents=True)
    written.write_text(json.dumps({"name": "Atraxa, Praetors' Voice", "decks": 41000, "bracket_decks": {"3": 5100}}))
    fetch = Fetch()
    counts = Counts(tmp_path, NOW, fetch, limit=1, delay=0)

    assert counts.get("atraxa")["bracket_decks"] == {"3": 5100}
    assert counts.get("krenko")["name"] == "Krenko, Mob Boss"
    assert counts.get("etali-primal-conqueror") is None  # past the run's limit
    assert fetch.urls == [f"{EDHREC}/krenko.json"]
    counts.save()

    later = Counts(tmp_path, NOW + timedelta(days=3), Fetch(), limit=5, delay=0)
    assert later.get("krenko")["decks"] == 30000 and later.fetch.urls == []
    stale = Counts(tmp_path, NOW + timedelta(days=8), Fetch(), limit=5, delay=0)
    assert stale.get("krenko") and stale.fetch.urls == [f"{EDHREC}/krenko.json"]


def test_a_commander_edhrec_has_no_page_for_is_not_asked_for_again_all_week(tmp_path):
    counts = Counts(tmp_path, NOW, Fetch(), delay=0)
    assert counts.get("gone") is None
    counts.save()
    again = Counts(tmp_path, NOW + timedelta(days=1), Fetch(), delay=0)
    assert again.get("gone") is None and again.fetch.urls == []


def test_edhtop16_is_asked_with_its_sites_query_and_read_again_with_the_current_id_when_it_changed():
    asked = []

    def post(url, body):
        asked.append(body["extensions"]["pastoria-id"])
        if body["extensions"]["pastoria-id"] != "new-id":
            return {"errors": ["Unknown persisted query"]}
        assert url == "https://edhtop16.com/api/graphql" and body["query"] is None
        assert body["variables"]["timePeriod"] == "THREE_MONTHS" and body["variables"]["minSize"] == 30
        node = {"name": "Kinnan, Bonder Prodigy", "stats": {"count": 157, "topCuts": 37, "conversionRate": 0.2356, "metaShare": 0.05}}
        return {"data": {"commanders": {"edges": [{"node": node}, {"node": {"name": "No stats"}}]}}}

    rows = edhtop16_rows(post, find_id=lambda: "new-id")
    assert asked == [top_brackets.EDHTOP16_QUERY_ID, "new-id"]
    assert rows == [{"name": "Kinnan, Bonder Prodigy", "entries": 157, "top_cuts": 37, "conversion_rate": 23.6}]


def test_the_query_id_is_read_from_the_sites_page_script():
    script = 'params:{id:`0123456789abcdef0123456789abcdef`,metadata:{},name:`TopCommandersQuery`,operationKind:`query`}'
    texts = {"https://edhtop16.com/": '<script type="module" src="/assets/page-AbC_1.js">', "https://edhtop16.com/assets/page-AbC_1.js": script}
    assert top_brackets.query_id(texts.__getitem__) == "0123456789abcdef0123456789abcdef"


def test_edhtop16_is_cached_for_a_day_and_a_weeks_read_stands_in_when_it_fails(tmp_path):
    reads = []
    assert cached_edhtop16(tmp_path, NOW, lambda: reads.append(1) or EDHTOP16) == EDHTOP16
    assert cached_edhtop16(tmp_path, NOW + timedelta(hours=10), lambda: reads.append(1) or None) == EDHTOP16 and len(reads) == 1
    assert cached_edhtop16(tmp_path, NOW + timedelta(days=2), lambda: None) == EDHTOP16
    assert cached_edhtop16(tmp_path, NOW + timedelta(days=8), lambda: None) is None


def test_top_json_gets_each_brackets_ranked_commanders_beside_the_windows(tmp_path):
    windows = {"7d": [{"rank": 1, "slug": "atraxa", "name": "Atraxa, Praetors' Voice", "decks": 10, "trend": 1.0}]}
    brackets = rank_brackets(tmp_path, ["atraxa", "krenko"], NOW, fetch_edhrec=Fetch(), read_edhtop16=lambda: EDHTOP16, delay=0)
    catalog = {"atraxa-praetors-voice": {"name": "Atraxa, Praetors' Voice", "oracle_id": "atraxa-oracle", "scryfall_id": "atraxa-print", "color_identity": ["W", "U", "B", "G"]}}

    document = build_top(windows, NOW, catalog, brackets)

    assert list(document["windows"]) == ["7d"] and list(document["brackets"]) == ["1", "2", "3", "4", "5"]
    two = document["brackets"]["2"]
    assert (two["name"], two["source"], two["decks"]) == ("Core", "edhrec", 7000)
    assert two["commanders"][1] == {
        "rank": 2, "slug": "atraxa", "name": "Atraxa, Praetors' Voice", "decks": 3000, "of_decks": 40000, "share": 42.9,
        "color_identity": ["W", "U", "B", "G"], "oracle_id": "atraxa-oracle", "scryfall_id": "atraxa-print",
    }
    cedh = document["brackets"]["5"]
    # Etali is no candidate of brackets 1 to 4 here, but its EDHREC page is read to match EDHTop16's entry.
    assert (cedh["name"], cedh["source"], cedh["window"], cedh["entries"]) == ("cEDH", "edhtop16", "3m", 1171)
    assert cedh["commanders"][0]["share"] == 89.8 and cedh["commanders"][0]["oracle_id"] is None
    assert "brackets" not in build_top(windows, NOW)


def test_bracket_slugs_reads_a_published_top_json():
    top = {"brackets": {"2": {"commanders": [{"slug": "b"}, {"slug": "a"}]}, "1": {"commanders": [{"slug": "a"}]}}}
    assert top_brackets.bracket_slugs(top) == ["a", "b"]
    assert top_brackets.bracket_slugs(None) == [] and top_brackets.bracket_slugs({"windows": {}}) == []
