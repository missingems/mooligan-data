import gzip
import json
from pathlib import Path

from mtgmeta.scryfall import card_catalog

CARDS = [
    {"name": "Lightning Bolt", "oracle_id": "bolt-oracle", "id": "bolt-printing", "layout": "normal"},
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
    {"name": "Counterspell", "oracle_id": "counter-oracle", "layout": "normal", "mana_cost": "{U}{U}", "color_identity": ["U"]},
    {"name": "Kenrith, the Returned King", "oracle_id": "kenrith-oracle", "layout": "normal", "color_identity": ["B", "G", "R", "U", "W"]},
    {"name": "Sol Ring", "oracle_id": "ring-oracle", "layout": "normal", "color_identity": []},
    {"name": "Fire // Ice", "oracle_id": "fire-oracle", "layout": "split", "mana_cost": "{1}{R} // {1}{U}", "type_line": "Instant // Instant",
     "card_faces": [{"mana_cost": "{1}{R}"}, {"mana_cost": "{1}{U}"}]},
    {"name": "Bonecrusher Giant // Stomp", "oracle_id": "giant-oracle", "layout": "adventure", "mana_cost": "{2}{R} // {1}{R}",
     "card_faces": [{"mana_cost": "{2}{R}"}, {"mana_cost": "{1}{R}"}]},
    {"name": "Delver of Secrets // Insectile Aberration", "oracle_id": "delver-oracle", "layout": "transform", "mana_cost": "",
     "card_faces": [{"mana_cost": "{U}"}, {"mana_cost": ""}]},
    {"name": "Valki, God of Lies // Tibalt, Cosmic Impostor", "oracle_id": "valki-oracle", "layout": "modal_dfc",
     "card_faces": [{"mana_cost": "{1}{B}"}, {"mana_cost": "{5}{B}{R}"}]},
    {"name": "Reversible spell", "layout": "reversible_card", "card_faces": [{"oracle_id": "spell-oracle", "mana_cost": "{G}"}, {"mana_cost": "{G}"}]},
    {"name": "Ornithopter", "oracle_id": "ornithopter-oracle", "layout": "normal", "mana_cost": "{0}"},
    {"name": "Brainstorm", "oracle_id": "brainstorm-oracle", "layout": "normal", "oracle_text": "Draw three cards, then put two cards from your hand on top of your library in any order."},
    {"name": "Bala Ged Recovery // Bala Ged Sanctuary", "oracle_id": "bala-oracle", "layout": "modal_dfc",
     "card_faces": [{"oracle_text": "Return target card from your graveyard to your hand."}, {"oracle_text": "As Bala Ged Sanctuary enters, you may pay 3 life.\n{T}: Add {G}."}]},
    {"name": "Smuggler’s Copter", "oracle_id": "copter-oracle", "layout": "normal", "oracle_text": "Whenever Smuggler’s Copter attacks or blocks, you may draw a card."},
]


def test_the_catalog_keys_real_cards_by_slug(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    # The printing the file picks is kept when it has an id.
    assert catalog["lightning-bolt"] == {"name": "Lightning Bolt", "oracle_id": "bolt-oracle", "scryfall_id": "bolt-printing", "type_line": "", "layout": "normal"}
    assert "scryfall_id" not in catalog["fable-of-the-mirror-breaker"]
    # The colour identity is in WUBRG order, empty for a colourless card, and absent when the file has none.
    assert catalog["kenrith-the-returned-king"]["color_identity"] == ["W", "U", "B", "R", "G"]
    assert catalog["sol-ring"]["color_identity"] == [] and catalog["counterspell"]["color_identity"] == ["U"]
    assert "color_identity" not in catalog["lightning-bolt"]
    # A double-faced card is keyed by its front face, as decklists write it.
    assert catalog["fable-of-the-mirror-breaker"]["oracle_id"] == "fable-oracle"
    # A reversible card keeps its oracle id on the face.
    assert catalog["reversible-thing"]["oracle_id"] == "face-oracle"
    assert "some-token" not in catalog


def test_the_catalog_keeps_every_face_s_rules_text(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["brainstorm"]["oracle_text"].startswith("Draw three cards")
    assert catalog["bala-ged-recovery"]["oracle_text"] == (
        "Return target card from your graveyard to your hand.\nAs Bala Ged Sanctuary enters, you may pay 3 life.\n{T}: Add {G}."
    )
    assert catalog["smugglers-copter"]["oracle_text"] == "Whenever Smuggler's Copter attacks or blocks, you may draw a card."
    assert "oracle_text" not in catalog["sol-ring"]


def test_the_catalog_marks_a_card_whose_front_face_is_a_land(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["mountain"] == {"name": "Mountain", "oracle_id": "mountain-oracle", "type_line": "Basic Land — Mountain", "layout": "normal", "land": True}
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

    assert catalog["shivan-dragon"] == {
        "name": "Shivan Dragon", "oracle_id": "dragon-oracle", "type_line": "", "layout": "normal", "price": 12.5, "mana_value": 6.0
    }
    assert catalog["foil-only"]["price"] == 3.25  # no regular price, so the foil one
    assert "price" not in catalog["unpriced-thing"] and catalog["unpriced-thing"]["mana_value"] == 0.0
    assert "price" not in catalog["lightning-bolt"] and "mana_value" not in catalog["lightning-bolt"]  # a record without them


def test_the_catalog_keeps_the_mana_cost_that_gives_a_card_its_colours(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["counterspell"]["mana_cost"] == "{U}{U}"
    # A split or adventure card has both halves on the card, and both count.
    assert catalog["fire"]["mana_cost"] == "{1}{R} // {1}{U}"
    assert catalog["bonecrusher-giant"]["mana_cost"] == "{2}{R} // {1}{R}"
    # A transform or modal double-faced card has none of its own: the front face's stands in, as the deck plays the front.
    assert catalog["delver-of-secrets"]["mana_cost"] == "{U}"
    assert catalog["valki-god-of-lies"]["mana_cost"] == "{1}{B}"
    assert catalog["reversible-spell"]["mana_cost"] == "{G}"
    # A cost of {0} is a cost; a land or a card with none has no key at all.
    assert catalog["ornithopter"]["mana_cost"] == "{0}"
    assert "mana_cost" not in catalog["mountain"] and "mana_cost" not in catalog["lightning-bolt"]


def test_the_catalog_keeps_the_front_faces_type_line_and_the_layout_that_group_popular_cards(tmp_path: Path):
    path = tmp_path / "oracle-cards.jsonl.gz"
    path.write_bytes(gzip.compress(b"\n".join(json.dumps(card).encode() for card in CARDS)))

    catalog = card_catalog(path.as_uri())

    assert catalog["dryad-arbor"]["type_line"] == "Land Creature — Forest Dryad"
    # Only the front face's, as the deck plays it: a spell with a land on the back, or two lands.
    assert catalog["shatterskull-smashing"]["type_line"] == "Sorcery"
    assert catalog["blightstep-pathway"]["type_line"] == "Land"
    assert catalog["fire"]["type_line"] == "Instant"
    # A card with none on it takes its front face's, and a card with no type line anywhere has "".
    assert catalog["reversible-land"]["type_line"] == "Land"
    assert catalog["lightning-bolt"]["type_line"] == ""
    # The layout is what tells "Fire // Ice" (a split card, both halves) from "Fable // Reflection" (a front face).
    assert (catalog["fire"]["layout"], catalog["fable-of-the-mirror-breaker"]["layout"]) == ("split", "transform")
    assert catalog["bonecrusher-giant"]["layout"] == "adventure"
