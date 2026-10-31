import json
from datetime import date
from types import SimpleNamespace

import pytest

from mtgmeta import guides, primers

TODAY = date(2026, 11, 1)

CATALOG = {}


def add(name, text="", type_line="Instant", cost="{1}"):
    CATALOG[guides.card_slug(name)] = {"name": name, "oracle_id": f"{guides.card_slug(name)}-oracle", "type_line": type_line, "oracle_text": text, "mana_cost": cost}


for card in ("Bolt", "Shock", "Island", "Thoughtseize", "Fatal Push", "Ragavan", "Counterspell", "Wrath", "Negate", "Duress", "Goblin Maker"):
    add(card, "Deal 3 damage to any target.")
CATALOG[guides.card_slug("Goblin Maker")]["oracle_text"] = "Create a 1/1 red Goblin Scout creature token."
LOOKUP = guides.catalog_lookup(CATALOG)


def row(id, name, share):
    return {"id": id, "name": name, "share_30d": share, "share_7d": share, "deck_count_30d": 100, "top8_30d": 10, "wins_30d": 2, "colors": ["R"], "key_cards": [{"name": "Bolt"}]}


def archetype(id, main, side=None, hand=None, **extra):
    main = main or {}
    side = side if side is not None else {"Negate": 2, "Duress": 2}
    return {
        "id": id, "name": id.split("-", 1)[1].title(), "format": "modern", "colors": ["R"], "shares": {"7d": 10.0, "14d": 10.0, "30d": 10.0},
        "cards": {
            "window": "7d", "deck_count": 30, "list_count": 20,
            "main": [{"name": name, "share": 100.0, "copies": float(copies)} for name, copies in main.items()],
            "side": [{"name": name, "share": 90.0, "copies": float(copies)} for name, copies in side.items()],
        },
        "hand": [{"name": name} for name in (hand or list(main)[:5])],
        "consensus": {"main": [{"name": name, "quantity": copies} for name, copies in main.items()], "side": [{"name": name, "quantity": copies} for name, copies in side.items()]},
        "decks": [{"date": "2026-10-30", "finish": "1st Place", "event_name": "Modern Challenge 64", "event": {"name": "Modern Challenge 64", "prestige": 3}}],
        **extra,
    }


MAIN = {"Bolt": 4, "Shock": 4, "Ragavan": 4, "Island": 20}


def explore():
    return {"formats": [{"format": "modern", "name": "Modern", "standings": [
        row("modern-alpha", "Alpha", 20.0), row("modern-beta", "Beta", 15.0), row("modern-gamma", "Gamma", 10.0),
        row("modern-delta", "Delta", 5.0), row("modern-omega", "Omega", 1.0),
    ]}]}


def results(count, wins=1):
    return [{"date": "2026-10-30T00:00:00Z", "finish": "1st Place" if index < wins else "5-0"} for index in range(count)]


def snapshot():
    """The standings' archetypes and three past them: rho and sigma with enough results, tau without."""
    counts = {"modern-alpha": 30, "modern-beta": 25, "modern-gamma": 20, "modern-delta": 20, "modern-omega": 3, "modern-rho": 15, "modern-sigma": 12, "modern-tau": 9}
    month = [{"id": "modern-sigma", "name": "Sigma", "percentage": 0.5, "deck_count": 12, "colors": ["U"], "key_cards": [{"name": "Counterspell"}]}]
    return {
        "format": "modern",
        "meta": {"30d": {"archetypes": month}, "7d": {"archetypes": []}},
        "archetypes": {archetype_id: {"name": archetype_id.split("-")[1].title(), "results": results(count)} for archetype_id, count in counts.items()},
        "merges": {"modern-old-beta": "modern-beta"},
    }


def data():
    return {
        "explore.json": explore(),
        "snapshots/modern.json": snapshot(),
        "archetypes/modern-alpha.json": archetype("modern-alpha", MAIN),
        "archetypes/modern-beta.json": archetype("modern-beta", MAIN),
        "archetypes/modern-gamma.json": archetype("modern-gamma", {"Bolt": 4, "Counterspell": 4, "Wrath": 4, "Island": 20}),
        "archetypes/modern-delta.json": archetype("modern-delta", MAIN),
        "archetypes/modern-omega.json": archetype("modern-omega", MAIN),
        "archetypes/modern-old-beta.json": archetype("modern-beta", MAIN, merged_into="modern-beta"),
        "archetypes/modern-rho.json": archetype("modern-rho", MAIN),
        "archetypes/modern-sigma.json": archetype("modern-sigma", MAIN),
        "archetypes/modern-tau.json": archetype("modern-tau", MAIN),
    }


def primer_row(id, archetype, updated="2026-10-20", version=1):
    return {"id": id, "archetype": archetype, "format": "Modern", "title": archetype, "written": "2026-10-19", "updated": updated, "version": version}


def markdown(archetype="modern-alpha", matchup="modern-beta", brought="2 [[Negate]]", taken="2 [[Shock]]", extra=""):
    return f"""---
archetype: {archetype}
format: Modern
title: Alpha
author: Greg
written: 2026-11-01
updated: 2026-11-01
type: [aggro]
---

## The deck

Burn them out.

## Main cards

:::cards
4 [[Bolt]] Three damage.
4 [[Shock]] Two damage.
4 [[Ragavan]] Treasure.
:::

## Gotchas and tips

:::tip Point it at the face
[[Bolt]] goes face. {extra}
:::

## Matchups and sideboarding

:::matchup "Beta" archetype={matchup}
about: Burn too.
key: [[Bolt]]
in: {brought}
out: {taken}
Bring in Negate.
:::
"""


class FakeApi:
    """The routes `primers.Api` calls, answering as api.mooligan.com does."""

    def __init__(self, rows=(), sources=None):
        self.rows = list(rows)
        self.sources = dict(sources or {})
        self.puts = []
        self.calls = []

    def __call__(self, method, url, body=None, headers=None):
        self.calls.append((method, url))
        path = url.split("api.test", 1)[1]
        if method == "GET" and path == "/v1/primers":
            return 200, self.rows
        if method == "GET" and path.endswith("/source"):
            primer_id = path.split("/")[3]
            if primer_id in self.sources:
                return 200, {"id": primer_id, "markdown": self.sources[primer_id], "author": "greg", "version": 1}
            return 404, {"error": "Primer not found"}
        if method == "POST" and path == "/mcp":
            name = body["params"]["name"]
            if name == "format_guide":
                return 200, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "# playgraph\nThe format."}]}}
            text = body["params"]["arguments"]["markdown"]
            fields = dict(line.split(": ", 1) for line in text.split("---")[1].strip().splitlines() if ": " in line)
            broken = "BROKEN" in text
            answer = {
                "valid": not broken, "archetype": fields.get("archetype", ""), "format": fields.get("format", ""),
                "diagnostics": [{"block": "Combo", "line": 2, "severity": "error", "message": "Two arrows in a row"}] if broken else [],
                "cards": sorted(primers.linked(text)),
            }
            return 200, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(answer)}]}}
        if method == "PUT":
            assert headers["Authorization"] == "Bearer secret"
            self.puts.append((path, body))
            return 201, {"id": path.rsplit("/", 1)[1], "version": 2}
        raise AssertionError(f"unexpected {method} {url}")


def api(rows=(), sources=None, token="secret"):
    fake = FakeApi(rows, sources)
    return primers.Api("https://api.test", token, fake), fake


class Reader:
    def __init__(self, files):
        self.files = files

    def read(self, path):
        return self.files.get(path)


class Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class Client:
    """Answers each `beta.messages.stream` call with the next of `replies`, and keeps what it was sent."""

    def __init__(self, *replies, output_tokens=20000):
        self.replies = list(replies)
        self.sent = []
        self.output_tokens = output_tokens
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **params):
        self.sent.append(json.loads(json.dumps(params, default=lambda block: block.__dict__)))
        reply = self.replies.pop(0)
        content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=reply)]
        usage = SimpleNamespace(input_tokens=13000, output_tokens=self.output_tokens, cache_creation_input_tokens=0, cache_read_input_tokens=5000)
        return Stream(SimpleNamespace(stop_reason="end_turn", model=primers.MODEL, content=content, usage=usage))


def test_moved_counts_cards_in_or_out_and_a_grid_only_out():
    before = {"Bolt": 4, "Shock": 4, "Island": 20}
    assert primers.moved(before, {"Bolt": 4, "Shock": 1, "Ragavan": 3, "Island": 20}) == 3
    assert primers.moved(before, {"Bolt": 4, "Island": 18, "Ragavan": 4, "Fatal Push": 2}) == 6
    assert primers.moved({"Bolt": 4, "Shock": 4}, {"Bolt": 1}, partial=True) == 7


def test_grid_reads_the_main_cards_grid():
    assert primers.grid(markdown()) == {"Bolt": 4, "Shock": 4, "Ragavan": 4}


def test_plan_orders_the_first_archetypes_missing_changed_and_old_then_the_ones_with_enough_results():
    files = data()
    rows = [
        primer_row("modern-old-beta", "modern-old-beta"),
        primer_row("modern-gamma", "modern-gamma"),
        primer_row("modern-delta", "modern-delta", updated="2026-09-25"),
        primer_row("modern-omega", "modern-omega", updated="2026-09-01"),
        primer_row("modern-rho", "modern-rho", updated="2026-10-25"),
    ]
    state = {"modern-gamma": {"version": 1, "consensus": MAIN}, "modern-rho": {"version": 1, "consensus": MAIN}}
    client, _ = api(rows, {"modern-old-beta": markdown("modern-old-beta"), "modern-delta": markdown("modern-delta")})
    items, notes = primers.plan(files["explore.json"], ["modern"], 4, client.primers(), files.get, state, client, TODAY)
    assert [(item.id, item.primer_id, item.tier) for item in items] == [
        ("modern-alpha", "modern-alpha", 0), ("modern-beta", "modern-beta", 0), ("modern-gamma", "modern-gamma", 0),
        ("modern-delta", "modern-delta", 0), ("modern-sigma", "modern-sigma", 1),
    ]
    assert items[0].reasons == ["no primer"]
    # The primer of an archetype merged into beta is not beta's: a new one is written under beta's id, from its text.
    assert items[1].reasons == ["no primer, but modern-old-beta was written for modern-old-beta, since merged into it"]
    assert items[1].primer is None and items[1].previous.id == "modern-old-beta"
    assert items[2].reasons == ["8 main deck cards changed since it was written"]
    assert items[3].reasons == ["updated 37 days ago"]
    # Past the first four: rho is up to date, sigma has no primer, omega and tau have too few results.
    assert items[4].reasons == ["no primer"]
    assert {key: items[4].row[key] for key in ("name", "share_30d", "deck_count_30d", "top8_30d", "wins_30d", "results")} == {
        "name": "Sigma", "share_30d": 0.5, "deck_count_30d": 12, "top8_30d": 1, "wins_30d": 1, "results": 12,
    }
    assert notes == []


def test_plan_writes_at_most_backfill_primers_past_the_first_archetypes_the_formats_taking_turns():
    files = data()
    files["explore.json"]["formats"].append({"format": "pauper", "name": "Pauper", "standings": [row("pauper-one", "One", 30.0)]})
    files["snapshots/pauper.json"] = {"archetypes": {"pauper-one": {"results": results(30)}, "pauper-two": {"results": results(11)}}, "merges": {}}
    files["archetypes/pauper-one.json"] = archetype("pauper-one", MAIN)
    files["archetypes/pauper-two.json"] = archetype("pauper-two", MAIN)
    client, _ = api()
    items, notes = primers.plan(files["explore.json"], ["modern", "pauper"], 2, client.primers(), files.get, {}, client, TODAY, backfill=3)
    # The first two of each by share; then each format's next by results, in turns: Pauper's two (11 results) comes
    # before Modern's delta (20), and rho (15) and sigma (12) wait.
    assert [item.id for item in items] == ["pauper-one", "modern-alpha", "modern-beta", "modern-gamma", "pauper-two", "modern-delta"]
    assert notes == ["2 past the first 2 wait for the next runs, at most 3 a run"]


def test_a_new_top_card_is_one_the_deck_did_not_play_not_a_reordering():
    primer = primers.Published.of(primer_row("modern-alpha", "modern-alpha"))
    state = {"version": 1, "consensus": MAIN}
    reordered = archetype("modern-alpha", MAIN, hand=["Shock", "Bolt"])
    assert primers.reasons_for(reordered, primer, state, None, TODAY) == ([], 3)
    new = archetype("modern-alpha", {**MAIN, "Fatal Push": 2}, hand=["Fatal Push", "Bolt"])
    assert primers.reasons_for(new, primer, state, None, TODAY)[0] == ["its top card Fatal Push is new to the deck"]
    # A hand-written primer has no state: its grid stands in, and a top card it never names is new.
    reasons, rank = primers.reasons_for(new, primer, None, markdown(), TODAY)
    assert (reasons, rank) == (["its top card Fatal Push is not in the primer"], 1)
    # State from a version since edited by hand is not used.
    assert primers.reasons_for(new, primer, {"version": 3, "consensus": MAIN}, markdown(), TODAY)[0] == ["its top card Fatal Push is not in the primer"]


def test_plan_with_archetype_writes_it_even_when_not_due():
    files = data()
    client, _ = api([primer_row("modern-delta", "modern-delta")], {"modern-delta": markdown("modern-delta")})
    items, _ = primers.plan(files["explore.json"], ["modern"], 4, client.primers(), files.get, {}, client, TODAY, only=["modern-delta", "modern-tau"])
    # tau has too few results to be due, but can still be asked for.
    assert [(item.id, item.reasons) for item in items] == [("modern-delta", ["asked for"]), ("modern-tau", ["no primer"])]


def test_an_archetype_with_no_lists_is_skipped():
    files = data()
    files["archetypes/modern-alpha.json"] = archetype("modern-alpha", {})
    client, _ = api()
    items, notes = primers.plan(files["explore.json"], ["modern"], 1, client.primers(), files.get, {}, client, TODAY, min_results=100)
    assert items == [] and notes == ["modern-alpha: no stored lists, so no primer"]


def item(id="modern-alpha", primer=None):
    files = data()
    block = files["explore.json"]["formats"][0]
    row_ = next(each for each in block["standings"] if each["id"] == id)
    return primers.Item(block, row_, files[f"archetypes/{id}.json"], primer, primer.id if primer else id, ["no primer"], 0)


def validate(text):
    client, _ = api()
    return client.validate(text)


def test_check_passes_a_good_primer():
    text = markdown()
    assert primers.check(text, validate(text), item(), LOOKUP, {"modern-alpha", "modern-beta"}, list(MAIN)) == []


def test_check_finds_each_kind_of_problem():
    text = markdown(matchup="modern-nope", brought="3 [[Fatal Push]]", taken="2 [[Negate]]", extra="[[Made Up Card]] BROKEN")
    problems = [str(problem) for problem in primers.check(text, validate(text), item(), LOOKUP, {"modern-alpha", "modern-beta"}, list(MAIN))]
    assert problems == [
        "format: Combo, line 2: Two arrows in a row",
        "card: [[Made Up Card]] is not a card Scryfall knows, nor a token the deck's cards make",
        "matchup: matchup 'Beta': archetype=modern-nope is not an archetype of Modern",
        "matchup: matchup 'Beta': in: [[Fatal Push]] is not one of the deck's sideboard cards",
        "matchup: matchup 'Beta': out: [[Negate]] is not one of the deck's main deck cards",
        "matchup: matchup 'Beta': brings in 3 cards and takes out 2",
    ]


def test_check_accepts_a_token_its_cards_make():
    text = markdown(extra="It makes a [[Goblin Scout]].")
    problems = primers.check(text, validate(text), item(), LOOKUP, {"modern-alpha", "modern-beta"}, list(MAIN) + ["Goblin Maker"])
    assert problems == []
    problems = primers.check(text, validate(text), item(), LOOKUP, {"modern-alpha", "modern-beta"}, list(MAIN))
    assert [problem.kind for problem in problems] == ["card"]


def test_check_wants_the_archetype_and_format_it_was_written_for():
    text = markdown("modern-beta")
    problems = primers.check(text, validate(text), item(), LOOKUP, {"modern-alpha", "modern-beta"}, list(MAIN))
    assert [str(problem) for problem in problems] == ["format: front matter archetype is 'modern-beta', not 'modern-alpha'"]


def test_markdown_of_takes_the_primer_from_the_reply():
    message = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Here it is:\n```markdown\n" + markdown() + "```\n")])
    assert primers.markdown_of(message) == markdown()
    with pytest.raises(primers.PrimerError, match="declined"):
        primers.markdown_of(SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(primers.PrimerError, match="front matter"):
        primers.markdown_of(SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="No.")]))


def test_facts_give_the_lists_the_opponents_and_the_primer_it_has():
    files = data()
    text, named = primers.facts(item(), files.get, LOOKUP, "OLD PRIMER", TODAY)
    assert "archetype: modern-alpha\nformat: Modern\ntitle: Alpha\nauthor: Greg\nwritten: 2026-11-01\nupdated: 2026-11-01" in text
    assert "4 Bolt (in 100.0% of the lists)" in text
    assert "## Consensus sideboard\n2 Negate (in 90.0% of the lists)" in text
    assert "- Beta (id modern-beta): 15.0% of the format over 30 days; key cards: Bolt, Shock, Ragavan, Island" in text
    assert "2026-10-30: 1st Place, Modern Challenge 64" in text
    assert "- Bolt ({1}; Instant): Deal 3 damage to any target." in text
    assert text.endswith("## The primer it has now\n\nOLD PRIMER")
    assert named[:4] == ["Bolt", "Shock", "Ragavan", "Island"]


def test_facts_of_a_merged_archetype_start_from_its_old_primer():
    files = data()
    old = primers.Published.of(primer_row("modern-old-beta", "modern-old-beta"))
    beta = item("modern-beta")
    merged = primers.Item(beta.format, beta.row, beta.archetype, None, "modern-beta", ["no primer"], 0, merged_from=old)
    text, _ = primers.facts(merged, files.get, LOOKUP, "OLD PRIMER", TODAY)
    assert "archetype: modern-beta\nformat: Modern\ntitle: Beta\nauthor: Greg\nwritten: 2026-11-01" in text
    assert text.endswith("## The primer of modern-old-beta, since merged into this archetype\n\nOLD PRIMER")


def run(client, budget=5.0, publish=True, items=None, tmp_path=None, token="secret"):
    fake_api, fake = api(token=token)
    writer = primers.Writer(client, primers.system_prompt("# playgraph", "EXAMPLE"))
    state = {}
    result = primers.run(
        tmp_path, items or [item()], writer=writer, api=fake_api, read=data().get, lookup=LOOKUP, budget=primers.Budget(budget),
        publish=publish, state=state, today=TODAY,
    )
    return result, fake, state


def test_run_sends_a_draft_back_with_its_problems_then_publishes_it(tmp_path):
    client = Client(markdown(matchup="modern-nope"), markdown())
    result, fake, state = run(client, tmp_path=tmp_path)
    assert result.published == ["modern-alpha"] and result.failed == []
    first, second = client.sent
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "high"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"} and "# playgraph" in first["system"][0]["text"]
    assert [message["role"] for message in second["messages"]] == ["user", "assistant", "user"]
    assert "archetype=modern-nope is not an archetype of Modern" in second["messages"][2]["content"]
    [(path, body)] = fake.puts
    assert path == "/v1/primers/modern-alpha" and body["markdown"] == markdown() and body["author"] == "greg"
    assert body["note"] == "Written by claude-opus-5-5 from 20 lists of the last 7 days on 2026-11-01: no primer"
    assert state["modern-alpha"]["consensus"] == MAIN and state["modern-alpha"]["version"] == 2
    assert json.loads((tmp_path / "state" / "primers.json").read_text()) == state
    assert (tmp_path / "primers" / "modern-alpha.md").read_text() == markdown()
    assert not (tmp_path / "primers" / "modern-alpha.problems.txt").exists()
    # Two calls of 13k input, 20k output and 5k cache read tokens at $4, $20 and $0.20 a million.
    assert result.spent == pytest.approx(2 * (13000 * 4 + 20000 * 20 + 5000 * 0.2) / 1e6)


def test_run_keeps_a_primer_that_still_has_problems(tmp_path):
    bad = markdown(matchup="modern-nope")
    result, fake, state = run(Client(bad, bad), tmp_path=tmp_path)
    assert result.failed == ["modern-alpha"] and fake.puts == [] and state == {}
    assert "archetype=modern-nope" in (tmp_path / "primers" / "modern-alpha.problems.txt").read_text()


def test_run_without_publish_only_drafts(tmp_path):
    result, fake, state = run(Client(markdown()), publish=False, tmp_path=tmp_path)
    assert result.drafted == ["modern-alpha"] and fake.puts == [] and state == {}


def test_run_stops_before_the_budget_and_leaves_the_rest(tmp_path):
    items = [item(), item("modern-delta")]
    # The first call costs $0.453; the next is taken to cost $0.60, which would pass $1.
    result, _, _ = run(Client(markdown()), budget=1.0, items=items, tmp_path=tmp_path)
    assert result.published == ["modern-alpha"] and result.deferred == ["modern-delta"]


def test_run_starts_no_primer_after_its_minutes(tmp_path):
    fake_api, fake = api()
    ticks = iter([0, 0, 61 * 60])
    result = primers.run(
        tmp_path, [item(), item("modern-delta")], writer=primers.Writer(Client(markdown()), "SYSTEM"), api=fake_api, read=data().get,
        lookup=LOOKUP, budget=primers.Budget(50), publish=True, state={}, today=TODAY, minutes=60, clock=lambda: next(ticks),
    )
    assert result.published == ["modern-alpha"] and result.deferred == ["modern-delta"]


def test_main_plan_needs_no_key(capsys, tmp_path):
    fake_api, fake = api([primer_row("modern-delta", "modern-delta", updated="2026-09-25")], {"modern-delta": markdown("modern-delta")}, token=None)
    code = primers.main([str(tmp_path), "--format", "modern", "--count", "4", "--plan"], api=fake_api, source=Reader(data()), today=TODAY)
    out = capsys.readouterr().out
    assert code == 0
    assert "modern   modern-alpha" in out and "modern   modern-delta" in out and "updated 37 days ago" in out
    assert "6 primers due" in out and "modern   modern-sigma" in out
    assert not any(method == "PUT" for method, _ in fake.calls)


def test_main_writes_and_publishes(capsys, tmp_path):
    fake_api, fake = api()
    client = Client(markdown())
    code = primers.main(
        [str(tmp_path), "--format", "modern", "--archetype", "modern-alpha", "--publish"], api=fake_api, source=Reader(data()), client=client,
        load_catalog=lambda: CATALOG, today=TODAY,
    )
    assert code == 0 and [path for path, _ in fake.puts] == ["/v1/primers/modern-alpha"]
    assert "1 published, 0 drafted, 0 failed, 0 left for the next run" in capsys.readouterr().out


def test_main_will_not_publish_without_the_token(tmp_path):
    fake_api, _ = api(token=None)
    code = primers.main(
        [str(tmp_path), "--format", "modern", "--count", "1", "--publish"], api=fake_api, source=Reader(data()), client=Client(),
        load_catalog=lambda: CATALOG, today=TODAY,
    )
    assert code == 2


def test_main_writes_no_commander_primers(tmp_path):
    assert primers.main([str(tmp_path), "--format", "commander", "--plan"], api=api()[0], source=Reader(data())) == 2


def test_check_published_reports_each_primer(capsys):
    rows = [primer_row("modern-alpha", "modern-alpha"), primer_row("modern-old-beta", "modern-old-beta"), primer_row("modern-sigma", "modern-sigma")]
    sources = {"modern-alpha": markdown(), "modern-old-beta": markdown("modern-old-beta"), "modern-sigma": markdown("modern-sigma", extra="[[Made Up Card]]")}
    fake_api, _ = api(rows, sources)
    checked, broken = primers.check_published(explore(), ["modern"], 2, fake_api, data().get, LOOKUP, TODAY)
    out = capsys.readouterr().out
    # The primer under an id merged away is not beta's, so it is not checked; sigma's is, for its 12 results.
    assert (checked, broken) == (2, 1)
    assert "modern-alpha: ok" in out and "modern-sigma: 1 problems" in out and "[[Made Up Card]]" in out and "old-beta" not in out
