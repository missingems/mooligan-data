import json
import struct
from datetime import datetime, timezone

import pytest

import mtgmeta.__main__ as entry
import mtgmeta.setart as setart
from mtgmeta.models import RunReport
from mtgmeta.setart import (
    GALLERY, PRODUCT, PRODUCT_GALLERY, SITEMAP_URL, Page, Paced, Response, SetInfo, image_size, measure, og_image,
    pages_by_set, parse_sets, parse_sitemap, pick, read_cache, write_set_art,
)

NOW = datetime(2026, 10, 20, 9, 30, 0, tzinfo=timezone.utc)
BASE = "https://magic.wizards.com/en"


def sitemap(*entries):
    rows = "".join(f"<url><loc>{BASE}{path}</loc>" + (f"<lastmod>{lastmod}</lastmod>" if lastmod else "") + "</url>" for path, lastmod in entries)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'.encode()


def jpeg(width, height):
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc2\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9


def png(width, height):
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


def page(image):
    meta = f'<meta property="og:image" content="{image}">' if image else ""
    return f'<html><head><meta property="og:title" content="x">{meta}</head><body></body></html>'.encode()


def scryfall(*sets):
    data = [{"code": code, "name": name, "released_at": released, "set_type": kind, "digital": False} for code, name, released, kind in sets]
    return json.dumps({"object": "list", "data": data}).encode()


SETS = scryfall(
    ("dsk", "Duskmourn: House of Horror", "2024-09-27", "expansion"),
    ("fdn", "Foundations", "2024-11-15", "core"),
    ("hou", "Hour of Devastation", "2017-07-14", "expansion"),
    ("frf", "Fate Reforged", "2015-01-23", "expansion"),
    ("m15", "Magic 2015", "2014-07-18", "core"),
    ("tdsk", "Duskmourn Tokens", "2024-09-27", "token"),
)

DSK_IMAGE = "https://images.ctfassets.net/x/dsk/dsk_meta.jpg"
DSK_GALLERY_IMAGE = "https://images.ctfassets.net/x/dsk/dsk_highlights.jpg"
FDN_IMAGE = "https://images.ctfassets.net/x/fdn/Meta-Image_FDN_EN.jpg"
HOU_IMAGE = "https://images.ctfassets.net/x/hou/hou-meta-image.jpeg"
FRF_IMAGE = "https://images.ctfassets.net/x/frf/frf.png"


class Wizards:
    """Stands in for Wizards' site: pages, images and the sitemap, and a record of what was asked for."""

    def __init__(self, sitemap_xml=None):
        self.files = {
            SITEMAP_URL: Response("application/xml", sitemap_xml or sitemap(
                ("/products/duskmourn-house-of-horror", "2026-09-01T00:00:00Z"),
                ("/products/duskmourn-house-of-horror/card-image-gallery", "2026-09-02T00:00:00Z"),
                ("/products/duskmourn-house-of-horror-order-now", None),
                ("/products/foundations", "2026-09-03T00:00:00Z"),
                ("/news/card-image-gallery/hour-devastation", "2017-07-01T00:00:00Z"),
                ("/news/card-image-gallery/frf-cig-en", "2015-01-01T00:00:00Z"),
                ("/news/card-image-gallery/dragonsoftarkir", "2015-03-01T00:00:00Z"),
                ("/news/making-magic/some-column", "2026-01-01T00:00:00Z"),
            )),
            f"{BASE}/products/duskmourn-house-of-horror": Response("text/html", page(DSK_IMAGE)),
            f"{BASE}/products/duskmourn-house-of-horror/card-image-gallery": Response("text/html", page(DSK_GALLERY_IMAGE)),
            f"{BASE}/products/foundations": Response("text/html", page(FDN_IMAGE)),
            f"{BASE}/news/card-image-gallery/hour-devastation": Response("text/html", page(HOU_IMAGE)),
            f"{BASE}/news/card-image-gallery/frf-cig-en": Response("text/html", page(FRF_IMAGE)),
            DSK_IMAGE: Response("image/jpeg", jpeg(1200, 630)),
            DSK_GALLERY_IMAGE: Response("image/jpeg", jpeg(768, 432)),
            FDN_IMAGE: Response("image/jpeg", jpeg(1200, 630)),
            HOU_IMAGE: Response("image/jpeg", jpeg(768, 432)),
            FRF_IMAGE: Response("image/png", png(1920, 1080)),
        }
        self.asked = []

    def __call__(self, url, last_byte=None):
        self.asked.append(url)
        found = self.files[url]
        if isinstance(found, Exception):
            raise found
        return found


def run(tmp_path, wizards, sets=SETS):
    return write_set_art(tmp_path, NOW, wizards, lambda url: sets)


def art(tmp_path):
    return json.loads((tmp_path / "sets" / "art.json").read_text())


def test_the_file_maps_each_set_code_to_the_art_of_its_pages(tmp_path):
    assert run(tmp_path, Wizards()) == ["sets/art.json"]
    assert art(tmp_path) == {
        "schema": 1,
        "generated_at": "2026-10-20T09:30:00Z",
        "sets": {
            "dsk": {
                "url": DSK_IMAGE, "width": 1200, "height": 630, "title": "Duskmourn: House of Horror", "source": "wizards",
                "page": f"{BASE}/products/duskmourn-house-of-horror",
            },
            "fdn": {"url": FDN_IMAGE, "width": 1200, "height": 630, "title": "Foundations", "source": "wizards", "page": f"{BASE}/products/foundations"},
            "frf": {"url": FRF_IMAGE, "width": 1920, "height": 1080, "title": "Fate Reforged", "source": "wizards", "page": f"{BASE}/news/card-image-gallery/frf-cig-en"},
            "hou": {"url": HOU_IMAGE, "width": 768, "height": 432, "title": "Hour of Devastation", "source": "wizards", "page": f"{BASE}/news/card-image-gallery/hour-devastation"},
        },
    }


def test_a_set_without_a_page_is_left_out(tmp_path):
    run(tmp_path, Wizards())
    assert "m15" not in art(tmp_path)["sets"] and "tdsk" not in art(tmp_path)["sets"]


def test_only_the_pages_of_sets_are_fetched_and_never_the_order_now_copies(tmp_path):
    wizards = Wizards()
    run(tmp_path, wizards)
    assert not any("order-now" in url or "making-magic" in url or "dragonsoftarkir" in url for url in wizards.asked)


def test_a_cached_page_is_not_fetched_again(tmp_path):
    run(tmp_path, Wizards())
    again = Wizards()
    run(tmp_path, again)
    assert again.asked == [SITEMAP_URL]
    assert set(art(tmp_path)["sets"]) == {"dsk", "fdn", "frf", "hou"}


def test_a_page_the_sitemap_says_changed_is_read_again_and_its_known_image_is_not_measured_again(tmp_path):
    run(tmp_path, Wizards())
    changed = Wizards(sitemap(
        ("/products/duskmourn-house-of-horror", "2026-10-01T00:00:00Z"),
        ("/products/duskmourn-house-of-horror/card-image-gallery", "2026-09-02T00:00:00Z"),
        ("/products/foundations", "2026-09-03T00:00:00Z"),
        ("/news/card-image-gallery/hour-devastation", "2017-07-01T00:00:00Z"),
        ("/news/card-image-gallery/frf-cig-en", "2015-01-01T00:00:00Z"),
    ))
    run(tmp_path, changed)
    assert changed.asked == [SITEMAP_URL, f"{BASE}/products/duskmourn-house-of-horror"]


def test_a_new_image_on_a_changed_page_is_measured(tmp_path):
    run(tmp_path, Wizards())
    new = "https://images.ctfassets.net/x/dsk/new.jpg"
    changed = Wizards(sitemap(("/products/duskmourn-house-of-horror", "2026-10-01T00:00:00Z")))
    changed.files[f"{BASE}/products/duskmourn-house-of-horror"] = Response("text/html", page(new))
    changed.files[new] = Response("image/jpeg", jpeg(1920, 1080))
    run(tmp_path, changed)
    assert art(tmp_path)["sets"]["dsk"]["url"] == new and art(tmp_path)["sets"]["dsk"]["width"] == 1920


def test_a_page_that_fails_is_skipped_and_tried_again_next_run(tmp_path, caplog):
    broken = Wizards()
    broken.files[f"{BASE}/products/foundations"] = OSError("HTTP 503")
    run(tmp_path, broken)
    assert set(art(tmp_path)["sets"]) == {"dsk", "frf", "hou"}
    assert f"{BASE}/products/foundations" not in read_cache(tmp_path)
    again = Wizards()
    run(tmp_path, again)
    assert again.asked == [SITEMAP_URL, f"{BASE}/products/foundations", FDN_IMAGE] and "fdn" in art(tmp_path)["sets"]


def test_an_image_that_is_not_an_image_leaves_the_set_out(tmp_path):
    wizards = Wizards()
    wizards.files[FDN_IMAGE] = Response("text/html", b"<html>blocked</html>")
    run(tmp_path, wizards)
    assert "fdn" not in art(tmp_path)["sets"]


def test_a_failing_sitemap_writes_nothing_and_leaves_the_published_file(tmp_path):
    wizards = Wizards()
    wizards.files[SITEMAP_URL] = OSError("HTTP 500")
    with pytest.raises(OSError):
        run(tmp_path, wizards)
    assert not (tmp_path / "sets").exists()


def test_the_widest_landscape_image_wins_and_a_product_page_wins_a_tie(tmp_path):
    product = Page("p", PRODUCT, "x", None)
    product_gallery = Page("pg", PRODUCT_GALLERY, "x", None)
    gallery = Page("g", GALLERY, "x", None)
    wide = {"image": "w", "width": 1920, "height": 1080}
    social = {"image": "s", "width": 1200, "height": 630}
    square = {"image": "q", "width": 2000, "height": 2000}
    assert pick([(product, social), (gallery, wide), (product_gallery, square)]) == (gallery, wide)
    assert pick([(gallery, social), (product_gallery, social), (product, social)]) == (product, social)
    assert pick([(product, square), (gallery, {"image": None})]) is None


def test_a_page_with_no_image_is_cached_so_it_is_not_fetched_again(tmp_path):
    wizards = Wizards()
    wizards.files[f"{BASE}/products/foundations"] = Response("text/html", page(None))
    run(tmp_path, wizards)
    assert "fdn" not in art(tmp_path)["sets"]
    again = Wizards()
    run(tmp_path, again)
    assert again.asked == [SITEMAP_URL]


def test_the_state_keeps_only_pages_that_still_matter(tmp_path):
    run(tmp_path, Wizards())
    assert set(read_cache(tmp_path)) == {
        f"{BASE}/products/duskmourn-house-of-horror", f"{BASE}/products/duskmourn-house-of-horror/card-image-gallery",
        f"{BASE}/products/foundations", f"{BASE}/news/card-image-gallery/hour-devastation", f"{BASE}/news/card-image-gallery/frf-cig-en",
    }


def test_the_sitemap_gives_product_and_gallery_pages_only():
    pages = parse_sitemap(sitemap(
        ("/products/marvel/marvel-super-heroes", "2026-06-01T00:00:00Z"),
        ("/products/marvel/marvel-super-heroes/card-image-gallery", None),
        ("/products/card-image-gallery", None),
        ("/news/card-image-gallery/kaladesh", None),
        ("/news/card-image-gallery", None),
        ("/news/feature/lost-wallpapers-2012-12-06", None),
        ("/how-to-play", None),
    ))
    assert pages == [
        Page(f"{BASE}/products/marvel/marvel-super-heroes", PRODUCT, "marvel-super-heroes", "2026-06-01T00:00:00Z"),
        Page(f"{BASE}/products/marvel/marvel-super-heroes/card-image-gallery", PRODUCT_GALLERY, "marvel-super-heroes", None),
        Page(f"{BASE}/news/card-image-gallery/kaladesh", GALLERY, "kaladesh", None),
    ]


def test_scryfall_sets_are_the_paper_ones_from_2015_on():
    sets = parse_sets(json.loads(scryfall(
        ("dsk", "Duskmourn: House of Horror", "2024-09-27", "expansion"),
        ("m15", "Magic 2015", "2014-07-18", "core"),
        ("tdsk", "Duskmourn Tokens", "2024-09-27", "token"),
        ("mdd", "Marvel: Darkhold Destiny", "2027-04-09", "expansion"),
    )))
    assert sets == [SetInfo("dsk", "Duskmourn: House of Horror", "2024-09-27"), SetInfo("mdd", "Marvel: Darkhold Destiny", "2027-04-09")]
    digital = json.dumps({"data": [{"code": "ymid", "name": "Alchemy: Innistrad", "released_at": "2021-12-09", "set_type": "expansion", "digital": True}]})
    assert parse_sets(json.loads(digital)) == []


@pytest.mark.parametrize(
    "code, name, slug",
    [
        ("dsk", "Duskmourn: House of Horror", "duskmourn-house-of-horror"),
        ("hou", "Hour of Devastation", "hour-devastation"),
        ("bfz", "Battle for Zendikar", "battle-zendikar-2015-09-18"),
        ("ori", "Magic Origins", "magicorigins"),
        ("ogw", "Oath of the Gatewatch", "oathofthegatewatch"),
        ("frf", "Fate Reforged", "frf-cig-en"),
        ("mm2015", "Modern Masters 2015", "modernmasters2015edition"),
        ("c18", "Commander 2018", "commander-2018-edition-2018-07-27"),
        ("m19", "Core Set 2019", "core-set-2019-2018-06-22"),
        ("tla", "Avatar: The Last Airbender", "avatar-the-last-airbender"),
        ("ltr", "The Lord of the Rings: Tales of Middle-earth", "the-lord-of-the-rings-tales-of-middle-earth"),
        ("acr", "Assassin's Creed", "assassins-creed"),
        ("spm", "Marvel's Spider-Man", "spider-man"),
        ("ikoria", "Ikoria: Lair of Behemoths", "ikoria-lair-behemoths"),
    ],
)
def test_a_page_is_matched_to_a_set_by_its_slug(code, name, slug):
    found = pages_by_set([SetInfo(code if code != "ikoria" else "iko", name, "2020-04-03")], [Page("u", PRODUCT, slug, None)])
    assert list(found.values()) == [[Page("u", PRODUCT, slug, None)]]


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Kaladesh", "kaladesh-remastered"),
        ("Ixalan", "rivals-of-ixalan"),
        ("Duskmourn: House of Horror", "duskmourn-house-of-horror-variants"),
        ("Commander 2016", "commander-2017"),
        ("Foundations", "foundations-jumpstart"),
    ],
)
def test_a_page_of_another_set_is_not_matched(name, slug):
    assert pages_by_set([SetInfo("zzz", name, "2020-01-01")], [Page("u", PRODUCT, slug, None)]) == {}


def test_the_social_image_of_a_page():
    assert og_image(page("//images.ctfassets.net/x/a.jpg"), "https://magic.wizards.com/en/products/x") == "https://images.ctfassets.net/x/a.jpg"
    assert og_image(page("/media/a.jpg"), "https://magic.wizards.com/en/products/x") == "https://magic.wizards.com/media/a.jpg"
    assert og_image(page(None), "https://magic.wizards.com/en/products/x") is None


def test_an_image_wizards_sets_on_any_page_is_not_set_art():
    for generic in ("https://images.ctfassets.net/x/error-pages_0.jpg", "https://images.ctfassets.net/x/MTG_Meta-ShareImage.jpg"):
        assert og_image(page(generic), "https://magic.wizards.com/en/x") is None


def test_image_sizes_are_read_from_the_first_bytes():
    assert image_size(jpeg(1920, 1080)) == (1920, 1080)
    assert image_size(png(1200, 630)) == (1200, 630)
    assert image_size(b"GIF89a" + struct.pack("<HH", 640, 360)) == (640, 360)
    webp_x = b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x00\x00\x00\x00" + (1919).to_bytes(3, "little") + (1079).to_bytes(3, "little")
    assert image_size(webp_x) == (1920, 1080)
    assert image_size(b"not an image") is None


def test_a_jpeg_that_hides_its_size_past_the_first_bytes_is_read_whole():
    calls = []

    def get(url, last_byte=None):
        calls.append(last_byte)
        if last_byte is not None:
            return Response("image/jpeg", b"\xff\xd8" + b"\xff\xfe\xff\xfd" + b"\x00" * (setart.HEAD_BYTES - 6) + b"\x00" * 6)
        return Response("image/jpeg", jpeg(1600, 900))

    assert measure("u", get) == (1600, 900) and calls == [setart.HEAD_BYTES, None]


def test_requests_are_paced():
    now, slept = [100.0], []

    def sleep(seconds):
        slept.append(round(seconds, 3))
        now[0] += seconds

    paced = Paced(lambda url, last_byte=None: Response("text/html", b""), 0.5, sleep, lambda: now[0])
    paced("a")
    now[0] += 0.2
    paced("b")
    now[0] += 2
    paced("c")
    assert slept == [0.3]


def test_publish_set_art_names_the_file_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(setart, "write_set_art", lambda directory, now, get, scry: ["sets/art.json"])
    assert entry.publish_set_art(tmp_path, RunReport()) == ["sets/art.json"]


def test_set_art_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SET_ART", "0")
    monkeypatch.setattr(setart, "write_set_art", lambda *args: pytest.fail("ran"))
    assert entry.publish_set_art(tmp_path, RunReport()) == []


def test_a_failure_in_publish_set_art_is_a_warning_the_run_passes(tmp_path, monkeypatch):
    def boom(*args):
        raise OSError("HTTP 500")

    monkeypatch.setattr(setart, "write_set_art", boom)
    report = RunReport()
    assert entry.publish_set_art(tmp_path, report) == []
    assert report.errors == [] and report.warnings == ["set art: HTTP 500"]
