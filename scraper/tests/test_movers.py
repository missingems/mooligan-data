import uuid
from datetime import date, datetime, timezone

import pytest

from mtgmeta.movers import KEPT_DAYS, LIMIT, NO_PRICE, build_movers, printings, read_history

NOW = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)
LAST = (date(2026, 9, 30) - date(1970, 1, 1)).days
FIRST = LAST - 89


def varint(value):
    out = bytearray()
    while value >= 0x80:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def zigzag(value):
    return varint(value << 1 if value >= 0 else (-value << 1) - 1)


def encode(cards, first=FIRST, last=LAST):
    """history.bin as prices.swift writes it: `cards` is [(scryfall id, [normal, foil, etched] points, latest)]."""
    out = bytearray(b"MTGH") + bytes([1]) + first.to_bytes(4, "little") + last.to_bytes(4, "little") + len(cards).to_bytes(4, "little")
    for printing, history, latest in cards:
        out += uuid.UUID(printing).bytes
        out.append(sum(1 << i for i, series in enumerate(history) if series))
        out.append(sum(1 << i for i, point in enumerate(latest) if point))
        for series in history:
            if not series:
                continue
            out += varint(len(series))
            day, cents = first, 0
            for point_day, point_cents in series:
                out += varint(point_day - day) + zigzag(point_cents - cents)
                day, cents = point_day, point_cents
        for point in latest:
            if point:
                out += varint(last - point[0]) + varint(point[1])
    return bytes(out)


def daily(*prices, until=LAST):
    """A price on each of the last len(prices) days, oldest first; None skips a day."""
    start = until - len(prices) + 1
    return [(start + i, cents) for i, cents in enumerate(prices) if cents is not None]


def pid(n):
    return str(uuid.UUID(int=n))


def test_the_regular_finish_of_the_last_month_is_read_and_the_rest_is_skipped_over():
    data = encode(
        [
            (pid(1), [daily(*range(100, 190)), daily(999, 999), []], [(LAST, 5), None, None, (LAST - 2, 3), None, None]),
            (pid(2), [daily(300, 310), [], daily(7)], [None] * 6),
        ]
    )
    history = read_history(data)
    assert history.last_day == date(2026, 9, 30)
    assert list(history.prices[pid(1)]) == list(range(190 - KEPT_DAYS, 190))
    assert list(history.prices[pid(2)])[-3:] == [NO_PRICE, 300, 310]
    assert set(read_history(data, wanted={pid(2)}).prices) == {pid(2)}


def test_a_price_holds_over_a_few_skipped_days_and_then_runs_out():
    series = [(LAST - 20, 400), (LAST - 16, 500), (LAST - 10, 600)]
    prices = list(read_history(encode([(pid(1), [series, [], []], [None] * 6)])).prices[pid(1)])
    assert prices[-21:-15] == [400, 400, 400, 400, 500, 500]  # three days held, then the next point
    assert prices[-11:] == [600, 600, 600, 600] + [NO_PRICE] * 7


def card(name, *ids, legal=("modern", "legacy")):
    return {"name": name, "slug": name.lower().replace(" ", "-"), "legal": set(legal), "printings": {i: "set" + i[-1] for i in ids}}


def movers(cards, prices):
    history = read_history(encode([(printing, [series, [], []], [None] * 6) for printing, series in prices.items()]))
    return build_movers(history, cards, NOW)


def names(file, window, side):
    return [row["name"] for row in file["windows"][window][side]]


def test_a_card_costs_its_cheapest_printing_among_those_priced_at_both_ends():
    cards = {"o1": card("Ragavan", pid(1), pid(2))}
    # The old printing climbs; a reprint arrives a week ago, cheaper. It was not priced a week or a month ago, so it is no move then.
    prices = {pid(1): daily(*[1000] * 24 + [1500] * 7), pid(2): daily(*[800] * 7)}
    file = movers(cards, prices)["all"]
    for window in ("7d", "30d"):
        assert names(file, window, "losers") == []
        [row] = file["windows"][window]["gainers"]
        assert (row["name"], row["price"], row["previous"], row["change"], row["percent"]) == ("Ragavan", 15.0, 10.0, 5.0, 50.0)
        assert row["scryfall_id"] == pid(1) and row["set"] == "set1" and row["slug"] == "ragavan"
        assert len(row["history"]) == 30 and row["history"][-1] == 15.0
    # Yesterday both were priced and the reprint was the cheaper, at 8 both days.
    assert file["windows"]["1d"] == {"gainers": [], "losers": []}


def test_a_card_whose_cheapest_printing_switches_between_days_moves_by_the_cheapest_of_each_day():
    cards = {"o1": card("Ragavan", pid(1), pid(2))}
    file = movers(cards, {pid(1): daily(1000, 1200), pid(2): daily(1100, 900)})["all"]
    [row] = file["windows"]["1d"]["losers"]
    assert (row["price"], row["previous"], row["percent"], row["scryfall_id"], row["set"]) == (9.0, 10.0, -10.0, pid(2), "set2")
    assert row["history"][-2:] == [10.0, 9.0]
    assert file["windows"]["1d"]["gainers"] == []


def test_a_printing_priced_for_the_first_time_does_not_move_the_card():
    cards = {"o1": card("Fatespinner", pid(1), pid(2))}
    file = movers(cards, {pid(1): daily(1045, 1045, 1045), pid(2): daily(None, None, 95)})["all"]
    assert names(file, "1d", "losers") == [] and names(file, "7d", "losers") == []
    # Priced on both days, it is the card's price on both, and the card did not move.
    file = movers(cards, {pid(1): daily(1045, 1045, 1045), pid(2): daily(None, 95, 95)})["all"]
    assert names(file, "1d", "losers") == []


def test_a_foil_only_printing_is_not_a_printing_of_the_card():
    cards = printings(
        [
            scryfall("Fatespinner", pid(1), set="mrd"),
            scryfall("Fatespinner", pid(2), set="plst", finishes=["foil"]),
            scryfall("Foil Only Promo", pid(3), oracle="o2", finishes=["foil"]),
            scryfall("Both Finishes", pid(4), oracle="o3", finishes=["nonfoil", "foil"]),
        ]
    )
    assert cards["o1"]["printings"] == {pid(1): "mrd"}
    assert set(cards) == {"o1", "o3"}
    # The foil-only printing gets a 95 cent regular price: the card does not fall from 10.45 to 0.95.
    file = movers(cards, {pid(1): daily(1045, 1045), pid(2): daily(None, 95)})["all"]
    assert names(file, "1d", "losers") == [] and names(file, "7d", "losers") == []


def test_gainers_and_losers_rank_by_percent_and_bulk_prices_stay_out():
    cards = {f"o{n}": card(f"Card {n}", pid(n)) for n in range(1, 7)}
    prices = {
        pid(1): daily(200, 300),  # +50%
        pid(2): daily(1000, 2000),  # +100%
        pid(3): daily(10, 90),  # bulk: under 50 cents before
        pid(4): daily(60, 80),  # under a dollar at both ends
        pid(5): daily(5000, 5010),  # moved by less than 25 cents
        pid(6): daily(4000, 3000),  # -25%
    }
    file = movers(cards, prices)["all"]
    assert names(file, "1d", "gainers") == ["Card 2", "Card 1"]
    assert names(file, "1d", "losers") == ["Card 6"]
    assert file["price_day"] == "2026-09-30" and file["generated_at"] == "2026-10-01T03:00:00Z"


def test_a_card_without_a_price_at_either_end_does_not_move():
    cards = {"o1": card("New", pid(1)), "o2": card("Gone", pid(2))}
    prices = {pid(1): daily(500, 900), pid(2): daily(500, 900, until=LAST - 5)}
    file = movers(cards, prices)["all"]
    assert names(file, "1d", "gainers") == ["New"]
    assert names(file, "7d", "gainers") == []  # nothing to compare with a week ago


def test_each_format_lists_only_cards_legal_there_and_all_lists_every_card():
    cards = {"o1": card("Modern Card", pid(1), legal=("modern",)), "o2": card("Unplayable", pid(2), legal=())}
    files = movers(cards, {pid(1): daily(500, 900), pid(2): daily(500, 1000)})
    assert set(files) == {"all", "modern", "standard", "pioneer", "legacy", "pauper", "vintage", "premodern", "penny_dreadful", "duel_commander"}
    assert names(files["all"], "1d", "gainers") == ["Unplayable", "Modern Card"]
    assert names(files["modern"], "1d", "gainers") == ["Modern Card"]
    assert names(files["legacy"], "1d", "gainers") == []


def test_a_list_holds_at_most_the_limit():
    cards = {f"o{n}": card(f"Card {n}", pid(n)) for n in range(1, LIMIT + 6)}
    file = movers(cards, {pid(n): daily(500, 500 + n * 10) for n in range(1, LIMIT + 6)})["all"]
    assert len(file["windows"]["1d"]["gainers"]) == LIMIT
    assert file["windows"]["1d"]["gainers"][0]["name"] == f"Card {LIMIT + 5}"


def scryfall(name, id, oracle="o1", **extra):
    return {"id": id, "oracle_id": oracle, "name": name, "games": ["paper", "mtgo"], "finishes": ["nonfoil", "foil"], "layout": "normal", "set": "abc", "set_type": "expansion",
            "legalities": {"modern": "legal", "vintage": "restricted", "legacy": "banned", "penny": "legal", "duel": "not_legal"}, **extra}


def test_only_paper_printings_of_real_cards_count_and_legal_means_legal_or_restricted():
    cards = printings(
        [
            scryfall("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", pid(1)),
            scryfall("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", pid(2), games=["mtgo"]),
            scryfall("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", pid(3), set_type="memorabilia"),
            scryfall("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", pid(4), oversized=True),
            scryfall("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", pid(5), set="xyz"),
            scryfall("Goblin", pid(6), oracle="o2", layout="token"),
            {"id": pid(7), "name": "Delver of Secrets // Insectile Aberration", "games": ["paper"], "finishes": ["nonfoil"], "layout": "transform",
             "card_faces": [{"oracle_id": "o3"}], "legalities": {}},
        ]
    )
    assert set(cards) == {"o1", "o3"}
    assert cards["o1"]["printings"] == {pid(1): "abc", pid(5): "xyz"}
    assert cards["o1"]["slug"] == "fable-of-the-mirror-breaker"
    assert cards["o1"]["legal"] == {"modern", "vintage", "penny_dreadful"}
    assert cards["o3"]["printings"] == {pid(7): ""}


def test_a_file_that_is_not_a_price_history_is_refused():
    with pytest.raises(ValueError):
        read_history(b"MTGD\x01" + bytes(12))
