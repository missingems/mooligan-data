# Published data format

Everything is static JSON at **`https://data.mooligan.com`**, rewritten by the scraper once a day at 14:00 UTC. Dates are UTC, in the form `2026-09-21T00:00:00Z`. The files are served compressed when the client accepts gzip or Brotli, which `URLSession` and browsers do by default.

| Path | Holds | Cache-Control |
| --- | --- | --- |
| `index.json` | What each format's snapshot is, with its hash | `max-age=60` |
| `explore.json` | A small summary of the six main formats, for a landing screen: top archetypes and the latest events | `max-age=300` |
| `snapshots/{format}.json` | Meta, events and archetype results for one format | `max-age=300` |
| `archetypes/{archetype_id}.json` | One archetype in a format's current metagame: its shares and its recent decks | `max-age=300` |
| `events/{event_id}.json` | One event of the last 30 days: its whole standings | `max-age=300` |
| `decks/{deck_id}.json` | One decklist. Never changes once published | `max-age=31536000, immutable` |
| `cards/{slug}.json` | Where one card is played, across every format | `max-age=300` |
| `cards/index.json` | Every card played, with the formats it appears in | `max-age=300` |
| `popular-cards/{format}.json` | The cards one format's recent decks play most, in each of three windows, by kind of card and for the sideboard | `max-age=300` |
| `breakouts/{format}.json` | The cards new to one format's metagame: played in the last 7 days and barely before, with how those decks did | `max-age=300` |
| `movers/{format}.json` | The cards whose price rose or fell most over the last day, week and month, among those legal in a format (`movers/all.json`: every card) | `max-age=300` |
| `edh/commanders/{slug}.json` | One commander: what its decks play, and its average decklist | `max-age=300` |
| `edh/commanders/index.json` | Every commander published, with its deck count | `max-age=300` |
| `locator/{place}.json` | Upcoming in-store events near one place, from Wizards' locator | `max-age=300` |
| `locator/index.json` | The places published, with their coordinates | `max-age=300` |
| `premier/schedule.json` | Premier play: Pro Tours, Regional Championships, Spotlight Series, Worlds, CommandFests | `max-age=300` |
| `catalog/…` | The card catalog: image feature prints, pull odds, price catalog. Layout in [`generators/README.md`](../generators/README.md) | `max-age=3600`; metas `max-age=300` |
| `state/*.json` | The scraper's own bookkeeping: stored deck ids, duplicate and empty events, deleted decks, EDHREC check times. Apps can ignore them | `no-cache` |

Formats are `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful` and `duel_commander`. MTGGoldfish's Arena formats (Historic, Alchemy, Explorer, Timeless) are not published: it has almost no tournament data for them. `schema` is `1`, and it will change only if a field is removed or its meaning changes. Adding fields doesn't bump it, so decoders should ignore unknown keys.

## Suggested app flow

0. For a landing screen (an Explore tab), fetch `explore.json` alone: it has each main format's top archetypes and latest events in a few tens of KB, so nothing else has to download first.
1. Fetch `index.json`, which is a few hundred bytes.
2. For each format the app shows, compare `formats[format].sha256` with the hash of the snapshot you have cached. Download `snapshots/{format}.json` only when the hash differs.
3. Fetch `decks/{deck_id}.json` when the user opens a deck, and cache it for good.
   To drill down from the Explore tab, follow a row to the file it names, then on to a deck:
   - **explore → archetype file → deck file.** A standings row's `id` is the file `archetypes/{id}.json`, which lists that archetype's recent decks; each deck row's `deck_id` is `decks/{deck_id}.json`.
   - **explore → event file → deck file.** A recent event's `id` is the file `events/{id}.json`, which lists its whole standings; each result's `deck_id` is `decks/{deck_id}.json`.

   An event row already shows the result that led it (`lead`: its archetype, player and two key cards) and the first three results (`top`), so it needs no download until it is opened. From an event file, a result with an `archetype_id` links on to `archetypes/{archetype_id}.json`; from an archetype file, a deck with an `event_id` links to `events/{event_id}.json`. Any of these can be a 404 (see below).
4. For "where is this card played", fetch `cards/{slug}.json`. Build the slug from the card's Scryfall name: take the part before any `/`, fold accents to ASCII (é → e), lower-case it, and replace every run of non-alphanumeric characters with `-`. "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki" becomes `fable-of-the-mirror-breaker`. The slugs come from the same Scryfall names your app already has, so this matches without a lookup table, and each page repeats its `oracle_id` so you can check you have the right card. A 404 means no tournament deck plays it and EDHREC has nothing for it yet.
5. Look up cards on Scryfall by `card_name` (`https://api.scryfall.com/cards/named?exact=…`), keeping to Scryfall's guidelines: a User-Agent header, at most about 10 requests a second, and caching.

A deck or event a snapshot mentions may not be published yet. The scraper downloads up to 1,500 new decklists per format a run, newest first, so the app should handle a 404 from `decks/…` as "not available yet". The archetype and event files say which decks to expect: each row's `published` is false for a deck whose file doesn't exist yet, so the app can grey the row out instead of asking. An `event_id` in an archetype's deck list can point at an event with no file (an event outside the last 30 days, or one dated ahead), which is a 404 as well.

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
        {
          "name": "Izzet Prowess", "id": "modern-izzet-prowess", "percentage": 9.8, "deck_count": 675, "deck_id": "7945486",
          "colors": ["U", "R"],
          "key_cards": [
            { "name": "Cori-Steel Cutter", "oracle_id": "a3f0…" },
            { "name": "Mishra's Bauble", "oracle_id": "…" },
            { "name": "Dragon's Rage Channeler", "oracle_id": "…" }
          ]
        }
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
        { "finish": "1st Place", "player": "ashame", "archetype": "Eldrazi Ramp", "archetype_id": "modern-eldrazi-ramp", "deck_id": "7966104", "colors": ["G"] }
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

- **`meta`** is keyed by window: `30d`, `14d` and `7d`. A format whose page has no window selector (Duel Commander) publishes `30d` only. Archetypes are in MTGGoldfish's order, most played first. `deck_count` can be null, and `deck_id` (the archetype's featured list) is null when it couldn't be read. Each archetype also has **`colors`**, the colours MTGGoldfish shows on its tile as letters (`W`, `U`, `B`, `R`, `G`) in that fixed order, `[]` for a colourless deck, and **`key_cards`**, the three cards its tile names, most representative first. A key card is `{ "name", "oracle_id" }`, with Scryfall's oracle id matched from the name, or null when the catalog doesn't know it (join on `oracle_id`, not the name). Both are `[]` when MTGGoldfish's tile doesn't show them, and are missing from snapshots published before 30 September 2026, so decode them as optional.
- **`events`** is newest first and covers every event MTGGoldfish lists for the format in the last 30 days: it is read from their tournament search, not just the "latest 10". Each has a **`kind`**, worked out from its name: `pro_tour` (also Worlds), `regional_championship`, `rcq` (RCQs and any other qualifier), `store_championship`, `mtgo_challenge` (Challenges, Showcases, prelims), `mtgo_league` (Magic Online Leagues: a league counts only when its `source` is `mtgo.com`, so a paper league imported from melee.gg is `other`), or `other` for local and unnamed events. Letters from another alphabet that look like a Latin one (a Cyrillic С in "Store Сhampionship") are read as the Latin letter. The `kind` is worked out again from the name and source on every run, so a fix to the rules corrects the events already stored (the `kind` of a League from melee.gg was `mtgo_league` until 1 October 2026). **`source`** is the site the results came from, usually `mtgo.com` or `melee.gg`, or null. MTGGoldfish sometimes imports a Challenge twice, and names the copy "… (1)". A copy with the same standings as another event is left out, here and in `archetypes`. A result's `finish` is a placing such as `"1st Place"` for Challenges, or a record such as `"5-0"` for Leagues. `archetype_id` is null when the deck isn't in a tracked archetype's list; `archetype` is then the pilot's own deck title. A result's **`colors`** are the pips MTGGoldfish shows beside the deck on the event's page, as `W`, `U`, `B`, `R`, `G` in that order. The key is there only for an event read since 1 October 2026 whose page showed some, and is absent otherwise (a colourless deck shows none, and an older event was not read for them), so decode it as optional: absent means unknown here, and `explore.json` and `events/{id}.json` fill it in (see below).
- **`archetypes`** is keyed by archetype id. `results` holds every deck of that archetype in the last 30 days, newest first. To group by event, group on `event_id`, which is null for the rare result without one; `event_name` is always set.

## `explore.json`

A summary of the six main formats for a landing screen, written with the snapshots each run (so it is never older than they are), about 35 KB gzipped (350 KB as JSON) with no decklists. Every number in it can also be worked out from `snapshots/{format}.json`; this is the same data cut down, so a tab can show it without downloading six snapshots of up to 2 MB each.

```json
{
  "generated_at": "2026-09-30T02:00:00Z",
  "formats": [
    {
      "format": "modern",
      "name": "Modern",
      "latest_event": {
        "id": "66929", "name": "Modern Challenge 32", "date": "2026-09-29", "kind": "mtgo_challenge", "prestige": 2, "source": "mtgo.com", "url": "https://www.mtggoldfish.com/tournament/66929", "deck_count": 32, "result_count": 32, "winner_archetype": "Boros Energy",
        "lead": { "finish": "1st Place", "archetype": "Boros Energy", "archetype_id": "modern-boros-energy", "player": "ashame", "deck_id": "7966104", "colors": ["R", "W"], "key_cards": [ { "name": "Ragavan, Nimble Pilferer", "oracle_id": "…" }, { "name": "Ocelot Pride", "oracle_id": "…" } ] },
        "top": [ "the lead again, then the 2nd and 3rd place results, each shaped like the lead" ]
      },
      "standings": [
        {
          "id": "modern-boros-energy", "name": "Boros Energy",
          "share_30d": 18.4, "share_7d": 19.1, "deck_count_30d": 120, "top8_30d": 77, "wins_30d": 11,
          "colors": ["R", "W"],
          "key_cards": [ { "name": "Ragavan, Nimble Pilferer", "oracle_id": "…" } ]
        }
      ],
      "standings_by_window": {
        "7d": [
          {
            "id": "modern-boros-energy", "name": "Boros Energy",
            "share": 19.1, "deck_count": 42, "top8": 15, "wins": 3, "trend": "up",
            "colors": ["R", "W"],
            "key_cards": [ { "name": "Ragavan, Nimble Pilferer", "oracle_id": "…" } ]
          }
        ],
        "14d": [ "…" ],
        "30d": [ "…" ]
      },
      "color_shares": {
        "7d": { "W": 13.8, "U": 19.4, "B": 7.9, "R": 20.6, "G": 21.9, "C": 16.4 },
        "14d": { "…": "…" },
        "30d": { "W": 14.4, "U": 22.6, "B": 10.8, "R": 21.7, "G": 19.6, "C": 10.9 }
      },
      "recent_events": [
        {
          "id": "66929", "name": "Modern Challenge 32", "date": "2026-09-29", "kind": "mtgo_challenge", "prestige": 2, "source": "mtgo.com", "url": "https://www.mtggoldfish.com/tournament/66929", "deck_count": 32, "result_count": 32, "winner_archetype": "Boros Energy", "winner_player": "ashame",
          "lead": { "finish": "1st Place", "archetype": "Boros Energy", "archetype_id": "modern-boros-energy", "player": "ashame", "deck_id": "7966104", "colors": ["R", "W"], "key_cards": [ { "name": "Ragavan, Nimble Pilferer", "oracle_id": "…" }, { "name": "Ocelot Pride", "oracle_id": "…" } ] },
          "top": [
            { "finish": "1st Place", "archetype": "Boros Energy", "archetype_id": "modern-boros-energy", "player": "ashame", "deck_id": "7966104", "colors": ["R", "W"], "key_cards": [ { "name": "Ragavan, Nimble Pilferer", "oracle_id": "…" }, { "name": "Ocelot Pride", "oracle_id": "…" } ] },
            { "finish": "2nd Place", "archetype": "Gruul Aggro", "archetype_id": null, "player": "lunarbeam", "deck_id": "7966105", "colors": ["R", "G"], "key_cards": [ { "name": "Cori-Steel Cutter", "oracle_id": "…" }, { "name": "Mishra's Bauble", "oracle_id": "…" } ] },
            { "finish": "3rd Place", "…": "…" }
          ]
        }
      ]
    }
  ]
}
```

- **`formats`** are in this order: `standard`, `pioneer`, `modern`, `legacy`, `pauper`, `vintage`; a format is left out until its first scrape has produced a snapshot. `name` is its display name. The other formats (Premodern, Penny Dreadful, Duel Commander) are only in their snapshots.
- **`standings`** are the sixteen archetypes with the biggest 30-day share, most played first. `id` is the archetype's id in the snapshot (`snapshots/{format}.json` → `archetypes`), so a row links to all of that archetype's results and to its featured deck, and it names the file `archetypes/{id}.json`, its recent decks. `share_30d` and `share_7d` are percent of the format's decks, to one decimal; `share_7d` is null when the archetype isn't in the 7-day window. `deck_count_30d` is the number of decks behind `share_30d` (null if MTGGoldfish didn't show it). `top8_30d` counts the archetype's results in the last 30 days that finished 1st to 8th place, and `wins_30d` those that finished 1st. A league's `"5-0"` is a record, not a placing, so it counts toward neither, and results dated in the future are left out. `colors` and `key_cards` are as in the snapshot's meta, with only the first two key cards; a tile that shows no colours takes the colours of the archetype's featured deck (see *Colours of a result* below), which may be `[]`, so `[]` there still means colourless.
- **`standings_by_window`** is the standings for each of the snapshot's meta windows, for a 7 / 14 / 30 day switch. Each of `7d`, `14d` and `30d` is that window's sixteen archetypes with the biggest share *in that window*, most played first, so the members and their order can differ between windows. `id`, `name`, `colors` and `key_cards` are as in `standings`. `share` is the archetype's percent of the format's decks in that window, to one decimal, and `deck_count` the number of decks behind it (null if MTGGoldfish didn't show it). **`top8`** and **`wins`** count the archetype's results that finished 1st to 8th place and 1st within that window's own days (the last 7, 14 or 30, counted back from the run, so the `30d` pair is `top8_30d` and `wins_30d`); a League's record and a result dated ahead count toward neither. A window with no data (a snapshot from before it was scraped, or a format with `30d` only) is an empty list. `standings` is unchanged, and is the `30d` list with its extra counts. Added on 30 September 2026 (`top8` and `wins` on 1 October 2026), so decode it, and those two, as optional.
  - **`trend`** is `"up"` or `"down"` when the archetype's share is moving by more than one point, else null. It sets a shorter window's share against a longer one's: `7d` against `14d`, `14d` against `30d`, and for the `30d` list the last week (`share_7d`) against the month (`share_30d`). `"up"` means the shorter window is higher by more than one point, `"down"` lower by more than one point, judged on the shares as shown to one decimal, so a move of exactly 1.0 is null. It is null too when the archetype isn't in the window it is compared with (which is searched whole, not only its top eight).
- **`color_shares`** is how the whole metagame divides among the colours, for each of the snapshot's windows (`7d`, `14d`, `30d`), for a colour chart or a "what colour is the format" line. Each window is `{ "W", "U", "B", "R", "G", "C" }`, in percent to one decimal, `C` being colourless; all six keys are there and they add up to exactly 100.0. A window with no data is left out of the object, so `color_shares` is `{}` for a format with no metagame yet. It is worked out over **every** archetype of the window, not only the eight in `standings`: an archetype's weight over the six colours is the average, over the decks of it that are stored (the decks of its results, and its featured deck), of how much of each colour the deck's mainboard mana symbols ask for. Every symbol counts once per copy of its card, lands excluded; a hybrid symbol such as `{R/W}` is split among those of its colours the deck plays; a Phyrexian symbol (`{R/P}`), a generic one and `{X}` count nothing, and a deck with no symbols at all (artifacts and lands) is all `C`. An archetype with no stored deck whose cards are known splits its tile's colours evenly instead (`[]`, a colourless tile, is all `C`). A window's share of a colour is then the sum over its archetypes of the archetype's share times its weight, scaled so the six add up to 100 (MTGGoldfish's archetype shares add up to about 97-100), with the tenths rounded so they add up to exactly 100.0. Added on 1 October 2026, so decode it as optional.
- **`recent_events`** are the newest 30 events in the snapshot (20 until 30 September 2026), newest first, dated today or earlier (MTGGoldfish lists the occasional event weeks ahead, which is left out). They are every kind, Leagues and local events included, so filter on `kind` to show only Challenges and up. Modern has about four events a day (two or three Challenges and a League, plus the odd local one), so 30 is about a week of it, and fewer days for a format with more events; the rest of the month is in `snapshots/{format}.json`. The snapshot lists every event of the window, Leagues included, apart from a second import of a Challenge or League (see `events` above) and events with no decklists; an event is missing from `recent_events` only by being older than the newest 30, never because of its kind or its name. `name` is not unique (every day has a "Modern League", and "Modern League (1)" is a second, different one of the same day), so identify an event by its `id`. `name` is the event's name with its own date taken out (MTGGoldfish writes "Modern Challenge 32 2026-09-29"), which is in `date` (`yyyy-MM-dd`, UTC). `deck_count` is how many results MTGGoldfish published for the event, not the size of the field. `winner_archetype` and `winner_player` come from the 1st place result, and are null for Leagues and any event with no 1st place. `kind`, `source` and `url` are the snapshot event's.
  - **`prestige`** is how much the event weighs, from 1 to 4, for sorting or highlighting; it is worked out from the event's `kind`, its name and its number of results, so it needs no extra data. **4**: `pro_tour` and `regional_championship`. **3**: `rcq`; any event whose name has "Showcase" or "Super Qualifier"; a Magic Online Challenge of 64, 96 or 128 (its name says "Challenge 64", "Challenge 96" or "Challenge 128"). **2**: the other Challenges (32, and prelims); `store_championship`; and an `other` event with 64 results or more. **1**: everything else, every League (`mtgo_league`) included, and small local events. It is also on `events/{id}.json`. Added on 1 October 2026, so decode it as optional.
  - **`id`** is the event's id, MTGGoldfish's tournament id (the number at the end of `url`), and names the file `events/{id}.json`. **`result_count`** is the number of results published for the event, the same as `deck_count`.
  - **`lead`** is the result an event row can show without opening the event: the 1st place result, or, for an event with no 1st place (a League), the first result listed. It is `{ "finish", "archetype", "archetype_id", "player", "deck_id", "colors", "key_cards" }`: `finish` is a placing such as `"1st Place"` or a record such as `"5-0"`; `archetype_id` is null when the deck isn't in a tracked archetype, and `archetype` is then the pilot's own deck title; `deck_id` is `decks/{deck_id}.json`. `colors` are the colours of the deck and `key_cards` its two preview cards (see below). `lead` is null only when the event has no results. Added on 30 September 2026, so decode `id`, `result_count` and `lead` as optional.
  - **`top`** is the event's first three results in finish order (1st, 2nd, 3rd place; a League's are its first three listed), each shaped like `lead`: `{ "finish", "player", "archetype", "archetype_id", "deck_id", "colors", "key_cards" }`. `top[0]` is `lead`. It has fewer than three when the event has fewer results, and is `[]` when it has none. Added on 30 September 2026, so decode it as optional.
  - **Key cards of a result** (in `lead`, `top` and `events/{id}.json`) are always the two cards to draw for it, so a row never lacks a preview. They are, in order of preference:
    1. The first two of the archetype's tile in the format's metagame (from the longest window that shows it), as in `standings`, when `archetype_id` is set and the archetype has a tile.
    2. Otherwise (`archetype_id` is null because the deck isn't in a tracked archetype, or the archetype has left the metagame or shows no key cards) two cards of the deck's own mainboard, never a land: first a card whose name shares a word of four letters or more with the result's `archetype` (a "Beanstalk Control" deck picks a card with "Beanstalk" in its name; the best ranked such card), then the most played cards, the four-ofs first. Cards played in equal numbers go to the one with the higher price (Scryfall's USD price for the card, and a card with no price ranks below any priced one), then to the higher mana value, then to the decklist's order. Each is `{ "name", "oracle_id" }`, the name as the decklist writes it and Scryfall's oracle id, both from the stored decklist and Scryfall's catalog: a card the catalog doesn't know is skipped.
    3. `[]` only when the deck's list isn't stored yet (its `published` in `events/{id}.json` is false; the scraper downloads a capped number of decklists a run) or has no non-land card that Scryfall knows, such as a list of basic lands.
    Before 30 September 2026 only the first applied, so a result outside a tracked archetype had `[]`.
  - **Colours of a result** (**`colors`**, in `lead`, `top` and `events/{id}.json`) are the colours of the deck as `W`, `U`, `B`, `R`, `G` in that order. **`[]` means colourless** (a deck of artifacts, say), and **`null` means unknown**: not the same thing, so show a colourless deck as such and show nothing for an unknown one. They are, in order of preference:
    1. The pips MTGGoldfish showed beside the deck on the event's page, stored on the snapshot's result as `colors` (only events read since 1 October 2026 have them).
    2. Otherwise the colours the deck's own stored decklist is built in: the colours of the one-colour mana symbols (`{R}`, `{2/W}`) of its non-land cards, mainboard and sideboard together, or, for a deck with none, of its hybrid symbols (`{W/U}`); colourless `{C}` and Phyrexian symbols are not colours. A deck that is all artifacts is `[]`. These agreed with MTGGoldfish's own pips for all 32 decks of the one event page checked.
    3. Otherwise the colours of the result's archetype's tile (the longest window that shows it), and when that tile shows none, of the archetype's featured deck, as in `standings`. A tile that lists no colours, with no featured deck to ask, is `[]`.
    4. Otherwise `null`: the deck isn't stored (or none of its spells is in Scryfall's catalog), and its archetype is untracked, has left the metagame, or has a tile from before colours were read.

    Added on 1 October 2026 (before it a result had no `colors`), so decode it as optional.
- **`latest_event`** is the first of `recent_events` that has a winner, or the first if none has, or null when there are no events. It has the fields of a recent event except `winner_player` (so it has `top` too).
- An `explore.json` run for some formats only keeps the rest from the snapshots already published, and it isn't written at all when there is nothing to summarise.

## `archetypes/{archetype_id}.json`

One file per archetype in each format's current metagame (any of the `7d`, `14d` and `30d` windows), written with the snapshots. The `archetype_id` is a standings row's `id`, and ids are unique across formats. Every format's archetypes are written, including the three formats `explore.json` leaves out. Everything in it can be worked out from the snapshot; it is that archetype's slice, so a screen doesn't download the whole format.

```json
{
  "id": "modern-eldrazi",
  "name": "Eldrazi",
  "format": "modern",
  "colors": ["G"],
  "key_cards": [
    { "name": "Thought-Knot Seer", "oracle_id": "cef7396d-…" },
    { "name": "Emrakul, the Promised End", "oracle_id": "…" },
    { "name": "Kozilek's Command", "oracle_id": "…" }
  ],
  "shares": { "7d": 14.6, "14d": 14.4, "30d": 10.3 },
  "decks": [
    { "deck_id": "7977623", "date": "2026-09-29", "event_id": "66952", "event_name": "Modern Challenge 64", "finish": "15th Place", "player": "Uagli1", "published": true }
  ]
}
```

- **`colors`** and **`key_cards`** are as in the snapshot's meta, with up to three key cards (the tile's own three). A tile that shows no colours takes the colours of the archetype's featured deck (as in `explore.json`'s `standings`; `[]` when it is colourless or its list isn't stored), as one that shows no key cards takes three cards of the archetype's featured deck instead, picked as for a result's key cards (the namesake of the archetype's `name` first), and `[]` only when the featured deck's list isn't stored.
- **`shares`** is the archetype's percent of the format's decks in each window, to one decimal, null for a window that doesn't list it (or a format with no such window; Duel Commander has `30d` only).
- **`decks`** are the archetype's results in the snapshot, newest first, at most 60, dated today or earlier. Results of one day are in the snapshot's order, which is not by finish. `date` is `yyyy-MM-dd` (UTC) and `event_name` has the event's own date taken out, as in `explore.json`. `event_id` is null for a result without an event, and otherwise names `events/{event_id}.json`, when that event is in the last 30 days. `finish` is a placing or a League record.
- **`published`** is whether `decks/{deck_id}.json` exists. The scraper caps how many decklists it downloads each run (see above), so a new result can wait a run or two; it is false until then.
- An archetype with no results yet has `decks: []`.

## `events/{event_id}.json`

One file per event of the last 30 days, in every format, written with the snapshots and dated today or earlier. `event_id` is `id` in `explore.json`'s recent events and the snapshot event's `event_id`, and is unique across formats. An event the scraper left out as a duplicate has none.

```json
{
  "id": "66947",
  "name": "Modern League",
  "date": "2026-09-30",
  "kind": "mtgo_league",
  "prestige": 1,
  "source": "mtgo.com",
  "url": "https://www.mtggoldfish.com/tournament/66947",
  "format": "modern",
  "results": [
    {
      "finish": "5-0", "player": "aljce", "archetype": "Amulet Titan", "archetype_id": "amulet-titan", "deck_id": "7977435", "published": true,
      "colors": ["U", "R", "G"],
      "key_cards": [ { "name": "Primeval Titan", "oracle_id": "…" }, { "name": "Amulet of Vigor", "oracle_id": "…" } ]
    }
  ]
}
```

- `name`, `date` (`yyyy-MM-dd`, UTC), `kind`, `prestige`, `source` and `url` are as in a recent event in `explore.json`. `prestige` was added on 1 October 2026, so decode it as optional.
- **`results`** are in finish order, as the snapshot publishes them (as MTGGoldfish lists them; a League's are all `"5-0"`, in no particular order). Each carries what a snapshot event's result does (`finish`, `player`, `archetype`, `archetype_id`, `deck_id`), plus **`published`** (whether `decks/{deck_id}.json` exists), **`colors`** (the deck's colours, `[]` for colourless and `null` for unknown, from the event page, else the deck, else its archetype: see *Colours of a result* in `explore.json`; added on 1 October 2026) and **`key_cards`**, the result's two preview cards, chosen as for `lead` in `explore.json`: the archetype's tile when it has one, otherwise the deck's own namesake and most played cards. It is `[]` only for a result whose deck isn't stored yet (`published` false) or has no non-land card. A result with an `archetype_id` links to `archetypes/{archetype_id}.json` when that archetype is in the current metagame (it may 404 otherwise).
- These files are only rewritten, never deleted: when an event or archetype ages out it stops being linked from `explore.json` and the snapshots but its file stays where it was.

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

## `popular-cards/{format}.json`

One file per format a run built, written with the snapshots: the cards that format's decks play most over the last 7, 14 and 30 days, for a "popular cards" screen. Built from the stored decklists and the snapshot's dates, so it is as fresh as the snapshot.

```json
{
  "schema": 1,
  "format": "modern",
  "generated_at": "2026-10-01T00:52:13Z",
  "windows": {
    "7d": {
      "deck_count": 744,
      "lists": [
        {
          "kind": "all",
          "cards": [
            { "name": "Arid Mesa", "oracle_id": "c5acf2a5-…", "type": "land", "decks": 244, "share": 32.8, "copies": 3.0, "trend": null }
          ]
        },
        { "kind": "creature", "cards": [ { "name": "Solitude", "oracle_id": "dcb9c2a7-…", "type": "creature", "decks": 166, "share": 22.3, "copies": 3.8, "trend": null } ] }
      ]
    },
    "14d": { "deck_count": 1670, "lists": [ … ] },
    "30d": { "deck_count": 7620, "lists": [ … ] }
  }
}
```

- **What counts.** Every stored decklist dated inside the window, once each and unweighted, and `deck_count` is how many that is. A deck's date is its event's (`events[].date` in the snapshot), else its archetype result's (`archetypes[].results[].date`), so decks that only an archetype lists count too; big paper events are published there only. An archetype's featured deck has no date and is left out, and so is a deck dated after today (MTGGoldfish lists events still to be played). A window runs from `generated_at` minus 7, 14 or 30 days to the end of today, the rule behind the top 8s and wins in `explore.json`: as events are dated at midnight UTC, `7d` is today and the six days before it.
- **Boards.** `all` and every kind list rank by the mainboard, and `sideboard` by the sideboard. A card's **`decks`** is how many decks have at least one copy of it on that board, **`share`** that as a percent of `deck_count` (to one decimal) and **`copies`** the average number of copies in those decks (to one decimal; a card a list names twice is added up).
- **Basics are left out.** Every card whose front face has the Basic supertype: the five basic lands, Wastes and every Snow-Covered one. Other lands stay.
- **Lists.** In this order: `all`, `creature`, `planeswalker`, `instant`, `sorcery`, `artifact`, `enchantment`, `battle`, `land`, `sideboard`. A list with no card is left out, so a window with no decks has `"deck_count": 0` and `"lists": []`. `all` has at most 50 cards and every other list at most 25, most **`decks`** first, then most `copies` (as shown), then `name`. A card needs at least 2 decks and at least 1% of `deck_count` on the board the list ranks; a card the scraper's catalog doesn't know isn't listed.
- **`type`** is the list a card belongs to, from its front face's type line: the first of creature, planeswalker, battle, land, instant, sorcery, artifact and enchantment among the types before the "—". An Artifact, Enchantment or Land Creature is a creature, and an Artifact or Enchantment Land is a land. A double-faced card is its front face: a spell with a land on the back is a spell, an adventure or transform card is its front, "Kindred Instant" is an instant, and a split card is its first half. A card with none of these types (Scryfall gives a few the type line "Card" or "Hero") has the type `"other"`: it is in `all` (or `sideboard`) and in no list of a kind. None has been played enough to be listed yet, but decode `type` leniently.
- **`name`** is Scryfall's, the front face of any double-faced or adventure card ("Fable of the Mirror-Breaker"), and both halves of a split card ("Fire // Ice"). `oracle_id` is Scryfall's. The slug for `cards/{slug}.json` is built from `name` as in the suggested app flow.
- **`trend`** is `"up"` or `"down"` when the card's share of the decks on that board has moved against the period just before, and `null` when it has not, or when there are no decks in that earlier period. `7d` is set against days 8 to 14, `14d` against days 15 to 28, and `30d` sets its last 7 days against days 8 to 30. It moved when the share changed by more than 5 points and a two-proportion z-score is above 3, so a card in a handful of decks does not trend on chance.
- **Against `cards/{slug}.json`.** That page counts every stored deck of the last 30 days, featured decks included, adds the mainboard and sideboard together, and has one window. This file counts only decks with a date, keeps the boards apart, and has the three windows, so a card's `decks` here will not match its `decks` there.
- A run for some formats only keeps the other formats' files as they were published, and a run that could not read Scryfall's catalog leaves all of them as they were.

## `breakouts/{format}.json`

One file per format a run built, written with `popular-cards/{format}.json` from the same decklists: the cards new to the format's metagame, for a "cards to watch" screen. A card breaks out when the last 7 days' decks play it and the 23 days before barely did, whether it is a new release finding a home or an old card a new deck picked up. It says nothing about price.

```json
{
  "schema": 1,
  "format": "modern",
  "generated_at": "2026-10-01T02:41:07Z",
  "deck_count": 744,
  "baseline_deck_count": 2410,
  "cards": [
    {
      "name": "Psychic Frog", "oracle_id": "0f1d…", "type": "creature",
      "decks": 61, "share": 8.2, "previous_share": 0.4, "new": false, "first_seen": "2026-09-12", "mainboard": 58,
      "top8": 19, "wins": 3, "best_prestige": 3,
      "archetypes": [ { "id": "modern-dimir-frog", "name": "Dimir Frog", "decks": 40, "colors": ["U", "B"] } ],
      "price": 18.5
    }
  ]
}
```

- **Periods.** `deck_count` is the decks of the last 7 days and `baseline_deck_count` those of days 8 to 30, dated and counted as in `popular-cards` (every dated stored deck once, featured decks left out). A deck counts for a card when it plays it on either board; **`mainboard`** says how many of the card's recent decks play it main.
- **What breaks out.** At least 4 recent decks and 1% of them play the card, and its **`share`** of the recent decks (a percent, to one decimal) is at least three times its **`previous_share`** of the earlier ones. **`new`** is true when no earlier deck played it. With fewer than 20 earlier decks every card would look new, so `cards` is `[]`. Basics are left out.
- **Order.** Most `decks` first, then most `top8`, then `name`; at most 25 cards.
- **How the decks did.** **`top8`** and **`wins`** count the card's recent decks that placed 8th or better, or 1st (a League record such as `5-0` is no placing). **`best_prestige`** is the highest `prestige` (1 to 4, as in `explore.json`) of the events those decks were played in, so a card a Regional Championship deck played shows 4. A deck only an archetype's results list, from an event not stored, counts as 1.
- **`archetypes`** are the three archetypes with the most of the card's recent decks, most first, with `id` linking to `archetypes/{id}.json`. A deck outside a tracked archetype isn't counted here. Each has **`colors`**, the archetype's colours as `W`, `U`, `B`, `R`, `G` in that order, worked out as for its row in `explore.json`'s `standings` (its tile's, else those of its featured deck; see *Colours of a result* below). `[]` means colourless; the key is missing when they are unknown (an archetype outside the metagame's windows with no stored featured deck), so decode it as optional and fall back to the format's `standings`. Added on 2 October 2026.
- **`first_seen`** is the date of the earliest deck of the last 30 days that plays the card.
- **`name`**, **`oracle_id`** and **`type`** are as in `popular-cards`. **`price`** is Scryfall's current US dollar price of the printing its oracle-cards file picks for the card (regular, else foil, else etched), missing when it has none; for price moves see `movers/{format}.json`.
- A run for some formats only keeps the other formats' files as they were published, and a run that could not read Scryfall's catalog leaves all of them as they were.

## `movers/{format}.json`

One file per published format plus `all.json`, written every run: the cards whose price rose (`gainers`) or fell (`losers`) most over the last day, 7 days and 30 days, for a "market movers" screen.

```json
{
  "schema": 1,
  "format": "modern",
  "generated_at": "2026-10-01T02:41:07Z",
  "price_day": "2026-09-30",
  "windows": {
    "1d": {
      "gainers": [
        {
          "name": "Psychic Frog", "slug": "psychic-frog", "oracle_id": "0f1d…", "scryfall_id": "a7f3…", "set": "mh3",
          "price": 18.5, "previous": 14.25, "change": 4.25, "percent": 29.8,
          "history": [12.1, 12.3, …, 14.25, 18.5]
        }
      ],
      "losers": [ … ]
    },
    "7d": { "gainers": [ … ], "losers": [ … ] },
    "30d": { "gainers": [ … ], "losers": [ … ] }
  }
}
```

- **Prices.** TCGplayer's retail price in US dollars, from MTGJSON, as published in `catalog/prices/history.bin.gz` (the catalog workflow builds it at 10:17 UTC; this file is rebuilt from it by the scrape at 14:00). **`price_day`** is the last day MTGJSON has a price for, and every window ends on it, so `1d` sets `price_day` against the day before it.
- **A card's price** is the cheapest of its paper printings in the regular (non-foil) finish that day: what it costs to play it. A new, cheaper reprint lowers it from the day it is priced, so a reprint shows as a loss. Printings that are not the card to play with are left out: oversized cards, gold-bordered and other memorabilia, tokens, minigames, and the Un-sets and playtest cards. A printing's price holds over up to 3 days MTGJSON skipped, and after that the printing has no price. **`scryfall_id`** and **`set`** are the printing that is cheapest on `price_day`.
- **What moves.** A card is listed when it has a price on `price_day` and at the start of the window, cost at least $0.50 at both ends and at least $1 at one of them, and moved by at least $0.25, so bulk commons moving a few cents don't fill the lists. **`price`** is its price on `price_day`, **`previous`** at the start of the window, **`change`** the difference in dollars and **`percent`** that as a percent of `previous`, to one decimal.
- **Order.** `gainers` are the largest `percent` first, `losers` the most negative first, ties by `change`; each has at most 30 cards.
- **Formats.** A format's file lists only cards legal (or restricted) there, by Scryfall's legalities: `penny_dreadful` is Scryfall's `penny` and `duel_commander` its `duel`. It says nothing about whether the card is played; for that, see `popular-cards/{format}.json`. `all.json` lists every card, legal anywhere or not.
- **`history`** is the card's price on each of the last 30 days up to `price_day`, oldest first, for a sparkline, with `null` on a day it had none. It is the same in every window.
- **`name`** is Scryfall's, both faces of a double-faced card ("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"); `slug` is the card's `cards/{slug}.json`, which is a 404 for a card no tournament deck plays.
- A run that could not read the price history or Scryfall's printings leaves the files as they were, and is marked failed.

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

Upcoming Magic events near a configured place, read once a day from Wizards' Store & Event Locator. Places are set in the workflow (`LOCATOR_PLACES`); `locator/index.json` lists them. Events are the next `days_ahead` days within `distance_miles`, soonest first.

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
