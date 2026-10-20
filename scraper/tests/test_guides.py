import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mtgmeta import guides

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
KEY = "sk-ant-test-sentinel-0123456789"

CATALOG = {
    "atraxa-praetors-voice": {"name": "Atraxa, Praetors' Voice", "oracle_id": "atraxa-oracle", "color_identity": ["W", "U", "B", "G"]},
    "sol-ring": {"name": "Sol Ring", "oracle_id": "ring-oracle", "color_identity": []},
    "counterspell": {"name": "Counterspell", "oracle_id": "counter-oracle", "color_identity": ["U"]},
    "lightning-bolt": {"name": "Lightning Bolt", "oracle_id": "bolt-oracle", "color_identity": ["R"]},
    "mana-crypt": {"name": "Mana Crypt", "oracle_id": "crypt-oracle", "color_identity": []},
    "delay": {"name": "Delay", "oracle_id": "delay-oracle", "color_identity": ["U"]},
    "fable-of-the-mirror-breaker": {"name": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "oracle_id": "fable-oracle", "color_identity": ["R"]},
}
# A run of plain cards, so a style can reach its 30.
for number in range(40):
    CATALOG[f"filler-{number}"] = {"name": f"Filler {number}", "oracle_id": f"filler-{number}-oracle", "color_identity": ["G"]}
# Five Game Changers from the repo's list, by their real oracle ids.
CHANGERS = {card["name"]: card["oracle_id"] for card in guides.load_game_changers()}
for name in ("Demonic Tutor", "Vampiric Tutor", "Rhystic Study", "Cyclonic Rift", "Smothering Tithe"):
    CATALOG[guides.card_slug(name)] = {"name": name, "oracle_id": CHANGERS[name], "color_identity": []}

PAGE = {
    "schema": 1,
    "slug": "atraxa-praetors-voice",
    "name": "Atraxa, Praetors' Voice",
    "decks": 1000,
    "color_identity": ["W", "U", "B", "G"],
    "scryfall_id": "atraxa-printing",
    "generated_at": "2026-10-19T14:00:00Z",
    "sections": [
        {"tag": "topcards", "header": "Top Cards", "cards": [{"name": "Sol Ring", "decks": 912, "of_decks": 1000, "synergy": 0.0}]},
        {"tag": "instants", "header": "Instants", "cards": [
            {"name": "Counterspell", "decks": 400, "of_decks": 1000, "synergy": 0.1},
            {"name": "Sol Ring", "decks": 912, "of_decks": 1000, "synergy": 0.0},
        ]},
    ],
    "average_deck": [{"header": "Artifacts", "cards": ["Sol Ring", "Arcane Signet"]}],
}
TOP = {"schema": 1, "windows": {
    "7d": {"decks": 10, "commanders": [{"rank": 1, "slug": "atraxa-praetors-voice", "name": "Atraxa, Praetors' Voice"}]},
    "30d": {"decks": 10, "commanders": [{"rank": 1, "slug": "other-commander", "name": "Other"}]},
}}


def card(name, role="utility"):
    return {"name": name, "role": role}


def answer(styles=None, brackets=None):
    fillers = [card(f"Filler {number}", "engine") for number in range(40)]
    return {
        "styles": styles if styles is not None else [
            {"name": "Superfriends", "summary": "Planeswalkers.", "brackets": [3, 2, 2, 9], "cards": [card("Sol Ring", "ramp"), *fillers]},
            {"name": "Infect", "summary": "Poison.", "brackets": [4], "cards": fillers},
            {"name": "Proliferate Counters", "summary": "Counters.", "brackets": [2, 3], "cards": fillers},
        ],
        "brackets": brackets if brackets is not None else [
            {"level": level, "summary": f"Bracket {level}.", "cards": [card("Sol Ring", "ramp")]} for level in (5, 4, 3, 2, 1)
        ],
    }


class Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class FakeClient:
    """Stands in for anthropic.Anthropic: records each call and answers with a write_guide tool call."""

    def __init__(self, *answers, stop_reason="tool_use"):
        self.calls = []
        self._answers = list(answers)
        self._stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **call):
        self.calls.append(call)
        tool_input = self._answers.pop(0) if self._answers else answer()
        return Stream(SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="tool_use", name="write_guide", input=tool_input)],
            stop_reason=self._stop_reason,
            model="claude-sonnet-5-5",
            usage=SimpleNamespace(input_tokens=2000, output_tokens=8000, cache_creation_input_tokens=0, cache_read_input_tokens=2100),
        ))


fake = FakeClient


def source(tmp_path: Path, pages=None):
    pages = {"edh/top.json": TOP, "edh/commanders/atraxa-praetors-voice.json": PAGE, **(pages or {})}
    requested = []

    def fetch(url):
        requested.append(url)
        return pages.get(url.split("https://data.example/", 1)[1])

    return guides.Source(tmp_path, "https://data.example", fetch), requested


def run(tmp_path, client, **options):
    src, _ = source(tmp_path)
    return guides.run(
        tmp_path, ["atraxa-praetors-voice"], src, client=client, catalog=CATALOG, banned={"crypt-oracle"},
        fetch_oracle=lambda page: "Flying, vigilance, deathtouch, lifelink\nAt the beginning of your end step, proliferate.",
        now=lambda: NOW, **options,
    )


def written(tmp_path):
    return json.loads((tmp_path / "edh" / "commanders" / "atraxa-praetors-voice" / "guide.json").read_text())


def test_a_guide_is_written_to_the_contract(tmp_path):
    result = run(tmp_path, fake())

    guide = written(tmp_path)
    assert result.written == ["edh/commanders/atraxa-praetors-voice/guide.json"]
    assert list(guide) == ["schema", "slug", "name", "generated_at", "model", "styles", "brackets"]
    assert guide["schema"] == 1 and guide["slug"] == "atraxa-praetors-voice" and guide["name"] == "Atraxa, Praetors' Voice"
    assert guide["generated_at"] == "2026-10-20T09:00:00Z" and guide["model"] == "claude-sonnet-5-5"
    style = guide["styles"][0]
    assert list(style) == ["id", "name", "summary", "brackets", "cards"]
    # The id is the name's slug; the brackets are sorted, each once, with anything but 1 to 5 left out.
    assert style["id"] == "superfriends" and style["brackets"] == [2, 3]
    assert style["cards"][0] == {"name": "Sol Ring", "oracle_id": "ring-oracle", "role": "ramp"}
    assert [style["id"] for style in guide["styles"]] == ["superfriends", "infect", "proliferate-counters"]
    # All five brackets, in order, named by Wizards, whatever order Claude gave them in.
    assert [(b["level"], b["name"]) for b in guide["brackets"]] == [(1, "Exhibition"), (2, "Core"), (3, "Upgraded"), (4, "Optimized"), (5, "cEDH")]
    assert list(guide["brackets"][0]) == ["level", "name", "summary", "cards"]
    assert guide["brackets"][0]["cards"] == [{"name": "Sol Ring", "oracle_id": "ring-oracle", "role": "ramp"}]


def test_cards_are_checked_against_the_catalog(tmp_path):
    styles = answer()["styles"]
    styles[0]["cards"] = [
        card("Sol Ring", "ramp"),
        card("Not A Real Card", "payoff"),
        card("Lightning Bolt", "removal"),  # red, and Atraxa has no red
        card("Mana Crypt", "ramp"),  # banned in Commander
        card("Atraxa, Praetors' Voice", "payoff"),  # the commander itself
        card("sol ring", "ramp"),  # the same card again
        card("Counterspell", "teleport"),  # a role not on the list
        card("Fable of the Mirror-Breaker", "engine"),
        *styles[0]["cards"][1:],
    ]
    run(tmp_path, fake(answer(styles=styles)))

    cards = written(tmp_path)["styles"][0]["cards"]
    assert cards[:2] == [
        {"name": "Sol Ring", "oracle_id": "ring-oracle", "role": "ramp"},
        {"name": "Counterspell", "oracle_id": "counter-oracle", "role": "utility"},
    ]
    names = {card["name"] for card in cards}
    assert not names & {"Not A Real Card", "Lightning Bolt", "Mana Crypt", "Atraxa, Praetors' Voice"}
    assert "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki" not in names


def test_game_changers_keep_to_each_brackets_limit(tmp_path):
    changers = [card(name, "tutor") for name in ("Demonic Tutor", "Vampiric Tutor", "Rhystic Study", "Cyclonic Rift", "Smothering Tithe")]
    brackets = [{"level": level, "summary": "", "cards": [*changers, card("Sol Ring", "ramp")]} for level in range(1, 6)]
    run(tmp_path, fake(answer(brackets=brackets)))

    counts = [len(bracket["cards"]) - 1 for bracket in written(tmp_path)["brackets"]]
    # None at brackets 1 and 2, three at 3, any number at 4 and 5.
    assert counts == [0, 0, 3, 5, 5]


def test_a_guide_missing_a_bracket_or_short_of_styles_is_not_written(tmp_path):
    short = answer(brackets=[{"level": level, "summary": "", "cards": []} for level in (1, 2, 3, 4)])
    few = answer(styles=answer()["styles"][:2])
    for broken in (short, few):
        result = run(tmp_path, fake(broken))
        assert result.failed == ["atraxa-praetors-voice"] and result.written == []
    assert not (tmp_path / "edh" / "commanders" / "atraxa-praetors-voice").exists()
    # Nothing is remembered, so the next run asks again.
    assert not (tmp_path / "state" / "guides.json").exists()


def test_a_refusal_or_a_cut_off_answer_fails_that_commander(tmp_path):
    for stop in ("refusal", "max_tokens"):
        result = run(tmp_path, fake(stop_reason=stop))
        assert result.failed == ["atraxa-praetors-voice"]
        assert result.usage.output == 8000
    assert not (tmp_path / "edh" / "commanders" / "atraxa-praetors-voice").exists()


def test_a_guide_is_asked_for_again_only_when_its_input_changed(tmp_path):
    client = fake()
    run(tmp_path, client)
    state = json.loads((tmp_path / "state" / "guides.json").read_text())
    assert set(state["atraxa-praetors-voice"]) == {"hash", "generated_at", "model"}

    assert run(tmp_path, client).unchanged == ["atraxa-praetors-voice"]
    assert len(client.calls) == 1
    # The same pool with new deck counts inside the same tenth is the same input.
    PAGE["sections"][0]["cards"][0]["decks"] = 905
    assert run(tmp_path, client).unchanged == ["atraxa-praetors-voice"]
    assert run(tmp_path, client, force=True).written
    assert len(client.calls) == 2
    # A new card in the pool asks again.
    PAGE["sections"][1]["cards"].append({"name": "Delay", "decks": 100, "of_decks": 1000, "synergy": 0.2})
    try:
        assert run(tmp_path, client).written
        assert len(client.calls) == 3
    finally:
        PAGE["sections"][1]["cards"].pop()
        PAGE["sections"][0]["cards"][0]["decks"] = 912


def test_a_change_to_the_rules_asks_for_every_guide_again(tmp_path, monkeypatch):
    client = fake()
    run(tmp_path, client)
    monkeypatch.setattr(guides, "_RULES", guides._RULES + "\nOne more rule.")
    assert run(tmp_path, client).written
    assert len(client.calls) == 2


def test_the_request_caches_the_rules_and_not_the_commander(tmp_path):
    client = fake()
    run(tmp_path, client)

    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5" and call["output_config"] == {"effort": "medium"}
    # Sonnet 5.5 refuses a forced tool call, so the tool is strict and the prompt asks for it.
    assert call["tool_choice"] == {"type": "auto"} and call["tools"][0]["strict"] is True
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in call
    system = call["system"]
    assert len(system) == 1 and system[0]["cache_control"] == {"type": "ephemeral"}
    assert "Demonic Tutor" in system[0]["text"] and "Atraxa" not in system[0]["text"]
    message = call["messages"][0]
    assert message["role"] == "user" and isinstance(message["content"], str)
    assert "Atraxa, Praetors' Voice" in message["content"] and "proliferate" in message["content"]


def test_the_commander_message_lists_each_card_once():
    text = guides.commander_message(PAGE, "Flying")

    assert "Colour identity: W U B G" in text
    assert text.count("Sol Ring") == 1
    assert "Sol Ring (~90%) *" in text and "Counterspell (~40%)" in text
    # A card in the average deck the sections never name is listed after them.
    assert text.rstrip().endswith("## Also in the average deck\nArcane Signet")


def test_the_strict_tool_schema_closes_every_object():
    def objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                yield schema
            for value in schema.values():
                yield from objects(value)
        elif isinstance(schema, list):
            for value in schema:
                yield from objects(value)

    found = list(objects(guides.TOOL["input_schema"]))
    assert len(found) == 5
    assert all(o["additionalProperties"] is False and set(o["required"]) == set(o["properties"]) for o in found)


def test_the_game_changers_file_names_each_card_with_its_oracle_id():
    cards = guides.load_game_changers()
    assert len(cards) == 53
    assert all(card["name"] and len(card["oracle_id"]) == 36 for card in cards)
    assert len({card["oracle_id"] for card in cards}) == 53


def test_top_takes_the_weeks_commanders_first():
    assert guides.commander_slugs(TOP, 2) == ["atraxa-praetors-voice", "other-commander"]
    assert guides.commander_slugs(TOP, 1) == ["atraxa-praetors-voice"]
    assert guides.commander_slugs(None, 5) == []


def test_pages_missing_locally_come_from_the_live_site(tmp_path):
    src, requested = source(tmp_path)
    (tmp_path / "edh").mkdir()
    (tmp_path / "edh" / "top.json").write_text(json.dumps(TOP))

    assert src.read("edh/top.json") == TOP
    assert src.read("edh/commanders/atraxa-praetors-voice.json") == PAGE
    assert requested == ["https://data.example/edh/commanders/atraxa-praetors-voice.json"]


def test_oracle_text_reads_both_faces_and_both_partners():
    cards = {
        "https://api.scryfall.com/cards/atraxa-printing": {"name": "Atraxa", "mana_cost": "{G}{W}{U}{B}", "type_line": "Legendary Creature", "oracle_text": "Proliferate."},
        "https://api.scryfall.com/cards/named?exact=Kraum%2C%20Ludevic%27s%20Opus": {"card_faces": [{"name": "Kraum", "oracle_text": "Flying, haste"}]},
        "https://api.scryfall.com/cards/named?exact=Tymna%20the%20Weaver": {"name": "Tymna", "oracle_text": "Lifelink"},
    }
    assert guides.oracle_text(PAGE, cards.get) == "Atraxa - {G}{W}{U}{B} - Legendary Creature\nProliferate."
    pair = {"name": "Kraum, Ludevic's Opus // Tymna the Weaver", "scryfall_id": None}
    assert guides.oracle_text(pair, cards.get) == "Kraum\nFlying, haste\n\nTymna\nLifelink"


def test_the_banned_list_follows_scryfalls_pages():
    pages = {
        "https://api.scryfall.com/cards/search?q=banned%3Acommander&unique=cards": {"has_more": True, "next_page": "page-2", "data": [{"oracle_id": "a"}]},
        "page-2": {"has_more": False, "data": [{"oracle_id": "b"}]},
    }
    assert guides.banned_oracle_ids(pages.get) == {"a", "b"}
    with pytest.raises(guides.GuideError):
        guides.banned_oracle_ids(lambda url: None)


def cli(tmp_path, *args, make_client=None):
    for path, body in {"edh/top.json": TOP, "edh/commanders/atraxa-praetors-voice.json": PAGE}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(json.dumps(body))
    return guides.main(
        [str(tmp_path), "--top", "1", *args],
        make_client=make_client, load_catalog=lambda: CATALOG, fetch_banned=lambda: set(), fetch_oracle=lambda page: "Proliferate.",
    )


def test_the_command_never_shows_the_key(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    caplog.set_level("DEBUG")
    client = fake()
    assert cli(tmp_path, make_client=lambda: client) == 0

    out = capsys.readouterr()
    assert "1 written, 0 unchanged, 0 failed" in out.out and "about $0.08" in out.out
    assert KEY not in out.out + out.err + caplog.text + json.dumps(client.calls)


def test_the_command_stops_without_a_key(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli(tmp_path, make_client=guides._client) == 2
    assert "ANTHROPIC_API_KEY is not set" in caplog.text


def test_a_dry_run_asks_nothing(tmp_path, capsys):
    def no_client():
        raise AssertionError("a dry run built a client")

    assert cli(tmp_path, "--dry-run", make_client=no_client) == 0
    assert "would ask: atraxa-praetors-voice" in capsys.readouterr().out
    assert not (tmp_path / "edh" / "commanders" / "atraxa-praetors-voice").exists()


def test_the_client_reads_the_key_from_the_environment(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert guides._client() is None
