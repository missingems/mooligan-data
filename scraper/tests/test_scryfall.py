import gzip
import json
from pathlib import Path

from mtgmeta.scryfall import card_catalog

CARDS = [
    {"name": "Lightning Bolt", "oracle_id": "bolt-oracle", "layout": "normal"},
    {"name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "oracle_id": "fable-oracle", "layout": "transform"},
    {"name": "Reversible thing", "layout": "reversible_card", "card_faces": [{"oracle_id": "face-oracle"}]},
    {"name": "Some Token", "oracle_id": "token-oracle", "layout": "token"},
    {"name": "Mountain", "oracle_id": "mountain-oracle", "layout": "normal", "type_line": "Basic Land — Mountain"},
    {"name": "Dryad Arbor", "oracle_id": "arbor-oracle", "layout": "normal", "type_line": "Land Creature — Forest Dryad"},
    {"name": "Shatterskull Smashing // Shatterskull, the Hammer Pass", "oracle_id": "smashing-oracle", "layout": "modal_dfc", "type_line": "Sorcery // Land"},
    {"name": "Blightstep Pathway // Searstep Pathway", "oracle_id": "pathway-oracle", "layout": "modal_dfc", "type_line": "Land // Land"},
    {"name": "Reversible land", "layout": "reversible_card", "card_faces": [{"oracle_id": "rev-oracle", "type_line": "Land"}]},
    {"name": "Shivan Dragon", "oracle_id": "dragon-oracle", "layout": "normal", "cmc": 6.0, "prices": {"usd": "12.50", "usd_foil": "40.00", "usd_etched": None}},
    {"name": "Foil Only", "oracle_id": "foil-oracle", "layout": "normal", "cmc": 2.0, "prices": {"usd": None, "usd_foil": "3.25", "usd_etched": None}},
    {"name": "Unpriced Thing", "oracle_id": "unpriced-oracle", "layout": "normal", "cmc": 0.0, "prices": {"usd": None, "usd_foil": None, "usd_etched": None}},
    {"name": "Lightning Bolt Elemental", "oracle_id": "elemental-oracle", "layout": "normal", "type_line": "Creature — Elemental Landwalker"},
]


def test_the_catalog_keys_real_cards_by_slug(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["lightning-bolt"] == {"name": "Lightning Bolt", "oracle_id": "bolt-oracle"}
    # A double-faced card is keyed by its front face, as decklists write it.
    assert catalog["fable-of-the-mirror-breaker"]["oracle_id"] == "fable-oracle"
    # A reversible card keeps its oracle id on the face.
    assert catalog["reversible-thing"]["oracle_id"] == "face-oracle"
    assert "some-token" not in catalog


def test_the_catalog_marks_a_card_whose_front_face_is_a_land(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["mountain"] == {"name": "Mountain", "oracle_id": "mountain-oracle", "land": True}
    assert catalog["dryad-arbor"]["land"] is True  # a creature land is a land
    assert catalog["blightstep-pathway"]["land"] is True
    assert catalog["reversible-land"]["land"] is True  # the type line sits on the face
    # A spell with a land on the back plays as a spell, and a subtype that only contains the letters isn't a land.
    assert "land" not in catalog["shatterskull-smashing"]
    assert "land" not in catalog["lightning-bolt-elemental"]
    assert "land" not in catalog["lightning-bolt"]  # a card with no type line at all


def test_the_catalog_keeps_the_price_and_mana_value_that_rank_a_decks_cards(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["shivan-dragon"] == {"name": "Shivan Dragon", "oracle_id": "dragon-oracle", "price": 12.5, "mana_value": 6.0}
    assert catalog["foil-only"]["price"] == 3.25  # no regular price, so the foil one
    assert "price" not in catalog["unpriced-thing"] and catalog["unpriced-thing"]["mana_value"] == 0.0
    assert "price" not in catalog["lightning-bolt"] and "mana_value" not in catalog["lightning-bolt"]  # a record without them
