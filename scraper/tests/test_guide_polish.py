from types import SimpleNamespace

from mtgmeta import guide_polish

GUIDE = {
    "slug": "atraxa", "name": "Atraxa, Praetors' Voice", "decks": 1000, "model": None,
    "styles": [{"id": "infect", "name": "Infect", "decks": 400, "brackets": [2, 3], "summary": "Templated.",
                "cards": [{"name": "Blighted Agent", "role": "payoff"}], "lists": [{"level": 3, "combos": ["1-2"]}]}],
    "brackets": [{"level": level, "name": f"B{level}", "decks": 10, "summary": f"Bracket {level}.", "cards": [{"name": "Sol Ring"}]} for level in range(1, 6)],
    "combos": [{"id": "1-2", "bracket": 3, "cards": [{"name": "A"}, {"name": "B"}], "results": ["Infinite mana"]}],
}


class Client:
    def __init__(self, tool_input=None, error=None):
        self.calls = []
        self.tool_input, self.error = tool_input, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **call):
        self.calls.append(call)
        if self.error:
            raise self.error
        message = SimpleNamespace(stop_reason="tool_use", model="claude-sonnet-5-5",
                                  content=[SimpleNamespace(type="tool_use", name="write_summaries", input=self.tool_input)])
        return Stream(message)


class Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def test_the_facts_carry_the_styles_combos_and_brackets():
    facts = guide_polish.facts(GUIDE)
    assert "## Style infect: Infect" in facts and "Blighted Agent (payoff)" in facts
    assert "Combo (bracket 3): A + B -> Infinite mana" in facts and "## Bracket 5: B5" in facts


def test_polish_replaces_the_summaries_it_gets_and_keeps_the_rest():
    client = Client({"styles": [{"id": "infect", "summary": "Poison them out."}], "brackets": [{"level": 3, "summary": "Tuned."}]})
    polished = guide_polish.Polisher(client)(GUIDE)

    assert polished["model"] == "claude-sonnet-5-5" and polished["styles"][0]["summary"] == "Poison them out."
    assert [bracket["summary"] for bracket in polished["brackets"]] == ["Bracket 1.", "Bracket 2.", "Tuned.", "Bracket 4.", "Bracket 5."]
    assert polished["styles"][0]["cards"] == GUIDE["styles"][0]["cards"]
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": "write_summaries"}


def test_a_failed_polish_keeps_the_templated_guide():
    assert guide_polish.Polisher(Client(error=RuntimeError("overloaded")))(GUIDE) is GUIDE


def test_no_key_no_polisher(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert guide_polish.make_polisher() is None


def test_the_strict_tool_schema_closes_every_object():
    def objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                yield schema
            for value in schema.values():
                yield from objects(value)

    assert all(each.get("additionalProperties") is False for each in objects(guide_polish.TOOL["input_schema"]))
