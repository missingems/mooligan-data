"""When each part of an undated page belongs in the story, so its events sort among the dated ones.

MTG Wiki articles carry no date, but each section of one tells the story of a time: "Thran-Phyrexian War",
"Phyrexian Invasion". data/eras.json tags each (page, section) with the Magic set or novel year that told
that part of the story:

    {"wiki/yawgmoth": {"Phyrexian Invasion": {"era": "inv", "label": "Invasion", "date": "2000-10-02"}}}

`era` is a set code (dated by the set's release, from the card data) or a year ("1999", dated 1 July).
These dates only order events; they are not facts, and an event's citation is unchanged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional


def set_dates(data: Path) -> Dict[str, dict]:
    """Every set the card data has: code to name and release date."""
    out = {}
    for path in (data / "cards").glob("*.json"):
        page = json.loads(path.read_text())
        out[page["slug"]] = {"label": re.sub(r":\s*card flavor text$", "", page["title"]), "date": page["story_date"]}
    return out


def resolve(era: str, sets: Dict[str, dict]) -> Optional[dict]:
    era = (era or "").strip().lower()
    if era in sets and sets[era]["date"]:
        return {"era": era, "label": sets[era]["label"], "date": sets[era]["date"]}
    if re.fullmatch(r"(199[3-9]|20[0-2]\d)", era):
        return {"era": era, "label": era, "date": f"{era}-07-01"}
    return None


def load(data: Path) -> dict:
    path = data / "eras.json"
    return json.loads(path.read_text()) if path.exists() else {}


def ingest(data: Path, rows) -> dict:
    """Saves tags given as [{"page", "section", "era"}]; ones naming no known set or year are reported."""
    sets, eras = set_dates(data), load(data)
    report = {"saved": 0, "bad": []}
    for row in rows:
        found = resolve(row.get("era", ""), sets)
        if found is None:
            report["bad"].append(row)
            continue
        eras.setdefault(row["page"], {})[row.get("section", "")] = found
        report["saved"] += 1
    (data / "eras.json").write_text(json.dumps(eras, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return report
