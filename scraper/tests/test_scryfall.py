import gzip
import json
from pathlib import Path

from mtgmeta.scryfall import card_catalog

CARDS = [
    {"name": "Lightning Bolt", "oracle_id": "bolt-oracle", "layout": "normal"},
    {"name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "oracle_id": "fable-oracle", "layout": "transform"},
    {"name": "Reversible thing", "layout": "reversible_card", "card_faces": [{"oracle_id": "face-oracle"}]},
    {"name": "Some Token", "oracle_id": "token-oracle", "layout": "token"},
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
