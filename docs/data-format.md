# Published data format

Everything is static JSON at **`https://data.mooligan.com`**, rewritten by the scraper at 02:00 and 14:00 UTC. Dates are UTC, in the form `2026-09-21T00:00:00Z`. The files are served compressed when the client accepts gzip or Brotli, which `URLSession` and browsers do by default.

| Path | Holds | Cache-Control |
| --- | --- | --- |
| `index.json` | What each format's snapshot is, with its hash | `max-age=60` |
| `snapshots/{format}.json` | Meta, events and archetype results for one format | `max-age=300` |
| `decks/{deck_id}.json` | One decklist. Never changes once published | `max-age=31536000, immutable` |
| `state/*.json` | The scraper's own bookkeeping: stored deck ids, and duplicate events. Apps can ignore them | `no-cache` |

Formats are `modern`, `standard` and `pioneer`. `schema` is `1`, and it will change only if a field is removed or its meaning changes. Adding fields doesn't bump it, so decoders should ignore unknown keys.

## Suggested app flow

1. Fetch `index.json`, which is a few hundred bytes.
2. For each format the app shows, compare `formats[format].sha256` with the hash of the snapshot you have cached. Download `snapshots/{format}.json` only when the hash differs.
3. Fetch `decks/{deck_id}.json` when the user opens a deck, and cache it for good.
4. Look up cards on Scryfall by `card_name` (`https://api.scryfall.com/cards/named?exact=…`), keeping to Scryfall's guidelines: a User-Agent header, at most about 10 requests a second, and caching.

A deck or event a snapshot mentions may not be published yet. The scraper downloads up to 400 new decklists a run, newest first, so the app should handle a 404 from `decks/…` as "not available yet".

## `index.json`

```json
{
  "schema": 1,
  "generated_at": "2026-09-22T14:40:12Z",
  "formats": {
    "modern": {
      "path": "snapshots/modern.json",
      "sha256": "9c1f…",
      "bytes": 2481734,
      "generated_at": "2026-09-22T14:40:12Z",
      "events": 212,
      "archetypes": 60
    }
  }
}
```

A format is missing from `formats` until its first scrape completes.

## `snapshots/{format}.json`

```json
{
  "schema": 1,
  "format": "modern",
  "generated_at": "2026-09-22T14:40:12Z",
  "meta": {
    "30d": {
      "timeframe": "30d",
      "last_updated": "2026-09-22T14:40:12Z",
      "archetypes": [
        { "name": "Izzet Prowess", "id": "modern-izzet-prowess", "percentage": 9.8, "deck_count": 675, "deck_id": "7945486" }
      ]
    }
  },
  "events": [
    {
      "event_id": "66753",
      "event_name": "Modern Challenge 32 2026-09-21",
      "date": "2026-09-21T00:00:00Z",
      "url": "https://www.mtggoldfish.com/tournament/66753",
      "last_updated": "2026-09-22T14:40:12Z",
      "results": [
        { "finish": "1st Place", "player": "ashame", "archetype": "Eldrazi Ramp", "archetype_id": "modern-eldrazi-ramp", "deck_id": "7966104" }
      ]
    }
  ],
  "archetypes": {
    "modern-izzet-prowess": {
      "archetype_id": "modern-izzet-prowess",
      "name": "Izzet Prowess",
      "deck_id": "7945486",
      "featured_player": "Roy Varney",
      "last_updated": "2026-09-22T14:40:12Z",
      "results": [
        { "deck_id": "7966110", "date": "2026-09-21T00:00:00Z", "player": "Xsper", "event_id": "66753", "event_name": "Modern Challenge 32 2026-09-21", "finish": "13th Place" }
      ]
    }
  }
}
```

- **`meta`** is keyed by window. Only `30d` is published today. Archetypes are in MTGGoldfish's order, most played first. `deck_count` can be null, and `deck_id` (the archetype's featured list) is null when it couldn't be read.
- **`events`** is newest first and covers the last 30 days. MTGGoldfish sometimes imports a Challenge twice, and names the copy "… (1)". A copy with the same standings as another event is left out, here and in `archetypes`. A result's `finish` is a placing such as `"1st Place"` for Challenges, or a record such as `"5-0"` for Leagues. `archetype_id` is null when the deck isn't in a tracked archetype's list; `archetype` is then the pilot's own deck title.
- **`archetypes`** is keyed by archetype id. `results` holds every deck of that archetype in the last 30 days, newest first. To group by event, group on `event_id`, which is null for the rare result without one; `event_name` is always set.

## `decks/{deck_id}.json`

```json
{
  "deck_id": "7966104",
  "player": "ashame",
  "archetype": "Eldrazi Ramp",
  "format": "modern",
  "event_id": "66753",
  "last_updated": "2026-09-22T14:40:12Z",
  "mainboard": [{ "quantity": 4, "card_name": "Ancient Stirrings" }],
  "sideboard": [{ "quantity": 2, "card_name": "Nature's Claim" }]
}
```

`event_id` is null for an archetype's featured list. `card_name` is exactly as MTGGoldfish writes it. For a double-faced card that's the front face ("Fable of the Mirror-Breaker"), which Scryfall's `exact` lookup accepts.
