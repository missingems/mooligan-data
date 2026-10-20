import json

from mtgmeta import guide_check

CARD = {"name": "Sol Ring", "oracle_id": "ring", "role": "ramp"}
GUIDE = {
    "slug": "atraxa",
    "name": "Atraxa, Praetors' Voice",
    "styles": [{"id": f"style-{n}", "name": "Style", "summary": "Plan.", "brackets": [2, 3], "cards": [CARD]} for n in range(3)],
    "brackets": [{"level": level, "name": "Name", "summary": "", "cards": [CARD]} for level in range(1, 6)],
    "combos": [{"id": "1-2", "cards": [CARD], "requires": [], "results": ["Infinite mana"], "bracket": 4, "bracket_tag": "R"}],
}


def test_a_whole_guide_passes():
    assert guide_check.problems(GUIDE, "atraxa") == []


def test_what_the_app_needs_is_checked():
    assert guide_check.problems({**GUIDE, "slug": "other"}, "atraxa") == ["slug 'other'"]
    assert guide_check.problems({**GUIDE, "brackets": GUIDE["brackets"][:4]}, "atraxa") == ["brackets are not levels 1 to 5"]
    assert guide_check.problems({k: v for k, v in GUIDE.items() if k != "combos"}, "atraxa") == ["no combos"]
    broken = {**GUIDE, "combos": [{**GUIDE["combos"][0], "results": [], "cards": [{"name": "Sol Ring"}]}]}
    assert guide_check.problems(broken, "atraxa") == ["combo '1-2': no results", "combo '1-2': a card without a name or oracle id"]


def test_the_command_prints_only_what_passes(tmp_path, capsys):
    for slug, guide in (("atraxa", GUIDE), ("broken", {**GUIDE, "slug": "broken", "styles": []})):
        path = tmp_path / "edh" / "commanders" / slug / "guide.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(guide))
    assert guide_check.main([str(tmp_path), "--slug", "atraxa", "--slug", "broken", "--slug", "missing"]) == 1
    assert capsys.readouterr().out == "atraxa\n"
