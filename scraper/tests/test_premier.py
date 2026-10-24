import json
from datetime import datetime, timezone
from types import SimpleNamespace

from mtgmeta.premier import calendar_from_html, premier_events, region_of
from mtgmeta.premier_formats import FORMATS, article_text, load_overrides, rule_formats, tag_formats

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)

# The schedule page embeds its state as a function call, the way Nuxt 2 does.
HTML = """<html><body><script>window.__NUXT__=(function(a,b){return {layout:"default",fetch:{"EventsCalendar:0":{payload:[
{id:"e1",entryTitle:a,eventName:a,eventScheduleType:{typeTitle:"Championships"},startTime:"2026-10-16T10:00+08:00",endTime:"2026-10-18T18:00+08:00",gameType:"Tabletop",link:b},
{id:"e2",entryTitle:"Old one",eventName:"SEA Championship: Bangkok",eventScheduleType:{typeTitle:"Championships"},startTime:"2026-03-13T10:00+07:00",endTime:"2026-03-15T18:00+07:00",gameType:"Tabletop",link:b},
{id:"e3",entryTitle:"PT",eventName:"Pro Tour Nauctis",eventScheduleType:{typeTitle:"Pro Tour"},startTime:"2027-02-26T09:00-08:00",endTime:"2027-02-28T18:00-08:00",gameType:"Tabletop",link:"https://magic.gg/events/pro-tour-nauctis"}
]}}}}("SEA Championship Final: Singapore","https://magic.gg/news/x"));</script></body></html>"""


def test_the_calendar_is_read_out_of_the_nuxt_state():
    entries = calendar_from_html(HTML)
    assert [entry["id"] for entry in entries] == ["e1", "e2", "e3"]
    assert entries[0]["eventName"] == "SEA Championship Final: Singapore"


def test_upcoming_events_are_published_with_place_and_region():
    events = premier_events(calendar_from_html(HTML), now=NOW)
    assert [event["name"] for event in events] == ["SEA Championship Final: Singapore", "Pro Tour Nauctis"]
    sea = events[0]
    assert (sea["start"], sea["end"], sea["place"], sea["region"], sea["type"]) == (
        "2026-10-16", "2026-10-18", "Singapore", "southeast_asia", "Championships",
    )
    assert events[1]["region"] is None and events[1]["url"] == "https://magic.gg/events/pro-tour-nauctis"


def test_regions_come_from_the_name():
    assert region_of("Ultimate Guard Magic Regional Championship: Ghent") == "europe"
    assert region_of("Regional Championship at SCG: Los Angeles") == "usa"
    assert region_of("Champions Cup: Yokohama") == "japan"
    assert region_of("Super Series Finals: Sydney") == "australia_nz"
    assert region_of("MIT Championship: Taipei City") == "chinese_taipei"
    assert region_of("Magic World Championship 32") is None


def test_dates_are_the_venues_own_days():
    html = HTML.replace('startTime:"2027-02-26T09:00-08:00",endTime:"2027-02-28T18:00-08:00"', 'startTime:"2026-10-02T10:00-04:00",endTime:"2026-10-04T20:00-04:00"')
    ottawa = [e for e in premier_events(calendar_from_html(html), now=NOW) if e["name"] == "Pro Tour Nauctis"][0]
    # 20:00 in Ottawa is already the 5th in UTC, but the event ends on the 4th.
    assert (ottawa["start"], ottawa["end"]) == ("2026-10-02", "2026-10-04")


def event(**fields):
    return {"id": "x", "name": "Some Event", "type": "Championships", "start": "2026-10-16", "end": "2026-10-18",
            "url": "https://magic.gg/news/a", **fields}


class FakeClaude:
    def __init__(self, formats=("Modern",), stop_reason="end_turn"):
        self.calls = []
        self.formats, self.stop_reason = formats, stop_reason
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **params):
        self.calls.append(params)
        block = SimpleNamespace(type="text", text=json.dumps({"formats": list(self.formats)}))
        return SimpleNamespace(stop_reason=self.stop_reason, content=[block])


def page(text="Round 2 Regional Championship Qualifiers are Modern."):
    return lambda url: text


def test_rules_read_the_type_and_the_name():
    assert rule_formats({"name": "CommandFest Leicester", "type": "CommandFest"}) == ["Commander"]
    assert rule_formats({"name": "Modern Open: Paris", "type": "Convention"}) == ["Modern"]
    assert rule_formats({"name": "Standard and Draft Showdown", "type": None}) == ["Standard", "Limited"]
    assert rule_formats({"name": "Pro Tour Nauctis", "type": "Pro Tour"}) == []
    assert rule_formats({"name": "Modernity Fest", "type": "Convention"}) == []


def test_published_events_carry_the_rules_formats():
    html = HTML.replace("Pro Tour Nauctis", "Pro Tour Modern")
    events = premier_events(calendar_from_html(html), now=NOW)
    assert [e["formats"] for e in events] == [[], ["Modern"]]


def test_the_rules_settle_an_event_without_claude():
    events = [event(name="CommandFest Marl", type="CommandFest")]
    client = FakeClaude()
    cache = tag_formats(events, {}, client, fetch=page(), overrides={})
    assert events[0]["formats"] == ["Commander"] and client.calls == [] and cache == {}


def test_claude_answers_for_events_the_rules_leave_empty():
    events = [event()]
    client = FakeClaude(["Limited", "Modern"])
    cache = tag_formats(events, {}, client, fetch=page(), overrides={})
    assert events[0]["formats"] == ["Modern", "Limited"]
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"]["format"]["schema"]["properties"]["formats"]["items"]["enum"] == FORMATS
    assert "Some Event" in call["messages"][0]["content"] and "Regional Championship Qualifiers" in call["messages"][0]["content"]
    assert cache["x"]["formats"] == ["Modern", "Limited"]


def test_an_answer_outside_the_vocabulary_is_dropped():
    events = [event()]
    tag_formats(events, {}, FakeClaude(["Modern", "Oathbreaker"]), fetch=page(), overrides={})
    assert events[0]["formats"] == ["Modern"]


def test_overrides_win_over_rules_cache_and_claude():
    events = [event(id="a", name="CommandFest Marl", type="CommandFest"), event(id="b"), event(id="c")]
    client = FakeClaude(["Legacy"])
    cache = {"b": {"hash": "stale", "formats": ["Vintage"]}}
    tag_formats(events, cache, client, fetch=page(), overrides={"a": ["Brawl"], "b": ["Pauper", "Standard"], "c": []})
    assert [e["formats"] for e in events] == [["Brawl"], ["Standard", "Pauper"], []]
    assert client.calls == []


def test_overrides_file_is_read_and_checked(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text('{"a": ["Limited", "Modern", "Nonsense"]}')
    assert load_overrides(path) == {"a": ["Modern", "Limited"]}
    assert isinstance(load_overrides(), dict)


def test_the_cache_short_circuits_claude():
    client = FakeClaude(["Modern"])
    cache = tag_formats([event()], {}, client, fetch=page(), overrides={})
    assert len(client.calls) == 1
    again = [event()]
    kept = tag_formats(again, cache, client, fetch=page(), overrides={})
    assert len(client.calls) == 1 and again[0]["formats"] == ["Modern"] and kept == cache


def test_a_changed_article_is_asked_again():
    cache = tag_formats([event()], {}, FakeClaude(["Modern"]), fetch=page(), overrides={})
    events = [event()]
    tag_formats(events, cache, FakeClaude(["Pioneer"]), fetch=page("Now it is Pioneer."), overrides={})
    assert events[0]["formats"] == ["Pioneer"]


def test_the_cache_serves_a_run_without_a_key():
    cache = tag_formats([event()], {}, FakeClaude(["Modern"]), fetch=page(), overrides={})
    events = [event()]
    tag_formats(events, cache, None, fetch=page(), overrides={})
    assert events[0]["formats"] == ["Modern"]


def test_without_a_key_the_list_stays_empty_and_nothing_is_cached():
    events = [event()]
    assert tag_formats(events, {}, None, fetch=page(), overrides={}) == {}
    assert events[0]["formats"] == []


def test_a_page_that_cannot_be_read_keeps_the_saved_answer():
    def broken(url):
        raise OSError("down")

    cache = tag_formats([event()], {}, FakeClaude(["Modern"]), fetch=page(), overrides={})
    events = [event(), event(id="y")]
    client = FakeClaude(["Legacy"])
    kept = tag_formats(events, cache, client, fetch=broken, overrides={})
    assert [e["formats"] for e in events] == [["Modern"], []] and client.calls == [] and list(kept) == ["x"]


def test_a_failed_call_leaves_the_event_empty_and_uncached():
    events = [event()]
    cache = tag_formats(events, {}, FakeClaude(["Modern"], stop_reason="refusal"), fetch=page(), overrides={})
    assert events[0]["formats"] == [] and cache == {}


def test_only_magic_gg_pages_are_read():
    seen = []
    events = [event(id="a", url="https://www.axionnowevents.com/commandfest-uk"), event(id="b", url="https://magic.gg/schedule"),
              event(id="c", url="http://magic.gg/news/a"), event(id="d", url="https://www.magic.gg/news/b")]
    tag_formats(events, {}, FakeClaude(), fetch=lambda url: seen.append(url) or "text", overrides={})
    assert seen == ["https://www.magic.gg/news/b"]


def test_one_page_is_fetched_once_for_the_events_it_covers():
    seen = []
    client = FakeClaude()
    tag_formats([event(id="a"), event(id="b")], {}, client, fetch=lambda url: seen.append(url) or "text", overrides={})
    assert len(seen) == 1 and len(client.calls) == 2


def test_the_article_text_is_the_main_article():
    html = "<body><nav><p>Menu</p></nav><article><h1>Title</h1><p>Modern  qualifiers.</p><script>x()</script><ul><li>Item</li></ul></article><footer><p>Legal</p></footer></body>"
    assert article_text(html) == "Title\nModern qualifiers.\nItem"
