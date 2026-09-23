from datetime import datetime, timezone

from mtgmeta.premier import calendar_from_html, premier_events, region_of

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
