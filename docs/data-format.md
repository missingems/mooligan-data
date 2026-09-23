# Published data format

Everything is static JSON at **`https://data.mooligan.com`**, rewritten by the scraper at 02:00 and 14:00 UTC. Dates are UTC, in the form `2026-09-21T00:00:00Z`. The files are served compressed when the client accepts gzip or Brotli, which `URLSession` and browsers do by default.

| Path | Holds | Cache-Control |
| --- | --- | --- |
| `index.json` | What each format's snapshot is, with its hash | `max-age=60` |
| `snapshots/{format}.json` | Meta, events and archetype results for one format | `max-age=300` |
| `decks/{deck_id}.json` | One decklist. Never changes once published | `max-age=31536000, immutable` |
| `cards/{slug}.json` | Where one card is played, across every format | `max-age=300` |
| `cards/index.json` | Every card played, with the formats it appears in | `max-age=300` |
| `edh/commanders/{slug}.json` | One commander: what its decks play, and its average decklist | `max-age=300` |
| `edh/commanders/index.json` | Every commander published, with its deck count | `max-age=300` |
| `locator/{place}.json` | Upcoming in-store events near one place, from Wizards' locator | `max-age=300` |
| `locator/index.json` | The places published, with their coordinates | `max-age=300` |
| `premier/schedule.json` | Premier play: Pro Tours, Regional Championships, Spotlight Series, Worlds, CommandFests | `max-age=300` |
| `state/*.json` | The scraper's own bookkeeping: stored deck ids, duplicate and empty events, deleted decks, EDHREC check times. Apps can ignore them | `no-cache` |

Formats are `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful` and `duel_commander`. MTGGoldfish's Arena formats (Historic, Alchemy, Explorer, Timeless) are not published: it has almost no tournament data for them. `schema` is `1`, and it will change only if a field is removed or its meaning changes. Adding fields doesn't bump it, so decoders should ignore unknown keys.

## Suggested app flow

1. Fetch `index.json`, which is a few hundred bytes.
2. For each format the app shows, compare `formats[format].sha256` with the hash of the snapshot you have cached. Download `snapshots/{format}.json` only when the hash differs.
3. Fetch `decks/{deck_id}.json` when the user opens a deck, and cache it for good.
4. For "where is this card played", fetch `cards/{slug}.json`. Build the slug from the card's Scryfall name: take the part before any `//`, lower-case it, and replace every run of non-alphanumeric characters with `-`. "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki" becomes `fable-of-the-mirror-breaker`. The slugs come from the same Scryfall names your app already has, so this matches without a lookup table, and each page repeats its `oracle_id` so you can check you have the right card. A 404 means no tournament deck plays it and EDHREC has nothing for it yet.
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
      "kind": "mtgo_challenge",
      "source": "mtgo.com",
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
- **`events`** is newest first and covers every event MTGGoldfish lists for the format in the last 30 days: it is read from their tournament search, not just the "latest 10". Each has a **`kind`**, worked out from its name: `pro_tour` (also Worlds), `regional_championship`, `rcq` (RCQs and any other qualifier), `store_championship`, `mtgo_challenge` (Challenges, Showcases, prelims), `mtgo_league`, or `other` for local and unnamed events. **`source`** is the site the results came from, usually `mtgo.com` or `melee.gg`, or null. MTGGoldfish sometimes imports a Challenge twice, and names the copy "… (1)". A copy with the same standings as another event is left out, here and in `archetypes`. A result's `finish` is a placing such as `"1st Place"` for Challenges, or a record such as `"5-0"` for Leagues. `archetype_id` is null when the deck isn't in a tracked archetype's list; `archetype` is then the pilot's own deck title.
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
  "mainboard": [{ "quantity": 4, "card_name": "Ancient Stirrings", "oracle_id": "0f9c3b6b-…" }],
  "sideboard": [{ "quantity": 2, "card_name": "Nature's Claim", "oracle_id": "…" }]
}
```

Each entry's `oracle_id` is Scryfall's, matched from the name; it is null on decks published before 2026-09-23 and for names the catalog doesn't know, and `cards/index.json` (which carries `oracle_id` per card) resolves those by slug. `event_id` is null for an archetype's featured list. `archetype_id` points at the entry in the snapshot's `archetypes`, so a deck screen can link to everything else that archetype did. It is null for decks stored before 23 September 2026, and for decks outside a tracked archetype; those can still be found by searching the snapshot's `archetypes` for the `deck_id`. `card_name` is exactly as MTGGoldfish writes it. For a double-faced card that's the front face ("Fable of the Mirror-Breaker"), which Scryfall's `exact` lookup accepts.

## `cards/{slug}.json`

```json
{
  "schema": 1,
  "slug": "lightning-bolt",
  "card_name": "Lightning Bolt",
  "oracle_id": "4457ed35-7c10-48c8-9776-456485fdf070",
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

`decks` of `of_decks` is how many Commander decks that could play the card do play it; each commander row is the same for that commander's decks. `salt` is EDHREC's salt score, and is null when they have none. At most 12 commanders, most decks first. **This data is EDHREC's, used with their permission: show it with attribution and link back to `url`.** Each run refreshes a slice of the cards (800 by default), longest unchecked first, working through every card Magic has (~35,000 from Scryfall's bulk file). One card comes round about every three weeks, so its Commander numbers can be that old, and a card may have no `edh` section until its first turn.

- **`decks`** is how many decks of that format play the card; **`of_decks`** is how many decks the format has in the window. Their ratio is the card's play rate.
- **`archetypes`** is most-played first, at most 12 per format. `archetype_id` is null for decks outside a tracked archetype, whose `name` is then "Other". `avg_copies` counts mainboard and sideboard together, so a card in both boards is one deck with the copies added up.
- **`deck_ids`** links up to 5 decks, newest first, that an app can open directly.
- **`oracle_id`** is Scryfall's oracle id for the card, or null for the few cards the catalog doesn't cover.
- `formats` is empty for a card that only has Commander data. A card is missing from `cards/` when no stored deck plays it and EDHREC has nothing for it. Stored decklists lag a little behind the newest events, so a brand-new card can take a run or two to appear.

## `cards/index.json`

```json
{ "schema": 1, "generated_at": "…", "cards": { "lightning-bolt": { "name": "Lightning Bolt", "formats": ["legacy", "modern"] } } }
```

Each entry also carries `"edh": true` when that card has Commander data. Useful for showing "played in Modern and Legacy" without fetching each card page, and for knowing whether a card page exists at all.

## `edh/commanders/{slug}.json`

The `slug` is the one on each card page's `edh.commanders[].slug`, so a card leads to the commanders playing it, and each of those to what that commander's decks play.

```json
{
  "schema": 1,
  "slug": "vivi-ornitier",
  "name": "Vivi Ornitier",
  "decks": 40779,
  "salt": 2.81,
  "url": "https://edhrec.com/commanders/vivi-ornitier",
  "generated_at": "2026-09-23T02:00:11Z",
  "sections": [
    {
      "tag": "topcards",
      "header": "Top Cards",
      "cards": [{ "name": "Brainstorm", "decks": 28385, "of_decks": 40779, "synergy": 0.28 }]
    }
  ],
  "average_deck": [{ "header": "Lands", "cards": ["Island"] }]
}
```

- **`sections`** are EDHREC's own groupings: `topcards`, `highsynergycards`, `gamechangers`, then by card type. A card's `decks` of `of_decks` is how many of this commander's decks play it, and `synergy` is EDHREC's synergy score (0.28 means 28 percentage points more than other decks of the same colours would play it).
- **`average_deck`** is the typical list EDHREC builds for the commander, by card type. Names only, since it is one copy of each apart from basics.
- Card names here match the `cards/{slug}.json` slug rule, so an app can link straight from a commander's list to a card page.
- Each run refreshes 150 commanders, longest unchecked first, so a commander may be missing until its first turn. **This is EDHREC's data, used with their permission: credit them and link back to `url`.**

## `locator/{place}.json`

Upcoming Magic events near a configured place, read twice a day from Wizards' Store & Event Locator. Places are set in the workflow (`LOCATOR_PLACES`); `locator/index.json` lists them. Events are the next `days_ahead` days within `distance_miles`, soonest first.

```json
{
  "schema": 1,
  "place": "Singapore",
  "slug": "singapore",
  "distance_miles": 15,
  "days_ahead": 14,
  "generated_at": "2026-09-23T14:00:11Z",
  "url": "https://locator.wizards.com/search?query=Singapore&searchType=magic-events&distance=15",
  "events": [
    {
      "id": "11505843",
      "title": "Unsleeved Morning Commander Party",
      "format": "Commander",
      "start": "2026-09-23T03:00:00Z",
      "time_zone": "Asia/Singapore",
      "rules_level": "CASUAL",
      "has_top8": false,
      "entry_fee": { "amount": 0, "currency": "USD" },
      "capacity": 32,
      "tags": ["commander"],
      "is_online": false,
      "latitude": 1.3045,
      "longitude": 103.8597,
      "store": { "id": "19413", "name": "Unsleeved by Lazy Potato", "address": "17A Jalan Klapa, Singapore, 199329", "website": "https://treasuresbylazypotato.com", "phone": "+65…", "premium": false, "url": "https://locator.wizards.com/store/19413" }
    }
  ]
}
```

`locator/index.json` gives each place its `latitude` and `longitude` (the median of its events). To choose a place from the device's location, pick the nearest one; if none is within, say, 60 miles, deep-link to the locator with the user's own area instead.

`start` is UTC; show it in `time_zone`. `rules_level` is `CASUAL`, `REGULAR`, `COMPETITIVE` or `PROFESSIONAL`, which is the locator's own casual-to-premier scale. `format` is the locator's name (Commander, Sealed Deck, Standard, Booster Draft, …) and can be null. `entry_fee.amount` of 0 means free, and the currency is whatever the store entered. For any place not published, deep-link to `url` with the user's own query instead.

## `premier/schedule.json`

Wizards' premier play calendar, read from magic.gg's schedule page each run: every event from a week ago to twelve months ahead, soonest first.

```json
{
  "schema": 1,
  "generated_at": "2026-09-23T14:00:11Z",
  "source": "https://magic.gg/schedule",
  "regions": ["australia_nz", "canada", "china", "chinese_taipei", "europe", "japan", "korea", "mexico_central_america", "south_america", "southeast_asia", "usa"],
  "events": [
    {
      "id": "18n7YfJ329iwE09esF7DHx",
      "name": "SEA Championship Final: Singapore",
      "type": "Championships",
      "start": "2026-10-16",
      "end": "2026-10-18",
      "start_time": "2026-10-16T10:00+08:00",
      "end_time": "2026-10-18T18:00+08:00",
      "place": "Singapore",
      "region": "southeast_asia",
      "game_type": "Tabletop",
      "url": "https://magic.gg/news/play-update-2026-27-round-2-regional-championship-promos-and-qualifiers"
    }
  ]
}
```

- **`type`** is magic.gg's own: `Pro Tour`, `World Championships`, `Championships` (the Regional Championships and their regional finals), `Magic Spotlight Series`, `CommandFest`, `Convention`, `Prereleases`.
- **`place`** is the city from the event's name when it has one; **`region`** is the Regional Championship region matched from the name, or null for global events such as the Pro Tour and Worlds. An app should show its user the events for their region (from the device's country) plus every event with a null region.
- **`url`** is where magic.gg sends readers, usually an announcement article or the organiser's site.

Regional Championship Qualifiers (RCQs) are store events and are not in this calendar: they appear in `locator/{place}.json` with `rules_level` of `COMPETITIVE`, and in the tournament feed's `events` with `kind` of `rcq` once results are posted.
