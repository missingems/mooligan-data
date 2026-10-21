from types import SimpleNamespace

from mtgmeta import guide_polish

GUIDE = {
    "slug": "atraxa", "name": "Atraxa, Praetors' Voice", "decks": 1000, "model": None,
    "styles": [{"id": "infect", "name": "Infect", "decks": 400, "brackets": [2, 3], "summary": "Templated.",
                "cards": [{"name": "Blighted Agent", "role": "payoff"}], "lists": [{"level": 3, "combos": ["1-2"]}]}],
    "brackets": [{"level": level, "name": f"B{level}", "decks": 10, "summary": f"Bracket {level}.", "cards": [{"name": "Sol Ring"}]} for level in range(1, 6)],
    "combos": [{"id": "1-2", "bracket": 3, "cards": [{"name": "A"}, {"name": "B"}], "results": ["Infinite mana"]}],
}


class BatchClient:
    """The Message Batches API as `BatchPolisher` uses it: each request is answered by `answer(custom_id, params)`."""

    def __init__(self, answer=None, statuses=("ended",), error=None):
        self.created, self.retrieved = [], 0
        self.answer = answer or (lambda custom_id, params: {"styles": [], "brackets": []})
        self.statuses, self.error = list(statuses), error
        self.messages = SimpleNamespace(batches=SimpleNamespace(create=self.create, retrieve=self.retrieve, results=self.results))

    def create(self, requests):
        if self.error:
            raise self.error
        self.created.append(requests)
        return SimpleNamespace(id=f"batch-{len(self.created)}")

    def retrieve(self, batch_id):
        status = self.statuses[min(self.retrieved, len(self.statuses) - 1)]
        self.retrieved += 1
        return SimpleNamespace(id=batch_id, processing_status=status)

    def results(self, batch_id):
        requests = self.created[int(batch_id.split("-")[1]) - 1]
        for each in requests:
            answer = self.answer(each["custom_id"], each["params"])
            if answer is None:
                yield SimpleNamespace(custom_id=each["custom_id"], result=SimpleNamespace(type="errored"))
                continue
            usage = SimpleNamespace(input_tokens=3600, output_tokens=1800, cache_creation_input_tokens=0, cache_read_input_tokens=0)
            content = [SimpleNamespace(type="thinking"), SimpleNamespace(type="tool_use", name="write_summaries", input=answer)]
            message = SimpleNamespace(stop_reason="tool_use", model="claude-sonnet-5-5", content=content, usage=usage)
            yield SimpleNamespace(custom_id=each["custom_id"], result=SimpleNamespace(type="succeeded", message=message))


def polisher(client, wait_minutes=30):
    clock = iter(range(0, 10**6, 60))
    return guide_polish.BatchPolisher(client, wait_minutes=wait_minutes, poll_seconds=60, sleep=lambda seconds: None, clock=lambda: next(clock))


def test_the_facts_carry_the_styles_combos_and_brackets():
    facts = guide_polish.facts(GUIDE)
    assert "## Style infect: Infect" in facts and "Blighted Agent (payoff)" in facts
    assert "Combo (bracket 3): A + B -> Infinite mana" in facts and "## Bracket 5: B5" in facts


def test_one_batch_carries_every_guide_and_its_answers_replace_only_the_summaries():
    client = BatchClient(lambda custom_id, params: {"styles": [{"id": "infect", "summary": "Poison them out."}], "brackets": [{"level": 3, "summary": "Tuned."}]})
    other = {**GUIDE, "slug": "a" * 80}
    batch_polisher = polisher(client)

    batch = batch_polisher.submit([GUIDE, other])
    assert batch_polisher.wait(batch)
    collected = batch_polisher.collect(batch)

    assert len(client.created) == 1 and [each["custom_id"] for each in client.created[0]] == ["g0", "g1"]
    answer, model = collected.answers["atraxa"]
    polished = guide_polish.apply(GUIDE, answer, model)
    assert polished["model"] == "claude-sonnet-5-5" and polished["styles"][0]["summary"] == "Poison them out."
    assert [bracket["summary"] for bracket in polished["brackets"]] == ["Bracket 1.", "Bracket 2.", "Tuned.", "Bracket 4.", "Bracket 5."]
    assert polished["styles"][0]["cards"] == GUIDE["styles"][0]["cards"]
    assert set(collected.answers) == {"atraxa", "a" * 80}
    assert (collected.usage.input_tokens, collected.usage.output_tokens) == (7200, 3600)
    assert round(collected.usage.dollars(), 4) == 0.0252


def test_the_request_asks_for_the_tool_without_forcing_it_or_naming_fallbacks():
    """Sonnet 5.5 refuses a forced tool choice, and the Batches API refuses fallbacks and their beta."""
    call = guide_polish.request(GUIDE)
    assert call["model"] == "claude-sonnet-5-5" and call["tool_choice"] == {"type": "auto"}
    assert "betas" not in call and "fallbacks" not in call and "thinking" not in call
    assert call["tools"][0]["strict"] is True and "Call the write_summaries tool once" in call["system"][0]["text"]


def test_a_failed_or_toolless_answer_keeps_the_templated_guide(caplog):
    client = BatchClient(lambda custom_id, params: None)
    batch_polisher = polisher(client)
    collected = batch_polisher.collect(batch_polisher.submit([GUIDE]))
    assert collected.answers == {} and collected.failed == {"atraxa": "errored"}


def test_a_batch_still_running_after_the_wait_is_left_for_later():
    client = BatchClient(statuses=("in_progress",))
    batch_polisher = polisher(client, wait_minutes=5)
    assert batch_polisher.wait(batch_polisher.submit([GUIDE])) is False
    assert client.retrieved >= 5


def test_the_polish_hash_moves_with_the_facts_only():
    same = {**GUIDE, "generated_at": "later"}
    moved = {**GUIDE, "decks": 1001}
    assert guide_polish.polish_hash(same) == guide_polish.polish_hash(GUIDE) != guide_polish.polish_hash(moved)


def test_a_last_polish_carries_over_only_onto_the_same_styles_and_brackets():
    previous = guide_polish.apply(GUIDE, {"styles": [{"id": "infect", "summary": "Old prose."}], "brackets": []}, "claude-sonnet-5-5")
    carried = guide_polish.carry_over(GUIDE, previous)
    assert carried["model"] == "claude-sonnet-5-5" and carried["styles"][0]["summary"] == "Old prose."
    assert guide_polish.carry_over({**GUIDE, "styles": []}, previous) is None
    assert guide_polish.carry_over(GUIDE, GUIDE) is None


def test_no_key_no_polisher(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert guide_polish.make_polisher() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key")
    monkeypatch.setenv("GUIDE_POLISH", "0")
    assert guide_polish.make_polisher() is None


def test_the_strict_tool_schema_closes_every_object():
    def objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                yield schema
            for value in schema.values():
                yield from objects(value)

    assert all(each.get("additionalProperties") is False for each in objects(guide_polish.TOOL["input_schema"]))
