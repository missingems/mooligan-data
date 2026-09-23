from datetime import datetime, timezone

from mtgmeta.locator import Locator, decode_turbo_stream, place_page

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def test_turbo_stream_expands_index_references():
    # {"a": {"b": [1, "x"]}, "u": <url>, "n": null}: values are indexes into the flat array.
    raw = [{"_1": 2, "_5": 6, "_7": -5}, "a", {"_3": 4}, "b", [8, 9], "u", ["U", "https://x"], "n", 1, "x"]
    assert decode_turbo_stream(raw) == {"a": {"b": [1, "x"]}, "u": "https://x", "n": None}


def stream(events, total):
    """A search.data payload holding `events`, as the locator's search route encodes it."""
    raw = [
        {"_1": 2},
        "routes/($lang).search",
        {"_3": 4},
        "data",
        {"_5": 6},
        "events",
        {"_7": 8},
        "advancedSearchEvents",
        {"_9": 10, "_11": 12},
        "events",
        [],
        "pageInfo",
        {"_13": 14},
        "totalResults",
        total,
    ]

    def add(value):
        raw.append(value)
        return len(raw) - 1

    def encode(value):
        if isinstance(value, dict):
            return add({f"_{add(key)}": encode(inner) for key, inner in value.items()})
        if isinstance(value, list):
            return add([encode(inner) for inner in value])
        return add(value)

    raw[10] = [encode(event) for event in events]
    return raw


EVENT = {
    "id": 11505843,
    "title": "Unsleeved Morning Commander Party",
    "eventFormat": {"id": "f", "name": "Commander"},
    "scheduledStartTime": "2026-09-23T03:00:00.0000000Z",
    "timeZone": "Asia/Singapore",
    "entryFee": {"amount": 0, "currency": "USD"},
    "capacity": 32,
    "rulesEnforcementLevel": "CASUAL",
    "hasTop8": False,
    "tags": ["magic:_the_gathering", "commander"],
    "isOnline": False,
    "latitude": 1.3045,
    "longitude": 103.8597,
    "organization": {"id": 19413, "name": "Unsleeved by Lazy Potato", "address": "17A Jalan Klapa", "city": "Singapore", "postalCode": "199329", "website": "https://treasuresbylazypotato.com", "isPremium": False},
}


def test_events_are_normalised_and_stop_at_the_horizon(monkeypatch):
    later = {**EVENT, "id": 2, "title": "Next month", "scheduledStartTime": "2026-10-20T03:00:00.0000000Z"}
    pages = {1: stream([EVENT, later], 2)}
    locator = Locator("test", delay=0)
    monkeypatch.setattr(locator, "_page", lambda query, distance, page: pages.get(page))

    events = locator.events("Singapore", 15, days_ahead=7, now=NOW)

    assert [event["title"] for event in events] == ["Unsleeved Morning Commander Party"]
    event = events[0]
    assert (event["format"], event["start"], event["rules_level"]) == ("Commander", "2026-09-23T03:00:00Z", "CASUAL")
    assert event["tags"] == ["commander"] and event["entry_fee"] == {"amount": 0, "currency": "USD"}
    assert event["store"]["address"] == "17A Jalan Klapa, Singapore, 199329"
    assert event["store"]["url"] == "https://locator.wizards.com/store/19413"


def test_a_place_page_links_back_to_the_locator():
    page = place_page("Kuala Lumpur", 20, 14, [], "2026-09-23T00:00:00Z")
    assert page["slug"] == "kuala-lumpur"
    assert page["url"] == "https://locator.wizards.com/search?query=Kuala+Lumpur&searchType=magic-events&distance=20"
