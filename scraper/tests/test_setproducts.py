import json
import urllib.error
from datetime import datetime, timezone

import pytest

import mtgmeta.__main__ as entry
import mtgmeta.setproducts as setproducts
from mtgmeta.models import RunReport
from mtgmeta.setproducts import (
    BASE_URL, LAST_UPDATED_URL, SETS_URL, Group, SetInfo, classify, image_loads, larger_image, match_groups, needs_read,
    parse_groups, parse_sets, prices_by_product, read_state, sealed_products, write_set_products,
)

NOW = datetime(2026, 10, 20, 9, 30, 0, tzinfo=timezone.utc)
BUILT = "2026-10-19T20:06:15+0000"
CDN = "https://tcgplayer-cdn.tcgplayer.com/product"


def scryfall(*sets):
    data = [{"code": code, "name": name, "released_at": released, "set_type": kind, "digital": digital} for code, name, released, kind, digital in sets]
    return json.dumps({"object": "list", "data": data}).encode()


SETS = scryfall(
    ("fra", "Reality Fracture", "2026-10-02", "expansion", False),
    ("frc", "Reality Fracture Commander", "2026-10-02", "commander", False),
    ("trk", "Star Trek", "2026-11-13", "expansion", False),
    ("blb", "Bloomburrow", "2024-08-02", "expansion", False),
    ("moc", "March of the Machine Commander", "2023-04-21", "commander", False),
    ("who", "Doctor Who", "2023-10-13", "expansion", False),
    ("ltr", "The Lord of the Rings: Tales of Middle-earth", "2023-06-23", "expansion", False),
    ("tfra", "Reality Fracture Tokens", "2026-10-02", "token", False),
    ("mkm", "Murders at Karlov Manor", "2024-02-09", "expansion", False),
    ("old", "Old Set", "2019-01-01", "expansion", False),
    ("dig", "Digital Set", "2026-01-01", "expansion", True),
    ("nup", "No Products", "2026-02-02", "expansion", False),
)

GROUPS = [
    {"groupId": 1, "name": "Reality Fracture", "abbreviation": "FRA", "modifiedOn": "2026-10-13T00:00:00"},
    {"groupId": 2, "name": "Commander: Reality Fracture", "abbreviation": "FRC", "modifiedOn": "2026-10-13T00:00:00"},
    {"groupId": 3, "name": "Star Trek", "abbreviation": "TRK", "modifiedOn": "2026-10-13T00:00:00"},
    {"groupId": 4, "name": "Bloomburrow", "abbreviation": "BLB", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 5, "name": "Commander: March of the Machine", "abbreviation": "MOC", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 6, "name": "Planechase: March of the Machine", "abbreviation": "MOC", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 7, "name": "Planechase: Universes Beyond: Doctor Who", "abbreviation": "WHO", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 8, "name": "Universes Beyond: Doctor Who", "abbreviation": "WHO", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 9, "name": "Universes Beyond: The Lord of the Rings: Tales of Middle-earth", "abbreviation": "LTR", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 10, "name": "Murders at Karlov Manor", "abbreviation": "MKM", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 11, "name": "Magic Player Rewards", "abbreviation": "MPRP", "modifiedOn": "2025-01-01T00:00:00"},
    {"groupId": 12, "name": "Old Set", "abbreviation": "OLD", "modifiedOn": "2025-01-01T00:00:00"},
]


def product(identifier, name, sealed=True, images=1, image=None):
    extended = [{"name": "OracleText", "value": "x"}] if sealed else [{"name": "Number", "value": "12/200"}, {"name": "Rarity", "value": "R"}]
    return {
        "productId": identifier, "name": name, "imageUrl": image or f"{CDN}/{identifier}_200w.jpg", "imageCount": images,
        "url": f"https://www.tcgplayer.com/product/{identifier}/magic-x", "extendedData": extended,
    }


def price(identifier, market=None, mid=None, sub="Normal"):
    return {"productId": identifier, "marketPrice": market, "midPrice": mid, "lowPrice": 1.0, "subTypeName": sub}


FRA_PRODUCTS = [
    product(11, "Reality Fracture - Collector Booster Display"),
    product(12, "Reality Fracture - Play Booster Display"),
    product(13, "Reality Fracture - Bundle"),
    product(14, "Reality Fracture - Play Booster"),
    product(15, "Reality Fracture - Prerelease Pack"),
    product(16, "Reality Fracture - Play Booster Display (Japanese)"),
    product(17, "Reality Fracture - Not Out Yet", images=0),
    product(18, "Lightning Bolt", sealed=False),
    product(19, "Reality Fracture - Missing Picture"),
]
FRA_PRICES = [price(11, market=434.72), price(12, market=130.94, mid=140.0), price(13, mid=48.27), price(14, market=6.03), price(15, market=32.97),
              price(11, market=999.0, sub="Foil")]
FRC_PRODUCTS = [product(21, "Reality Fracture Commander Deck - Multiverse Reforged")]
TRK_PRODUCTS = [product(31, "Star Trek - Play Booster Display")]


class Tcgcsv:
    """Stands in for TCGCSV: its files by URL, and a record of what was asked for."""

    def __init__(self, groups=GROUPS, built=BUILT):
        self.files = {
            LAST_UPDATED_URL: built.encode(),
            f"{BASE_URL}/groups": json.dumps({"success": True, "results": groups}).encode(),
        }
        for group, products, prices in ((1, FRA_PRODUCTS, FRA_PRICES), (2, FRC_PRODUCTS, []), (3, TRK_PRODUCTS, []), (4, [product(41, "Bloomburrow - Bundle")], [price(41, market=40.0)]),
                                        (5, [], []), (8, [product(81, "Doctor Who - Bundle")], [price(81, market=30.0)]), (9, [product(91, "Tales of Middle-earth - Starter Kit")], [price(91, market=10.0)]),
                                        (10, [product(101, "Murders at Karlov Manor - Bundle", sealed=False)], [])):
            self.files[f"{BASE_URL}/{group}/products"] = json.dumps({"results": products}).encode()
            self.files[f"{BASE_URL}/{group}/prices"] = json.dumps({"results": prices}).encode()
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        found = self.files[url]
        if isinstance(found, Exception):
            raise found
        return found

    def reads(self):
        return sorted({url.split("/")[-2] for url in self.asked if url.endswith("/products")}, key=int)


def loads(url):
    return "19_" not in url


def run(tmp_path, tcgcsv=None, sets=SETS, now=NOW, check=loads):
    tcgcsv = tcgcsv or Tcgcsv()
    written = write_set_products(tmp_path, now, tcgcsv, lambda url: sets, check)
    return written, tcgcsv


def products_of(tmp_path, code):
    return json.loads((tmp_path / "sets" / "products" / f"{code}.json").read_text())


def test_a_sets_file_lists_its_sealed_products_in_the_contracts_shape(tmp_path):
    written, _ = run(tmp_path)
    assert "sets/products/fra.json" in written
    assert products_of(tmp_path, "fra") == {
        "schema": 1,
        "set": "fra",
        "generated_at": "2026-10-20T09:30:00Z",
        "products": [
            {"name": "Reality Fracture - Play Booster Display", "kind": "booster-box", "image": f"{CDN}/12_400w.jpg", "url": "https://www.tcgplayer.com/product/12/magic-x", "price": 130.94},
            {"name": "Reality Fracture - Collector Booster Display", "kind": "collector-booster-box", "image": f"{CDN}/11_400w.jpg", "url": "https://www.tcgplayer.com/product/11/magic-x", "price": 434.72},
            {"name": "Reality Fracture - Bundle", "kind": "bundle", "image": f"{CDN}/13_400w.jpg", "url": "https://www.tcgplayer.com/product/13/magic-x", "price": 48.27},
            {"name": "Reality Fracture - Play Booster", "kind": "play-booster", "image": f"{CDN}/14_400w.jpg", "url": "https://www.tcgplayer.com/product/14/magic-x", "price": 6.03},
            {"name": "Reality Fracture - Prerelease Pack", "kind": "prerelease", "image": f"{CDN}/15_400w.jpg", "url": "https://www.tcgplayer.com/product/15/magic-x", "price": 32.97},
        ],
    }


def test_cards_foreign_products_and_products_without_a_picture_are_left_out(tmp_path):
    run(tmp_path)
    names = [item["name"] for item in products_of(tmp_path, "fra")["products"]]
    assert "Lightning Bolt" not in names
    assert not any("Japanese" in name or "Not Out Yet" in name or "Missing Picture" in name for name in names)


def test_a_set_with_no_sealed_products_has_no_file(tmp_path):
    written, _ = run(tmp_path)
    assert not (tmp_path / "sets" / "products" / "mkm.json").exists()
    assert not (tmp_path / "sets" / "products" / "moc.json").exists()
    assert sorted(written) == ["sets/products/blb.json", "sets/products/fra.json", "sets/products/frc.json", "sets/products/ltr.json", "sets/products/trk.json", "sets/products/who.json"]


def test_an_upcoming_set_gets_a_file_and_an_old_set_does_not(tmp_path):
    run(tmp_path)
    assert (tmp_path / "sets" / "products" / "trk.json").exists()
    assert not (tmp_path / "sets" / "products" / "old.json").exists()


def test_a_product_with_no_price_yet_has_a_null_price(tmp_path):
    run(tmp_path)
    assert products_of(tmp_path, "trk")["products"][0]["price"] is None


def test_the_best_group_serves_a_set_when_two_share_an_abbreviation():
    sets = parse_sets(json.loads(SETS), "2026-10-20")
    matched = match_groups(sets, parse_groups({"results": GROUPS}))
    assert matched["moc"].id == 5
    assert matched["who"].id == 8
    assert matched["ltr"].id == 9


def test_groups_are_matched_by_abbreviation_then_by_name():
    sets = [SetInfo("zzz", "Star Trek: Stardates", "2026-11-13"), SetInfo("aaa", "Star Trek", "2026-11-13")]
    groups = [Group(1, "Star Trek: Stardates", "sds", ""), Group(2, "Star Trek", "trk", "")]
    matched = match_groups(sets, groups)
    assert matched["zzz"].id == 1
    assert matched["aaa"].id == 2
    assert match_groups([SetInfo("sds", "Stardates", "2026-11-13")], [Group(1, "Star Trek: Stardates", "sds", "")])["sds"].id == 1
    assert match_groups([SetInfo("slp", "Secret Lair Promo", "2023-02-17")], [Group(1, "Secret Lair Showdown", "slp", "")]) == {}


def test_sets_are_the_paper_ones_since_2023_and_the_upcoming_ones():
    codes = [info.code for info in parse_sets(json.loads(SETS), "2026-10-20")]
    assert "old" not in codes and "dig" not in codes and "tfra" not in codes
    assert {"fra", "trk", "moc"} <= set(codes)


@pytest.mark.parametrize("name, kind", [
    ("Reality Fracture - Play Booster Display", "booster-box"),
    ("Commander Masters - Draft Booster Box", "booster-box"),
    ("Commander Masters - Set Booster Box", "booster-box"),
    ("Marvel: Darkhold Destiny - Booster Display", "booster-box"),
    ("Reality Fracture - Collector Booster Display", "collector-booster-box"),
    ("Commander Masters - Collector Booster Box", "collector-booster-box"),
    ("Reality Fracture - Bundle", "bundle"),
    ("The Hobbit - Gift Bundle", "bundle"),
    ("Reality Fracture - Play Booster", "play-booster"),
    ("The Hobbit - Play Booster Pack", "play-booster"),
    ("The Hobbit - Sleeved Play Booster Pack", "play-booster"),
    ("Marvel: Darkhold Destiny - Booster Pack", "play-booster"),
    ("Reality Fracture - Collector Booster", "collector-booster"),
    ("March of the Machine - Collector Booster Pack", "collector-booster"),
    ("Reality Fracture - Prerelease Pack", "prerelease"),
    ("Reality Fracture Commander Deck - Multiverse Reforged", "commander-deck"),
    ("Phyrexia: All Will Be One Commander Decks [Set of 2]", "commander-deck"),
    ("FINAL FANTASY - Starter Kit", "starter-kit"),
    ("Reality Fracture - Draft Night", "other"),
    ("The Hobbit Scene Box - Crack the Plates", "other"),
    ("March of the Machine - Draft Booster Pack", "other"),
    ("March of the Machine - Set Booster Pack", "other"),
    ("Reality Fracture - Play Booster Display Case", "other"),
    ("Reality Fracture - Bundle Case", "other"),
    ("Reality Fracture - Prerelease Case", "other"),
    ("Reality Fracture - Collector Booster Omega Pack", "other"),
    ("FINAL FANTASY - Collector Booster Sample Pack", "other"),
    ("Phyrexia: All Will Be One Commander Deck Display", "other"),
    ("Reality Fracture Commander Deck - Multiverse Reforged Case", "other"),
])
def test_a_product_is_classified_by_its_name(name, kind):
    assert classify(name) == kind


def test_the_image_is_the_larger_one():
    assert larger_image(f"{CDN}/692979_200w.jpg") == f"{CDN}/692979_400w.jpg"
    assert larger_image("https://example.com/plain.jpg") == "https://example.com/plain.jpg"


def test_the_market_price_wins_over_the_mid_price_and_the_normal_printing_over_the_foil():
    prices = prices_by_product([
        price(1, market=5.0, mid=9.0), price(2, mid=7.456), price(3), price(4, market=100.0, sub="Foil"), price(4, market=10.0),
    ])
    assert prices == {1: 5.0, 2: 7.46, 4: 10.0}


def test_sealed_products_without_a_price_are_kept_with_none():
    assert sealed_products([product(1, "X - Bundle")], {})[0]["price"] is None


def test_a_picture_that_does_not_load_drops_its_product(tmp_path):
    run(tmp_path)
    assert all("19_" not in item["image"] for item in products_of(tmp_path, "fra")["products"])


def test_the_second_run_on_the_same_build_reads_nothing_it_has(tmp_path):
    _, first = run(tmp_path)
    assert first.reads() == ["1", "2", "3", "4", "5", "8", "9", "10"]
    written, second = run(tmp_path, now=NOW.replace(hour=11))
    assert second.reads() == []
    assert second.asked == [LAST_UPDATED_URL, f"{BASE_URL}/groups"]
    assert "sets/products/fra.json" in written
    assert products_of(tmp_path, "fra")["generated_at"] == "2026-10-20T11:30:00Z"


def test_a_new_build_reads_the_recent_sets_again_and_leaves_the_old_ones(tmp_path):
    run(tmp_path)
    _, later = run(tmp_path, Tcgcsv(built="2026-10-20T20:06:15+0000"))
    assert later.reads() == ["1", "2", "3"]


def test_an_old_set_is_read_again_when_its_group_changed_or_its_copy_is_stale(tmp_path):
    run(tmp_path)
    changed = [dict(group, modifiedOn="2026-10-18T00:00:00") if group["groupId"] == 4 else group for group in GROUPS]
    _, after_change = run(tmp_path, Tcgcsv(changed, built="2026-10-20T20:06:15+0000"))
    assert after_change.reads() == ["1", "2", "3", "4"]
    _, weeks_later = run(tmp_path, Tcgcsv(changed, built="2026-11-10T20:06:15+0000"))
    assert "9" in weeks_later.reads() and "5" in weeks_later.reads()


def test_needs_read_follows_the_age_of_the_set():
    built = datetime(2026, 10, 20, 20, 0, 0, tzinfo=timezone.utc)
    group = Group(1, "X", "x", "m")
    entry = {"modified": "m", "built": "2026-10-19T20:00:00+0000", "products": []}
    assert needs_read(entry, group, SetInfo("x", "X", "2026-10-02"), built)
    assert not needs_read(entry, group, SetInfo("x", "X", "2024-10-02"), built)
    assert needs_read(None, group, SetInfo("x", "X", "2024-10-02"), built)
    assert needs_read(dict(entry, modified="other"), group, SetInfo("x", "X", "2024-10-02"), built)
    assert needs_read({"modified": "m", "products": []}, group, SetInfo("x", "X", "2024-10-02"), built)


def test_a_group_that_fails_is_skipped_and_the_others_are_written(tmp_path):
    tcgcsv = Tcgcsv()
    tcgcsv.files[f"{BASE_URL}/3/products"] = OSError("HTTP 500")
    written, _ = run(tmp_path, tcgcsv)
    assert "sets/products/trk.json" not in written and "sets/products/fra.json" in written


def test_a_group_that_fails_keeps_its_last_copy(tmp_path):
    run(tmp_path)
    tcgcsv = Tcgcsv(built="2026-10-20T20:06:15+0000")
    tcgcsv.files[f"{BASE_URL}/3/products"] = OSError("HTTP 500")
    written, _ = run(tmp_path, tcgcsv)
    assert "sets/products/trk.json" in written


def test_a_pictures_found_by_the_last_read_are_not_asked_for_again(tmp_path):
    run(tmp_path)
    asked = []
    run(tmp_path, Tcgcsv(built="2026-10-20T20:06:15+0000"), check=lambda url: asked.append(url) or loads(url))
    assert all("19_" in url for url in asked)


def test_the_state_keeps_each_group_read(tmp_path):
    run(tmp_path)
    state = read_state(tmp_path)
    assert set(state) == {"1", "2", "3", "4", "5", "8", "9", "10"}
    assert state["3"]["built"] == BUILT and state["3"]["modified"] == "2026-10-13T00:00:00"
    (tmp_path / "state" / "set-products.json").write_text("not json")
    assert read_state(tmp_path) == {}


def test_tcgcsv_being_down_writes_nothing(tmp_path):
    tcgcsv = Tcgcsv()
    tcgcsv.files[f"{BASE_URL}/groups"] = OSError("HTTP 503")
    with pytest.raises(OSError):
        run(tmp_path, tcgcsv)
    assert not (tmp_path / "sets").exists()


def test_a_picture_the_cdn_does_not_have_is_not_a_failure(monkeypatch):
    class Response:
        headers = {"Content-Type": "image/jpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(setproducts.urllib.request, "urlopen", lambda request, timeout: Response())
    assert image_loads("https://x/1.jpg")

    def forbidden(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(setproducts.urllib.request, "urlopen", forbidden)
    assert not image_loads("https://x/1.jpg")

    def broken(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    monkeypatch.setattr(setproducts.urllib.request, "urlopen", broken)
    with pytest.raises(urllib.error.HTTPError):
        image_loads("https://x/1.jpg")


def test_publish_set_products_names_the_files_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(setproducts, "write_set_products", lambda *args: ["sets/products/fra.json"])
    assert entry.publish_set_products(tmp_path, RunReport()) == ["sets/products/fra.json"]


def test_set_products_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SET_PRODUCTS", "0")
    monkeypatch.setattr(setproducts, "write_set_products", lambda *args: pytest.fail("ran"))
    assert entry.publish_set_products(tmp_path, RunReport()) == []


def test_a_failure_in_publish_set_products_is_a_warning_the_run_passes(tmp_path, monkeypatch):
    def boom(*args):
        raise OSError("HTTP 500")

    monkeypatch.setattr(setproducts, "write_set_products", boom)
    report = RunReport()
    assert entry.publish_set_products(tmp_path, report) == []
    assert report.errors == [] and report.warnings == ["set products: HTTP 500"]
