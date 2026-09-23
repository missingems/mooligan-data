# Published data format

Everything is static JSON at **`https://data.mooligan.com`**, rewritten by the scraper at 02:00 and 14:00 UTC. Dates are UTC, in the form `2026-09-21T00:00:00Z`. The files are served compressed when the client accepts gzip or Brotli, which `URLSession` and browsers do by default.

| Path | Holds | Cache-Control |
| --- | --- | --- |
| `index.json` | What each format's snapshot is, with its hash | `max-age=60` |
| `snapshots/{format}.json` | Meta, events and archetype results for one format | `max-age=300` |
| `decks/{deck_id}.json` | One decklist. Never changes once published | `max-age=31536000, immutable` |
| `cards/{slug}.json` | Where one card is played, across every format | `max-age=300` |
| `cards/index.json` | Every card played, with the formats it appears in | `max-age=300` |
| `state/*.json` | The scraper's own bookkeeping: stored deck ids, duplicate events, deleted decks, EDHREC check times. Apps can ignore them | `no-cache` |

Formats are `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful` and `duel_commander`. MTGGoldfish's Arena formats (Historic, Alchemy, Explorer, Timeless) are not published: it has almost no tournament data for them. `schema` is `1`, and it will change only if a field is removed or its meaning changes. Adding fields doesn't bump it, so decoders should ignore unknown keys.

## Suggested app flow

1. Fetch `index.json`, which is a few hundred bytes.
2. For each format the app shows, compare `formats[format].sha256` with the hash of the snapshot you have cached. Download `snapshots/{format}.json` only when the hash differs.
3. Fetch `decks/{deck_id}.json` when the user opens a deck, and cache it for good.
4. For "where is this card played", fetch `cards/{slug}.json`, where the slug is the card's name lower-cased with every run of non-alphanumeric characters replaced by `-` ("Fable of the Mirror-Breaker" becomes `fable-of-the-mirror-breaker`). A 404 means the card isn't played in any tracked format.
5. Look up cards on Scryfall by `card_name` (`https://api.scryfall.com/cards/named?exact=…`), keeping to Scryfall's guidelines: a User-Agent header, at most about 10 requests a second, and caching.

A deck or event a snapshot mentions may not be published yet. The scraper downloads up to 1,500 new decklists per format a run, newest first, so the app should handle a 404 from `decks/…` as "not available yet".

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

- **`meta`** is keyed by window: `30d`, `14d` and `7d`. A format whose page has no window selector (Duel Commander) publishes `30d` only. Archetypes are in MTGGoldfish's order, most played first. `deck_count` can be null, and `deck_id` (the archetype's featured list) is null when it couldn't be read.
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
  "archetype_id": "modern-eldrazi-ramp",
  "last_updated": "2026-09-22T14:40:12Z",
  "mainboard": [{ "quantity": 4, "card_name": "Ancient Stirrings" }],
  "sideboard": [{ "quantity": 2, "card_name": "Nature's Claim" }]
}
```

`event_id` is null for an archetype's featured list. `archetype_id` points at the entry in the snapshot's `archetypes`, so a deck screen can link to everything else that archetype did. It is null for decks stored before 23 September 2026, and for decks outside a tracked archetype; those can still be found by searching the snapshot's `archetypes` for the `deck_id`. `card_name` is exactly as MTGGoldfish writes it. For a double-faced card that's the front face ("Fable of the Mirror-Breaker"), which Scryfall's `exact` lookup accepts.

## `cards/{slug}.json`

```json
{
  "schema": 1,
  "slug": "lightning-bolt",
  "card_name": "Lightning Bolt",
  "generated_at": "2026-09-23T02:00:11Z",
  "formats": {
    "modern": {
      "decks": 412,
      "of_decks": 1638,
      "archetypes": [
        {
          "archetype_id": "modern-izzet-prowess",
          "name": "Izzet Prowess",
          "decks": 118,
          "avg_copies": 3.9,
          "deck_ids": ["7966110", "7966099"]
        }
      ]
    }
  }
}
```

Counted over the decklists stored for the last 30 days, so it follows the same window as the snapshots.

A card also carries an `edh` section when EDHREC has Commander data for it:

```json
"edh": {
  "decks": 562775,
  "of_decks": 5011429,
  "salt": 0.18,
  "url": "https://edhrec.com/cards/lightning-bolt",
  "commanders": [
    { "name": "Vivi Ornitier", "slug": "vivi-ornitier", "decks": 23169, "of_decks": 40779 }
  ]
}
```

`decks` of `of_decks` is how many Commander decks that could play the card do play it; each commander row is the same for that commander's decks. `salt` is EDHREC's salt score, and is null when they have none. At most 12 commanders, most decks first. **This data is EDHREC's, used with their permission: show it with attribution and link back to `url`.** Each run refreshes a slice of the cards (800 by default), oldest check first, so a card's Commander numbers can be a few days old.

- **`decks`** is how many decks of that format play the card; **`of_decks`** is how many decks the format has in the window. Their ratio is the card's play rate.
- **`archetypes`** is most-played first, at most 12 per format. `archetype_id` is null for decks outside a tracked archetype, whose `name` is then "Other". `avg_copies` counts mainboard and sideboard together, so a card in both boards is one deck with the copies added up.
- **`deck_ids`** links up to 5 decks, newest first, that an app can open directly.
- A card is missing from `cards/` when no stored deck plays it. Stored decklists lag a little behind the newest events, so a brand-new card can take a run or two to appear.

## `cards/index.json`

```json
{ "schema": 1, "generated_at": "…", "cards": { "lightning-bolt": { "name": "Lightning Bolt", "formats": ["legacy", "modern"] } } }
```

Each entry also carries `"edh": true` when that card has Commander data. Useful for showing "played in Modern and Legacy" without fetching each card page, and for knowing whether a card page exists at all.
