# Published data format

Everything is static JSON at **`https://data.mooligan.com`**, rewritten by the scraper once a day. The run is scheduled for 14:00 UTC, but GitHub's scheduler has been starting it hours late (the scheduled runs of 30 September and 1, 2 and 3 October 2026 started at 19:01, 19:24, 19:08 and 17:52 UTC and finished at 19:35, 20:11, 19:55 and 18:46), and the files land about an hour after it starts. The `generated_at` of `explore.json`, `popular-cards/…` and `breakouts/…` is when the run started building them, and `today.json`'s is when it was built. Dates are UTC, in the form `2026-09-21T00:00:00Z`. The files are served compressed when the client accepts gzip or Brotli, which `URLSession` and browsers do by default.

| Path | Holds | Cache-Control |
| --- | --- | --- |
| `index.json` | What each format's snapshot is, with its hash | `max-age=60` |
| `explore-manifest.json` | The SHA-256 of each Explore file (`explore.json`, `today.json`, `previews.json`, `edh/top.json`, `rules/keywords.json`, `popular-cards/…`, `breakouts/…`), to see in one request which of them changed | `max-age=60` |
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
| `today.json` | One response for Explore's Today widgets: up to three breakout cards, the week's biggest mover and loser with their price over that week, the uprising EDH commander, and a preview | `max-age=300` |
| `previews.json` | The printings Scryfall added in the last 7 days from sets not released yet: the cards being previewed. `today.json`'s `preview` is one of them | `max-age=300` |
| `rules/keywords.json` | The keyword actions and keyword abilities of Magic's Comprehensive Rules, and the ability words, with the date the rules take effect. Changes only when Wizards publishes new rules | `max-age=300` |
| `sets/art.json` | Wizards' official art for each set, by Scryfall set code, for a set page's hero banner. Sets without art are left out | `max-age=300` |
| `sets/products/{code}.json` | One recent set's sealed products (boxes, boosters, bundles, decks) with TCGplayer's picture, link and price. Sets with no sealed products have no file | `max-age=300` |
| `sets/mechanics.json` | The keyword abilities, keyword actions and ability words each set introduced, by Scryfall set code, with rules, reminder text and example cards | `max-age=300` |
| `edh/commanders/{slug}.json` | One commander: what its decks play, and its average decklist | `max-age=300` |
| `edh/commanders/{slug}/guide.json` | One commander's play styles (EDHREC's themes), each with a whole deck per bracket it is played at, its five power brackets and its combos, built from EDHREC, Commander Spellbook and Scryfall | `max-age=300` |
| `edh/commanders/index.json` | Every commander published, with its deck count | `max-age=300` |
| `edh/top.json` | EDHREC's ranked top 100 commanders of the past week and the past month, with each one's share of the window's top 100 decks | `max-age=300` |
| `locator/{place}.json` | Upcoming in-store events near one place, from Wizards' locator | `max-age=300` |
| `locator/index.json` | The places published, with their coordinates | `max-age=300` |
| `premier/schedule.json` | Premier play: Pro Tours, Regional Championships, Spotlight Series, Worlds, CommandFests | `max-age=300` |
| `lore/app/cards.json` | Each card (by Scryfall `oracle_id`) to the story characters, planes and places it depicts | `max-age=3600` |
| `lore/app/sets.json` | Each set's key characters and places, by Scryfall set code | `max-age=3600` |
| `lore/app/entities.json` | Every lore entity that has a page: a one-sentence summary, a portrait card and its sets | `max-age=3600` |
| `lore/app/entities/{id}.md` | One entity's lore page, in playgraph primer markdown | `max-age=3600` |
| `catalog/…` | The card catalog: image feature prints, pull odds, price catalog. Layout in [`generators/README.md`](../generators/README.md) | `max-age=3600`; metas `max-age=300` |
| `state/…` | The scraper's own bookkeeping: stored deck ids, duplicate and empty events, deleted decks, decks with entries still lacking an `oracle_id` (`state/unresolved-deck-ids.json`), EDHREC check times, the commander counts `today.json`'s commander is compared with (`state/today-commanders.json`), the Scryfall printings the last run saw (`state/printing-ids.json.gz`) and when each recent one was first seen (`state/printing-first-seen.json.gz`), the localized cards of the last good run (`state/localized.json.gz`), the fingerprint of the published keyword rules (`state/rules-keywords.json`), the set art pages already read (`state/set-art.json`), the sealed products already read for each set (`state/set-products.json`), what each commander guide was built from and when (`state/guides.json`), the last run's manifest (`state/explore-manifest.json`), each format's snapshot as scraped, before its archetypes are merged (`state/snapshots/{format}.json`, which the next run starts from), and the last run's archetype groups (`state/archetype-groups/{format}.json`, member id to leader id). Apps can ignore them | `no-cache` |

Formats are `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful` and `duel_commander`. MTGGoldfish's Arena formats (Historic, Alchemy, Explorer, Timeless) are not published: it has almost no tournament data for them. `schema` is `1` (`today.json`'s is `2`), and it will change only if a field is removed or its meaning changes. Adding fields doesn't bump it, so decoders should ignore unknown keys.

## Suggested app flow

0. For a landing screen (an Explore tab), fetch `explore.json` alone: it has each main format's top archetypes and latest events in a few tens of KB, so nothing else has to download first.
   To keep the Explore files (`explore.json`, `today.json`, `previews.json`, `edh/top.json`, `rules/keywords.json`, and the `popular-cards/` and `breakouts/` files) up to date, fetch `explore-manifest.json` first and download only the files whose `sha256` differs from the copy you hold, in place of asking for each file. See [`explore-manifest.json`](#explore-manifestjson).
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

## Merged archetypes

MTGGoldfish names some archetypes apart that play one deck (Modern's "Eldrazi Ramp", "Eldrazi" and "Mono-Green Basking Broodscale Combo"; "Izzet Prowess" and "Temur Prowess"). Every published file shows such archetypes as one, under the id and name of its **leader**, and every result of them under the leader. Added on 17 October 2026: before it each MTGGoldfish archetype stood alone, so decode `merges` and `merged_into` as optional. The scraper keeps them apart in `state/snapshots/{format}.json`, so the groups are worked out afresh each run and an archetype that drifts away is published on its own again.

- **Lists compared.** An archetype's average list over a window is its mainboard's non-lands from the stored decklists of its decks in that window, each card at its share of the decks times its average copies (copies capped at 4). Two lists score their weighted cosine, 0 to 1.
- **Groups.** The archetypes with stored lists are taken biggest first: most decks in the last 30 days, then 14, then 7. Each joins the leader it scores highest against, at **0.8** or more, in any of the 7, 14 and 30 day windows where both have lists, and otherwise leads its own group. A member is so always close to its leader's own list, not only to another member, and no chain of look-alikes forms. One set of groups holds in every window, so an id means the same thing on the 7, 14 and 30 day lists, and `share_7d` and `trend` compare like with like. An archetype with no stored list in the last 30 days is never merged.
- **Groups hold from run to run.** Each run starts from the last run's groups (`state/archetype-groups/{format}.json`). A group keeps its leader, and so its id and name, unless one of its members now has more than 1.2 times the leader's decks of the last 30 days, which then leads it; so two close archetypes (Eldrazi Tron and Tron) don't swap the id every other day. A member stays in its group while it scores at least **0.75** against the leader, below the 0.8 a new member needs, so one scoring about 0.8 doesn't come and go. A group whose leader has no stored list left breaks up, and its archetypes are grouped afresh.
- **Overrides.** `scraper/mtgmeta/archetype_overrides.json` is kept by hand and wins over every score: `disabled` lists the formats published unmerged (Duel Commander, whose decks share most of their 99 across different commanders); `keep_apart` (per format, sets of archetype ids) never puts two ids of a set in one group, whether one would join the other or both one leader (Modern's 4c Energy and Azorius Control); `always_merge` (per format, sets of ids) joins every archetype of a set to the group of the biggest of them, whatever it scores.
- **Results with no archetype** (`archetype_id` null, the pilot's own deck title) join the leader whose own 30-day list theirs scores highest against, at 0.8 or more, and take its `archetype_id` and name.
- **Where it shows.** In `snapshots/{format}.json`: each window's `meta` lists a group once, under the leader, with the members' `percentage` and `deck_count` added up (`deck_count` null when a member's is) the leader's `key_cards` and featured `deck_id` (from its tile in that window, else its tile in the longest window that has one, else the biggest member's), and the group's colours, in order of share; `archetypes` has the leader only, its `results` every member's and the results that joined it, newest first; every event result of a member, or that joined, has the leader's `archetype_id` and name as `archetype`. `explore.json`, `archetypes/{id}.json`, `events/{id}.json`, `cards/{slug}.json`, `popular-cards/`, `breakouts/` and `today.json` are built from that snapshot, so they show the groups too. A result that joined a group adds to its results, top 8s and wins, but not to its `percentage` or `deck_count`, which are MTGGoldfish's.
- **A group's `colors`** are the colours at least half of its decks play, among its decks whose colours are known: every result of every member and every result that joined, each deck's colours being the pips MTGGoldfish showed on its event page, else those of its stored decklist (see *Colours of a result* in `explore.json`). Neither the leader's tile alone (Eldrazi Ramp's `["G"]` would hide a red half of the group) nor the union (one Gruul deck would make the group red). A group none of whose decks' colours is known keeps the leader's tile colours. An archetype that merged nothing keeps its tile's colours.
- **`merges`**, at the top of `snapshots/{format}.json`, maps every archetype id merged away to its leader's id (`{}` when none is). Decode it as optional.
- **An old id still opens.** `archetypes/{id}.json` for an id merged away is still written: it is the leader's file (with the leader's `id`), plus `"merged_into"` naming the leader. Decklists keep MTGGoldfish's own `archetype_id` (see `decks/{deck_id}.json`); `merges` maps it.
- A run that could not read Scryfall's card catalog (which tells the lands apart) publishes the snapshots unmerged.

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

## `explore-manifest.json`

The SHA-256 of each Explore file, so an app that keeps them can tell from one small response (about 2 KB for all 22 files) which ones changed, in place of asking for each of them. It is published as compact JSON, sorted by path. `index.json` is as it was: it still lists only the snapshots, so nothing that reads it changes.

```json
{
  "schema": 1,
  "generated_at": "2026-10-04T19:52:10Z",
  "files": {
    "breakouts/legacy.json": { "sha256": "1b6e…" },
    "explore.json": { "sha256": "9d40…" },
    "popular-cards/modern.json": { "sha256": "e7a2…" },
    "previews.json": { "sha256": "52b9…" },
    "today.json": { "sha256": "04cf…" }
  }
}
```

- **`files`** is keyed by path, as in the file's URL. It lists `explore.json`, `today.json`, `previews.json`, `edh/top.json`, `rules/keywords.json`, `popular-cards/{format}.json` and `breakouts/{format}.json`, and no other file. The `movers/{format}.json` files are not listed, as the app gets the movers through `today.json`; the snapshots are in `index.json`, and archetype, event, deck and card files are reached by following links.
- **`sha256`** is the SHA-256 of the file's bytes as written and uploaded, in lower-case hex. Cloudflare compresses a response in transit, so hash the body as received, after HTTP decompression (`URLSession` already hands you that), or the bytes you stored.
- **A run does not rewrite every file.** A run for some formats leaves the other formats' `popular-cards/` and `breakouts/` files as published, a run that could not read Scryfall's card catalog writes none of them, and `explore.json` and `today.json` can be skipped when they fail, and `previews.json` is skipped on a run that could not read Scryfall's printings, and `rules/keywords.json` is written only on a run that finds new rules. A file a run did not rewrite keeps the entry of the run that wrote it, and a file never published is not listed. The scraper carries the entries over from the last manifest, which it keeps in `state/explore-manifest.json`.
- **Uploaded last but for `index.json`**, after the files it lists and the state, so the manifest never names a hash that a file does not have yet. Its `generated_at` is when the manifest was written; each file has its own.
- **Using it.** Fetch `explore-manifest.json`, compare each `files[path].sha256` with the hash of the copy you hold, and download only the files that differ. For a path the manifest does not list, or when the manifest is a 404, ask for the file itself, for example with `If-None-Match`. A cache can hand out the previous copy of a file for up to its `max-age`, so if a download still differs from the manifest, keep it and check again at the next manifest.

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

- **`meta`** is keyed by window: `30d`, `14d` and `7d`. A format whose page has no window selector (Duel Commander) publishes `30d` only. Archetypes are in MTGGoldfish's order, most played first. `deck_count` can be null, and `deck_id` (the archetype's featured list) is null when it couldn't be read. Each archetype also has **`colors`**, the colours MTGGoldfish shows on its tile as letters (`W`, `U`, `B`, `R`, `G`) in that fixed order, `[]` for a colourless deck, and **`key_cards`**, up to three cards that stand for it, most representative first. They are the first three of the archetype's `hand` in `archetypes/{id}.json` (its most played mainboard non-lands of the last 7 days, from our stored decklists), and, for an archetype with no hand (no stored list in those days), the three cards MTGGoldfish's tile names. A key card is `{ "name", "oracle_id" }`, with Scryfall's oracle id matched from the name, or null when the catalog doesn't know it (join on `oracle_id`, not the name). Both are `[]` when the archetype has no hand and MTGGoldfish's tile doesn't show them, and are missing from snapshots published before 30 September 2026, so decode them as optional. Key cards come from the hand since 18 October 2026; before, they were always the tile's.
- **`events`** is newest first and covers every event MTGGoldfish lists for the format in the last 30 days: it is read from their tournament search, not just the "latest 10". Each has a **`kind`**, worked out from its name: `pro_tour` (also Worlds), `regional_championship`, `rcq` (RCQs and any other qualifier), `store_championship`, `mtgo_challenge` (Challenges, Showcases, prelims), `mtgo_league` (Magic Online Leagues: a league counts only when its `source` is `mtgo.com`, so a paper league imported from melee.gg is `other`), or `other` for local and unnamed events. Letters from another alphabet that look like a Latin one (a Cyrillic С in "Store Сhampionship") are read as the Latin letter. The `kind` is worked out again from the name and source on every run, so a fix to the rules corrects the events already stored (the `kind` of a League from melee.gg was `mtgo_league` until 1 October 2026). **`source`** is the site the results came from, usually `mtgo.com` or `melee.gg`, or null. MTGGoldfish sometimes imports a Challenge twice, and names the copy "… (1)". A copy with the same standings as another event is left out, here and in `archetypes`. A result's `finish` is a placing such as `"1st Place"` for Challenges, or a record such as `"5-0"` for Leagues. `archetype_id` is null when the deck isn't in a tracked archetype's list; `archetype` is then the pilot's own deck title. A result's **`colors`** are the pips MTGGoldfish shows beside the deck on the event's page, as `W`, `U`, `B`, `R`, `G` in that order. The key is there only for an event read since 1 October 2026 whose page showed some, and is absent otherwise (a colourless deck shows none, and an older event was not read for them), so decode it as optional: absent means unknown here, and `explore.json` and `events/{id}.json` fill it in (see below).
- **`archetypes`** is keyed by archetype id. `results` holds every deck of that archetype in the last 30 days, newest first. To group by event, group on `event_id`, which is null for the rare result without one; `event_name` is always set.
- Archetypes that play one deck are merged under their leader in `meta`, `events` and `archetypes`, and **`merges`** maps each id merged away to its leader: see [Merged archetypes](#merged-archetypes).

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
    1. The first two of the archetype's key cards in the format's metagame (from the longest window that shows it; the first two of its `hand`, else its tile's), as in `standings`, when `archetype_id` is set and the archetype has a tile.
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
- **`localized`** is the printed name and picture of every card in the file, in Japanese, French, Italian, Spanish and German, so the app can show Explore in the card language without asking Scryfall. See *`localized`* below. Added on 11 October 2026, so decode it as optional.
- An `explore.json` run for some formats only keeps the rest from the snapshots already published, and it isn't written at all when there is nothing to summarise.

### `localized`

`today.json` and `explore.json` have a top-level **`localized`**, keyed by the `oracle_id` of every card in the file (wherever an `oracle_id` appears in it), then by language code (`ja`, `fr`, `it`, `es`, `de`), then the card as printed in that language:

```json
"localized": {
  "33e3793c-098f-4897-88f3-9f9ce9081e0f": {
    "ja": { "name": "驕慢な戦闘魔道士", "image": "https://cards.scryfall.io/normal/front/1/7/174c608e-9086-4de8-ae28-51f537884b07.jpg?1790683523" },
    "fr": { "name": "Mage de bataille pompeux", "image": "https://cards.scryfall.io/normal/front/0/d/0d05d177-8b79-4717-9f16-ff3230101c4d.jpg?1790683507" }
  },
  "<double-faced oracle id>": {
    "ja": {
      "name": "秘密を掘り下げる者 // 昆虫の逸脱者",
      "image": "https://cards.scryfall.io/normal/front/…jpg?…", "back_image": "https://cards.scryfall.io/normal/back/…jpg?…",
      "faces": [{ "name": "秘密を掘り下げる者" }, { "name": "昆虫の逸脱者" }]
    }
  }
}
```

- **A key is left out when there is no value.** A card with no printing in a language has no entry for it (and one with none in any language has no entry at all), so an app shows the English card for what is missing. Every key of an entry is optional.
- **`name`** is the printed name: the card's `printed_name`; for a card with faces and none of its own, the faces' printed names joined with `" // "`, when every face has one; else the front face's.
- **`image`** is the `normal`-size picture (`https://cards.scryfall.io/normal/…`) of the printing. The path never changes for a printing; the `?` timestamp changes when Scryfall replaces the scan. **`back_image`** is the back face's picture, present only for a double-faced card whose two faces both have one; a double-faced card with only one of them has neither `image` nor `back_image`. A scan Scryfall marks `missing` or `placeholder` is never published.
- **`faces`** is there for a card with more than one face, one object per face in order, with the face's `name` (and, in `today.json`, its text); a face with nothing to say is `{}`.
- **The printing** is normally the same for every language of a card, and is chosen so the picture matches the card the app shows. The English printing is the newest paper printing (by `released_at`), then the lowest collector number (compared as a number where it has digits), then the set code. For each language the entry comes from that language's printing of the **same set and collector number** when it has one with a usable picture; otherwise (so that language does not share the printing) from that language's own newest paper printing with a usable picture. Tokens, art series cards, emblems, vanguard, scheme and planar cards, and printings not available in paper are never chosen.
- **Text, `today.json` only.** There the entry also has **`type_line`**, **`text`** and **`flavor_text`** (the printed type line, rules text and flavour text; each left out when the printing has none), and each of `faces` has the same three, so a card opened from Today reads in full offline. `explore.json` has the name and pictures only, as it holds many more cards.
- **Size.** About 55 KB gzipped in `explore.json` (175 KB raw, over about 1,200 entries) and 10 KB gzipped in `today.json` (33 KB raw) added to the figures above. They change with the file, which is about daily.
- **Missing.** A run with `LOCALIZE=0`, or one that could not read Scryfall's file and has no saved cards, publishes the file without `localized`. A run that could not read it but has the last good run's cards (`state/localized.json.gz`) publishes those instead, so a card new that day may be missing from it. Decode a missing `localized` as empty, and skip an entry that cannot be read rather than failing the file.

## `archetypes/{archetype_id}.json`

One file per archetype in each format's current metagame (any of the `7d`, `14d` and `30d` windows), written with the snapshots. The `archetype_id` is a standings row's `id`, and ids are unique across formats. Every format's archetypes are written, including the three formats `explore.json` leaves out. Everything in it can be worked out from the snapshot and the stored decklists; it is that archetype's slice, so a screen doesn't download the whole format. An archetype is a group of merged archetypes under its leader (see [Merged archetypes](#merged-archetypes)), and an id merged away has a file too: its leader's, with `merged_into`.

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
    {
      "deck_id": "7977623", "date": "2026-09-29", "event_id": "66952", "event_name": "Modern Challenge 64", "finish": "15th Place", "player": "Uagli1", "published": true,
      "event": { "id": "66952", "name": "Modern Challenge 64", "kind": "mtgo_challenge", "prestige": 3, "source": "mtgo.com", "deck_count": 64 },
      "changes": {
        "added": [{ "name": "Forest", "oracle_id": "…", "quantity": 2, "board": "main" }],
        "removed": [
          { "name": "Devourer of Destiny", "oracle_id": "…", "quantity": 1, "board": "main" },
          { "name": "Trinisphere", "oracle_id": "…", "quantity": 1, "board": "side" }
        ],
        "added_count": 2, "removed_count": 2
      }
    }
  ],
  "cards": {
    "window": "7d", "deck_count": 357, "list_count": 217,
    "main": [
      { "name": "Kozilek's Command", "oracle_id": "2f2c549d-…", "type": "instant", "decks": 217, "share": 100.0, "copies": 4.0 },
      { "name": "Forest", "oracle_id": "…", "type": "land", "decks": 214, "share": 98.6, "copies": 5.5 }
    ],
    "side": [
      { "name": "Trinisphere", "oracle_id": "…", "type": "artifact", "decks": 207, "share": 95.4, "copies": 2.5 }
    ]
  },
  "hand": [
    { "name": "Kozilek's Command", "oracle_id": "2f2c549d-…" },
    { "name": "Sowing Mycospawn", "oracle_id": "…" }
  ],
  "consensus": {
    "main": [
      { "name": "Forest", "oracle_id": "…", "quantity": 6 },
      { "name": "Kozilek's Command", "oracle_id": "2f2c549d-…", "quantity": 4 }
    ],
    "side": [{ "name": "Trinisphere", "oracle_id": "…", "quantity": 3 }]
  }
}
```

- **`colors`** and **`key_cards`** are as in the snapshot's meta, with up to three key cards: the first three of `hand`, in its order, so they are the first cards of the hand's fan; with no hand, the tile's own three. A tile that shows no colours takes the colours of the archetype's featured deck (as in `explore.json`'s `standings`; `[]` when it is colourless or its list isn't stored), as one that shows no key cards takes three cards of the archetype's featured deck instead, picked as for a result's key cards (the namesake of the archetype's `name` first), and `[]` only when the featured deck's list isn't stored.
- **`shares`** is the archetype's percent of the format's decks in each window, to one decimal, null for a window that doesn't list it (or a format with no such window; Duel Commander has `30d` only).
- **`decks`** are the archetype's results in the snapshot, newest first, at most 60, dated today or earlier. Results of one day are in the snapshot's order, which is not by finish. `date` is `yyyy-MM-dd` (UTC) and `event_name` has the event's own date taken out, as in `explore.json`. `event_id` is null for a result without an event, and otherwise names `events/{event_id}.json`, when that event is in the last 30 days. `finish` is a placing or a League record.
- **`published`** is whether `decks/{deck_id}.json` exists. The scraper caps how many decklists it downloads each run (see above), so a new result can wait a run or two; it is false until then.
- **`event`** is the deck's event as an event row of `explore.json`'s `recent_events` shows it, for a header: `{ "id", "name", "kind", "prestige", "source", "deck_count" }`, each as there (`name` without its date, `deck_count` the results published for the event). It is null for a result whose event isn't in the snapshot (no `event_id`, or an event outside the last 30 days). Added on 17 October 2026, so decode it as optional.
- An archetype with no results yet has `decks: []`.
- **`cards`** is the archetype's card tally from our stored decklists of its decks of the last 7 days (`window` is `"7d"`), counted back from the run as `explore.json`'s top 8s are. An archetype with no stored list in those days is counted over its decks of the last 30 days instead, when any of them has one (`window` is then `"30d"`), and its `hand`, `consensus` and decks' `changes` follow. `deck_count` is its decks in those days and `list_count` how many of them have a stored list, which is what the tally counts. `main` and `side` are the mainboard's and sideboard's cards, each `{ "name", "oracle_id", "type", "decks", "share", "copies" }` as in `popular-cards/{format}.json`: `type` is the kind of card from the front face's type line (`creature`, `planeswalker`, `battle`, `land`, `instant`, `sorcery`, `artifact`, `enchantment`, in that order of precedence, or `other`), `decks` the lists that play it, **`share`** their percent of `list_count` to one decimal (0 to 100, as every share in these files), and **`copies`** the average copies in the lists that play it, to one decimal. Lands and basics are in; a card Scryfall's catalog doesn't know is left out. Sorted by `decks` (so by share), then `copies`, then name. With no stored list, both are `[]`. Added on 17 October 2026, so decode it as optional.
- **`hand`** is the five mainboard non-lands that most stand for the archetype, by share times average copies (the card's copies over all the lists, divided by `list_count`), a tie going to the name: each `{ "name", "oracle_id" }`. Fewer when the lists have fewer, `[]` with none. Every key card list of the archetype (`key_cards` here and in the snapshot's meta, `explore.json`'s standings, and the key cards of its results) is the first cards of this hand, in its order, when it has any. Added on 17 October 2026, so decode it as optional.
- **`consensus`** is the archetype's common list, from the same lists as `cards` (its stored decklists of the last 7 days, or 30 as in `cards`): every card that at least half of `list_count` play on that board, at its average copies in the lists that play it (`copies` in `cards`), rounded half up (2.5 is 3) and at least 1. `main` and `side` are each `[{ "name", "oracle_id", "quantity" }]`, most copies first, then name. Lands and basics count like any card. A card Scryfall's catalog doesn't know is in too, named as the first list writes it, with a null `oracle_id`. With no stored list in those days, both are `[]`. The quantities need not add up to 60 and 15. Added on 18 October 2026, so decode it as optional.
- **`changes`** on a deck is how its list differs from `consensus`, card by card on each board: where it plays more copies than the consensus the difference is in `added`, where it plays fewer (or none) the difference is in `removed`, so a deck with two more Forests has `{ "name": "Forest", "quantity": 2, "board": "main" }` in `added`. Each is `{ "name", "oracle_id", "quantity", "board" }`, `board` being `"main"` or `"side"`, mainboard first, then most copies, then name; names are as in `consensus`. **`added_count`** and **`removed_count`** add up their `quantity`s. A deck as played as the consensus has both lists `[]` and both counts 0. Any deck of `decks` with a stored list has it, older decks too (compared with this week's consensus); it is null for a deck whose list isn't stored, and for every deck when the archetype has no stored list in the week (so `consensus` is empty). Added on 18 October 2026, so decode it as optional.
- **`merged_into`** is there only in the file of an id merged into another: the leader's id, which is also the file's `id`. The rest of the file is the leader's.

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
- **`results`** are in finish order, as the snapshot publishes them (as MTGGoldfish lists them; a League's are all `"5-0"`, in no particular order). Each carries what a snapshot event's result does (`finish`, `player`, `archetype`, `archetype_id`, `deck_id`), plus **`published`** (whether `decks/{deck_id}.json` exists), **`colors`** (the deck's colours, `[]` for colourless and `null` for unknown, from the event page, else the deck, else its archetype: see *Colours of a result* in `explore.json`; added on 1 October 2026) and **`key_cards`**, the result's two preview cards, chosen as for `lead` in `explore.json`: the archetype's tile when it has one, otherwise the deck's own namesake and most played cards. It is `[]` only for a result whose deck isn't stored yet (`published` false) or has no non-land card. A result with an `archetype_id` links to `archetypes/{archetype_id}.json` when that archetype is in the current metagame (it may 404 otherwise). A result of an archetype merged into another, or with no archetype of its own that joined one, has the leader's `archetype_id` and name (see [Merged archetypes](#merged-archetypes)).
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

Each entry's `oracle_id` is Scryfall's, matched from the name; it is null on decks published before 2026-09-23 and for names the catalog doesn't know, and `cards/index.json` (which carries `oracle_id` per card) resolves those by slug. `event_id` is null for an archetype's featured list. `archetype_id` points at the entry in the snapshot's `archetypes`, so a deck screen can link to everything else that archetype did. It is MTGGoldfish's id, written once with the deck: when that archetype is merged into another, the snapshot's `merges` gives the leader's id (its `archetypes/{id}.json` still opens, see [Merged archetypes](#merged-archetypes)). It is null for decks stored before 23 September 2026, and for decks outside a tracked archetype; those can still be found by searching the snapshot's `archetypes` for the `deck_id`. `card_name` is exactly as MTGGoldfish writes it. For a double-faced card that's the front face ("Fable of the Mirror-Breaker"), which Scryfall's `exact` lookup accepts.

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
      "name": "Psychic Frog", "oracle_id": "0f1d…", "scryfall_id": "3c9a…", "type": "creature",
      "decks": 61, "share": 8.2, "previous_share": 0.4, "new": false, "first_seen": "2026-09-12", "mainboard": 58,
      "top8": 19, "wins": 3, "best_prestige": 3,
      "results": [
        { "deck_id": "7977623", "date": "2026-09-29", "event_id": "66952", "event_name": "Modern Challenge 64", "prestige": 3,
          "finish": "2nd Place", "top8": true, "player": "Uagli1", "archetype": "Dimir Frog", "archetype_id": "modern-dimir-frog",
          "colors": ["U", "B"], "copies": 4, "mainboard": true }
      ],
      "price": 18.5
    }
  ]
}
```

- **Periods.** `deck_count` is the decks of the last 7 days and `baseline_deck_count` those of days 8 to 30, dated and counted as in `popular-cards` (every dated stored deck once, featured decks left out). A deck counts for a card when it plays it on either board; **`mainboard`** says how many of the card's recent decks play it main.
- **What breaks out.** At least 4 recent decks and 1% of them play the card, and its **`share`** of the recent decks (a percent, to one decimal) is at least three times its **`previous_share`** of the earlier ones. **`new`** is true when no earlier deck played it. With fewer than 20 earlier decks every card would look new, so `cards` is `[]`. Basics are left out.
- **Order.** Most `decks` first, then most `top8`, then `name`; at most 25 cards.
- **How the decks did.** **`top8`** and **`wins`** count the card's recent decks that placed 8th or better, or 1st (a League record such as `5-0` is no placing). **`best_prestige`** is the highest `prestige` (1 to 4, as in `explore.json`) of the events those decks were played in, so a card a Regional Championship deck played shows 4. A deck only an archetype's results list, from an event not stored, counts as 1.
- **`results`** lists every deck of the last 7 days that plays the card (so it has `decks` entries, with no cap), for showing which decks justify the call and which made top 8. Each has **`deck_id`** (which names `decks/{deck_id}.json` when that deck is published), **`date`** (`yyyy-MM-dd`), **`event_id`** and **`event_name`** (the name without its date, as in `events/{id}.json`; both null when the deck's event isn't stored), **`prestige`** (as in `explore.json`; 1 when the event isn't stored), **`finish`** (as the event lists it, such as `"2nd Place"` or a League's `"5-0"`; null if unknown), **`top8`** (true when the finish is a placing from 1st to 8th, so a League record is false), **`player`** (null if unknown), **`archetype`**, **`archetype_id`** and **`colors`**, **`copies`** (the card's copies in the deck, mainboard and sideboard together) and **`mainboard`** (whether it is played main). A deck outside the tracked archetypes is listed too, with a null `archetype_id` and the pilot's own deck title as its `archetype`. `colors` are those of a result in `events/{id}.json`: `[]` is colourless and `null` unknown (see *Colours of a result* above). The list is in order: top 8 decks first, then the rest; within each group higher `prestige` first, then better placing (placings before League records and unknown finishes), then newer `date`, then `deck_id`. This replaces the card's `archetypes`, which was removed on 2 October 2026; app decoders should treat it as gone.
- **`first_seen`** is the date of the earliest deck of the last 30 days that plays the card.
- **`name`**, **`oracle_id`** and **`type`** are as in `popular-cards`. **`scryfall_id`** is the printing Scryfall's oracle-cards file picks for the card, the one `price` is of; it is missing when the catalog has none, and present from 5 October 2026. **`price`** is Scryfall's current US dollar price of the printing its oracle-cards file picks for the card (regular, else foil, else etched), missing when it has none; for price moves see `movers/{format}.json`.
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
- **A card's price** is the cheapest of its paper printings that come in the regular (non-foil) finish: what it costs to play it. A printing Scryfall lists as foil-only is left out, as its regular-finish price is not one anyone can pay (The List's foil-only Fatespinner, newly priced at 95 cents, once made the card look like it fell from $10.45). Printings that are not the card to play with are left out too: oversized cards, gold-bordered and other memorabilia, tokens, minigames, and the Un-sets and playtest cards. A printing's price holds over up to 3 days MTGJSON skipped, and after that the printing has no price.
- **Like for like.** A window compares the printings that have a price at both of its ends: the card costs the cheapest of them on `price_day` and the cheapest of them at the start of the window. A printing priced for the first time in the window (a reprint just listed) is left out of that window, so it cannot make the card look cheaper or dearer than it was; it counts again once it has been priced at both ends of a window. **`scryfall_id`** and **`set`** are the cheapest of those printings on `price_day`.
- **What moves.** A card is listed when it has a price on `price_day` and at the start of the window, cost at least $0.50 at both ends and at least $1 at one of them, and moved by at least $0.25, so bulk commons moving a few cents don't fill the lists. **`price`** is its price on `price_day`, **`previous`** at the start of the window, **`change`** the difference in dollars and **`percent`** that as a percent of `previous`, to one decimal.
- **Order.** `gainers` are the largest `percent` first, `losers` the most negative first, ties by `change`; each has at most 30 cards.
- **Formats.** A format's file lists only cards legal (or restricted) there, by Scryfall's legalities: `penny_dreadful` is Scryfall's `penny` and `duel_commander` its `duel`. It says nothing about whether the card is played; for that, see `popular-cards/{format}.json`. `all.json` lists every card, legal anywhere or not.
- **`history`** is the price of those same printings on each of the last 30 days up to `price_day`, oldest first, for a sparkline, with `null` on a day none had one. It ends on `price`, and differs between windows only when a printing was priced for the first time in one of them.
- **`name`** is Scryfall's, both faces of a double-faced card ("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"); `slug` is the card's `cards/{slug}.json`, which is a 404 for a card no tournament deck plays.
- A run that could not read the price history or Scryfall's printings leaves the files as they were, and is marked failed.

## `today.json`

One response for Explore's Today widgets, so the app doesn't open a separate large file for each card. Built by `scraper/mtgmeta/today.py` at the end of each run from the `breakouts/` and `movers/all.json` just written, the EDHREC commander counts the run refreshed, and the printings Scryfall added since the last run, and uploaded with them (`max-age=300`). Published since 4 October 2026; **`schema` is `2`** since 5 October 2026 (see *Schema 1* below).

This example is the generator's real output for the files of the 4 October run, with the commander counts EDHREC gave on 5 October for 100 of the commanders checked on 30 September:

```json
{
  "schema": 2,
  "generated_at": "2026-10-05T19:31:04Z",
  "breakouts": [
    {
      "format": "modern", "formats": ["modern", "standard", "pioneer"],
      "name": "Pompous Battlemage", "oracle_id": "33e3793c-098f-4897-88f3-9f9ce9081e0f", "type": "creature",
      "decks": 41, "share": 3.3, "previous_share": 0.0, "new": true, "first_seen": "2026-09-30", "top8": 5, "wins": 0, "price": 2.3,
      "archetypes": [
        {"name": "Izzet Prowess", "id": "modern-izzet-prowess", "decks": 18, "colors": ["U", "R"]},
        {"name": "Grixis Prowess", "id": "modern-grixis-prowess", "decks": 1, "colors": ["U", "B", "R"]},
        {"name": "Jeskai Prowess", "id": "modern-jeskai-prowess", "decks": 1, "colors": ["W", "U", "R"]}
      ]
    },
    {
      "format": "standard", "formats": ["standard"],
      "name": "Liliana the Faultless", "oracle_id": "22c2e66d-a2a1-46db-a70a-dff5ad5d6c14", "type": "creature",
      "decks": 17, "share": 8.5, "previous_share": 0.0, "new": true, "first_seen": "2026-09-29", "top8": 4, "wins": 0, "price": 4.13,
      "archetypes": [
        {"name": "Lifegain", "id": "standard-lifegain-woe", "decks": 16, "colors": ["W", "B"]}
      ]
    },
    {
      "format": "vintage", "formats": ["vintage"],
      "name": "Avatar of Burgeoning Echoes", "oracle_id": "08e8a63c-9fcc-48cf-a9af-15cbaeec943f", "type": "creature",
      "decks": 9, "share": 6.9, "previous_share": 0.0, "new": true, "first_seen": "2026-10-02", "top8": 1, "wins": 0, "price": 3.31,
      "archetypes": [
        {"name": "Lurrus DRS", "id": "vintage-lurrus-drs", "decks": 3, "colors": ["U", "B", "G"]}
      ]
    }
  ],
  "movers": {
    "price_day": "2026-10-04",
    "mover": {
      "name": "Roxanne, Starfall Savant", "slug": "roxanne-starfall-savant", "oracle_id": "11765eaf-87a1-48bd-90c1-7a5f21be5918", "scryfall_id": "11fbe52f-febd-49fc-8391-28d3efe9c3eb", "set": "otj",
      "price": 1.22, "previous": 0.78, "change": 0.44, "percent": 56.4,
      "history": [0.47, 0.45, 0.45, 0.46, 0.49, 0.49, 0.49, 0.5, 0.5, 0.5, 0.51, 0.58, 0.6, 0.64, 0.69, 0.73, 0.73, 0.75, 0.77, 0.76, 0.78, 0.75, 0.74, 0.73, 0.72, 0.75, 0.8, 0.83, 0.78, 1.22]
    },
    "loser": {
      "name": "Bast, Panther Goddess", "slug": "bast-panther-goddess", "oracle_id": "e3233686-7703-460c-80ee-8cd37b3014ff", "scryfall_id": "c53a05f1-8e95-4a39-b2a3-a21d3d19b5b3", "set": "msc",
      "price": 0.82, "previous": 1.53, "change": -0.71, "percent": -46.4,
      "history": [1.2, 1.19, 1.16, 1.16, 1.17, 1.17, 1.17, 1.2, 1.19, 1.14, 1.14, 1.15, 1.06, 0.96, 0.96, 0.97, 1.0, 1.0, 1.02, 0.91, 0.91, 0.87, 0.86, 0.81, 0.81, 0.78, 0.76, 1.52, 1.53, 0.82]
    }
  },
  "commander": {
    "slug": "avacyn-angel-of-horror", "name": "Avacyn, Angel of Horror", "oracle_id": "…", "scryfall_id": "ff65f46b-0f82-49b8-93b9-7ac0243ce941", "color_identity": ["B"],
    "decks": 1722, "previous_decks": 1147, "rise": 575, "rise_percent": 50.1, "since": "2026-09-30",
    "days": 5, "rise_per_day": 115.0, "rise_percent_per_day": 10.03,
    "url": "https://edhrec.com/commanders/avacyn-angel-of-horror",
    "top_cards": [
      {"name": "Dark Ritual", "oracle_id": "…", "decks": 1459, "share": 84.7, "synergy": 0.17},
      {"name": "Gray Merchant of Asphodel", "oracle_id": "…", "decks": 1445, "share": 83.9, "synergy": 0.34},
      {"name": "Jet Medallion", "oracle_id": "…", "decks": 1315, "share": 76.4, "synergy": 0.14}
    ],
    "synergy_cards": [
      {"name": "The Sibsig Ceremony", "oracle_id": "…", "decks": 1118, "share": 64.9, "synergy": 0.63},
      {"name": "Blood Vassal", "oracle_id": "…", "decks": 223, "share": 13.0, "synergy": 0.13},
      {"name": "H.E.R.B.I.E. Scout Unit", "oracle_id": "…", "decks": 117, "share": 6.8, "synergy": 0.06}
    ],
    "attribution": {"name": "EDHREC", "url": "https://edhrec.com"}
  },
  "preview": { "card": null },
  "localized": {
    "33e3793c-098f-4897-88f3-9f9ce9081e0f": {
      "ja": { "name": "驕慢な戦闘魔道士", "image": "https://cards.scryfall.io/normal/front/1/7/174c608e-9086-4de8-ae28-51f537884b07.jpg?1790683523", "type_line": "…", "text": "…" },
      "fr": { "name": "Mage de bataille pompeux", "image": "https://cards.scryfall.io/normal/front/0/d/0d05d177-8b79-4717-9f16-ff3230101c4d.jpg?1790683507", "type_line": "…", "text": "…" }
    }
  }
}
```

Today is a row of widgets of four kinds: up to three breakout cards, the movers, the rising commander and the preview. The breakouts and the movers are built from files already published, so they add no data of their own; the commander comes from the EDHREC pages the run refreshed, and the preview from Scryfall's default-cards bulk file, which the movers read anyway. Every section is always present; one with nothing to show is `[]` (`breakouts`) or `null` (`commander`, `mover`, `loser`, `preview.card`).

### `breakouts`

A list of **1 to 3 cards**, fewer when fewer exist and `[]` when no format has a breakout. They are taken from one ranking, strongest first. Cards are ranked as cards, not as rows: a real release finds a home in several formats at once, while a card that four decks of one small format play may just be a tech. Cards are told apart by `oracle_id` (`name` when a row has none), and a card is listed once. The ranking, in this order:

1. The most **`decks` plus `top8`** added up over every format whose `breakouts/{format}.json` lists the card (a top 8 deck counts twice).
2. The largest gain in share (`share` minus `previous_share`) in any one format.
3. A card that is `new` (no deck of the 23 earlier days played it) in its busiest format (below) before one that is not: `new` only breaks a tie, since a new card needs only 4 decks and 1% of a format's decks.
4. `name`.

So a card seeing play in three formats (26 Standard decks, 13 in Pioneer, 6 in Modern) comes before a card 4 decks of Pauper play, new or not.

**Three formats where it can.** The three cards come from three different formats when three formats have a breakout: going down the ranking, a card is taken when no card taken so far has its busiest format (below), until there are three. Only when fewer than three formats have one is the list filled up with the next best cards whatever their format. The cards are listed in their ranked order. So the best card of a third format comes before a second card of a format already listed.

Each card is shown as its row in its busiest format: the format where it has the most `decks`, ties going to the format's place in the order of the formats above (`modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful`, `duel_commander`; a format not in it comes after, alphabetically). It has:

- **`format`**: that busiest format, the one whose numbers the card shows. **`formats`**: every format whose `breakouts/` file lists the card, new or not, `format` first and the rest in the order above.
- From that format's breakout row, as in `breakouts/{format}.json`: **`name`**, **`oracle_id`**, **`scryfall_id`** (the printing Scryfall's oracle-cards file picks for the card, whose price `price` is; present from the first run after 5 October 2026, so the example has none, and missing for a card it has no printing for), **`type`**, **`decks`**, **`share`**, **`previous_share`**, **`new`**, **`first_seen`**, **`top8`** and **`wins`**, and **`price`** when the row has one. `results`, `mainboard` and `best_prestige` are left out.
- **`archetypes`**: which decks play it, for "played in Izzet Prowess": the tracked archetypes of the row's `results` (the decks of the last 7 days that play it), counted by deck, most `decks` first, then `name`; at most 3. **`id`** is the archetype's `archetypes/{id}.json`, never null. A deck outside the tracked archetypes (a null `archetype_id` in `results`, named by its pilot) is left out, so `decks` can add up to less than the card's, and `archetypes` is `[]` when no deck playing it is in a tracked archetype. Each archetype's **`colors`** are its colour identity as letters (`W`, `U`, `B`, `R`, `G`) in that fixed order, `[]` for a colourless deck: the archetype's own, as its `archetypes/{id}.json` and `explore.json`'s standings show them (its tile's, else its featured deck's), else the colours most of the card's decks of that archetype have (the first listed in `results` on a tie). `colors` is left out when neither is known. Added on 5 October 2026, so decode it as optional.

### `movers`

- **`mover`** is the first of `gainers` and **`loser`** the first of `losers` in the `7d` window of `movers/all.json`: the card that rose most and the card that fell most over the last 7 days. They have the fields of a card there, copied as published and in that order: `name`, `slug`, `oracle_id`, `scryfall_id`, `set`, `price`, `previous`, `change`, `percent` and **`history`**, the card's price on each of the 8 days from `previous`'s to `price_day`, oldest first, with `null` on a day it had none: draw it as a small static sparkline. Its first point is `previous` and its last is `price`, so the line rises when `percent` does. Until 19 October 2026 these were the `1d` window's cards with 30 days of history, a month the percent did not cover. The `1d` and `30d` windows are not used, and nothing but the history's length is changed.
- **`price_day`** is the movers file's. Either card is `null` when its list is empty, and all three are `null` when `movers/all.json` is missing.

### `commander`

The uprising EDH commander: the commander whose deck count on EDHREC rose fastest, as a percent a day, since EDHREC was last asked about it. **This is EDHREC's data, used with their permission: an app showing it must credit EDHREC (`attribution`) and link to the commander's page (`url`).**

- **How a rise is seen.** Each run refreshes a slice of the commanders, longest unchecked first (`edh/commanders/{slug}.json`; 300 a run over about 4,200 commanders, so each comes round about every two weeks), and `edh/commanders/index.json` has only each one's latest count. So the run that builds `today.json` keeps, in `state/today-commanders.json`, every commander's count and when EDHREC gave it, and the next run compares: a commander EDHREC was asked about again since then can have risen, from **`previous_decks`** (its count then) to **`decks`** (its count now). Commanders not refreshed this run, and commanders refreshed for the first time, have no rise.
- **The floor.** A rise counts only with at least **50 `decks`** now, a **`rise`** of at least **10 decks** and a **`rise_percent`** of at least **10**. Most commanders barely move between two checks: of 100 commanders checked on 30 September and again on 5 October, half had the same count and the median change was 0%; a small commander swings by several percent on a deck or two (20 to 22 decks is +10%), which the deck floors keep out; and the three that cleared the floor rose 25% to 50% (Avacyn, Angel of Horror 1,147 → 1,722; Aerid Konstrari 2,184 → 2,893; Ghalta, the Immovable 330 → 414).
- **The ranking.** The checks of two commanders can be days or weeks apart (each run refreshes the longest unchecked, and a run can refresh more or fewer), so the commanders that clear the floor are ranked by their rise a day: **`rise_percent_per_day`**, the percent rise over the **`days`** between the dates of the two checks (at least 1). Ties go to the larger `rise_per_day`, then the larger `rise`, then the slug. The floor is on the whole rise, not the rise a day.
- **`null`** when no commander clears the floor, on the first run (there is no snapshot to compare with yet), and on a run that refreshed no commanders (`EDHREC_COMMANDERS_PER_RUN=0` or EDHREC unreachable).
- **The fields.** **`slug`** (its `edh/commanders/{slug}.json`), **`name`**; **`scryfall_id`** (the printing EDHREC shows) and **`color_identity`** (`W`, `U`, `B`, `R`, `G`; `[]` is colourless) as EDHREC has them, `null` when the run has no page for it; **`decks`**, **`previous_decks`**, **`rise`** (`decks` less `previous_decks`) and **`rise_percent`** (to one decimal); **`since`**, the day (`yyyy-MM-dd`) EDHREC gave `previous_decks`, so the rise is "since 30 September"; **`days`**, the days from `since` to this run's check (at least 1); **`rise_per_day`** (`rise` over `days`, to one decimal) and **`rise_percent_per_day`** (`rise_percent` over `days`, unrounded first, to two decimals), added on 5 October 2026, so decode them as optional; **`url`**, its page on EDHREC; **`attribution`**, `{"name": "EDHREC", "url": "https://edhrec.com"}`.
- **`oracle_id`** is on the commander and on each of its `top_cards` and `synergy_cards`, matched from the name against Scryfall's oracle cards, so `localized` and Scryfall can be joined on it. It is `null` when Scryfall's catalog has no card of that name, or when the run could not load the catalog. Added on 11 October 2026, so decode it as optional.
- **The decks' breakdown**, from the commander's `edh/commanders/{slug}.json`: **`top_cards`**, the first three cards of its Top Cards (the cards most of its decks play), and **`synergy_cards`**, the first three of its High Synergy Cards (the cards its decks play far more than other decks of its colours; EDHREC now calls the section High Lift Cards, and either is used). Each has **`name`**, **`decks`** (how many of the commander's decks play it), **`share`** (that as a percent of the commander's decks, to one decimal) and **`synergy`** (EDHREC's score, as in `edh/commanders/{slug}.json`; `null` when it has none). Either list is `[]` when the page has no such section.

### `preview`

Unchanged from schema 1. **`preview`** holds exactly one card, never a list: a printing Scryfall added since the last run, from a set not released yet. (The whole list of what was added in the last 7 days is [`previews.json`](#previewsjson).) Each run saves the id of every printing in Scryfall's default-cards bulk file (`state/printing-ids.json.gz`), and a printing whose id the last run did not have is new. Tokens, art series cards, emblems and other memorabilia, minigame inserts, oversized cards and digital-only printings are never the preview. Of the rest, only a new printing whose `released_at` is after the day of `generated_at` (in UTC) can be it; a printing released that day or earlier, or with no `released_at` or one that is not a date, cannot. Among those, the order is: a card's first printing before a reprint (Scryfall's `reprint`), so a new card wins over a new printing of an old card, as most of what Scryfall lists ahead of a release is reprints and promos; then the most recently previewed first (`previewed_at`), with one Scryfall has no preview date for after those it has, since it was added since the last run all the same; and ties go to the set code, then the collector number. The release date only decides who is eligible, never the order: a card previewed today beats one previewed earlier, however much later it is released.

**`card`** is `null` when there is none (as in the example): on a day Scryfall added no printing from a set not released yet, on the first run (it only saves the ids to compare with), and on a run that could not read Scryfall's file to its end or skipped the movers (`MOVERS=0`). Those last two leave the saved ids as they were, so the next run still finds the printings they missed. A printing that was new on a day with no card is not offered again, since the next run saves its id; so `card` is often `null`, and an app should show nothing for it rather than an older preview.

A preview card looks like this:

```json
"preview": {
  "card": {
    "name": "Overwrite the Multiverse", "oracle_id": "d037…", "scryfall_id": "c455…",
    "set": "fra", "set_name": "Reality Fracture", "released_at": "2026-10-23",
    "previewed_at": "2026-09-09", "source": "Wizards of the Coast", "source_uri": "https://magic.wizards.com/en/news/…"
  }
}
```

It has Scryfall's **`name`** (both faces of a double-faced card, as in `movers/`), **`oracle_id`**, **`scryfall_id`** (the printing, which Scryfall's API and images are keyed on), **`set`**, **`set_name`** and **`released_at`** (`yyyy-MM-dd`), and, when Scryfall has them, **`previewed_at`**, **`source`** and **`source_uri`**: when the card was previewed, by whom and where. Show `source` and link to `source_uri` wherever the card is shown with them. Decode every field but `name` as optional.

### Decoding

**`generated_at`** is when the file was built. A decoder should treat every section and every field but a card's `name` as optional, read `breakouts` as `[]` when it is missing, skip one entry it cannot read rather than fail the file, and ignore keys it doesn't know.

### Schema 1

The files of 4 and 5 October 2026 before the change are `"schema": 1`. They have no `breakouts`, `commander` or movers' `history`, and have instead an **`interesting_card`** object holding one `card` (or `null`): the first card of the ranking then (new cards first), with **`kind`** `"new_card"` (step 1) or `"released_card"` (step 2), `format`, and the row's `name`, `oracle_id`, `type`, `decks`, `share`, `previous_share`, `first_seen`, `top8`, `wins` and `price`. Schema 2 drops `interesting_card`. An app holding a stored schema-1 copy can read its card as a one-card `breakouts` (`new` is `kind == "new_card"`, no `archetypes`) until the next download replaces it.

## `previews.json`

The cards being previewed: every printing Scryfall added to its default-cards bulk file in the last 7 days that is from a set not released yet. It is the list behind a "View N more" link, in place of every unreleased card on Scryfall (about 800 printings, most of them listed months before their release). It is built from the same read of Scryfall's file as `today.json`'s [`preview`](#preview), whose one card is always one of these (when it is picked at all), and uploaded next to it with the same `max-age`. It is published as compact JSON.

```json
{
  "schema": 1,
  "generated_at": "2026-10-14T06:12:40Z",
  "window_days": 7,
  "count": 2,
  "cards": [
    {
      "name": "Overwrite the Multiverse", "oracle_id": "d037…", "scryfall_id": "c455…",
      "set": "fra", "set_name": "Reality Fracture", "collector_number": "88", "released_at": "2026-10-23",
      "first_seen": "2026-10-14", "previewed_at": "2026-10-13"
    },
    {
      "name": "Marsh Flats", "oracle_id": "9a1c…", "scryfall_id": "01b7…",
      "set": "fra", "set_name": "Reality Fracture", "collector_number": "311", "released_at": "2026-10-23",
      "first_seen": "2026-10-11", "previewed_at": null
    }
  ]
}
```

- **`cards`** holds a card for each printing (`scryfall_id`) that is eligible, was first seen within the last **`window_days`** (7) days and is not released yet. Eligible is as for `preview`: a paper card, not a token, art series card, emblem, other memorabilia, minigame insert, oversized card or digital-only printing. Not released yet means `released_at` is after the day of `generated_at` in UTC. A printing with no `released_at` or one that is not a date is not listed. A card leaves the list on the day it is released and 8 days after it was first seen: a printing first seen on 7 October is still listed on 14 October (`first_seen` is not more than 7 days before the day of `generated_at`) and gone on 15 October. **`count`** is `cards.length`. An empty list is a valid file: `{"cards": [], "count": 0}`.
- **Order** is fixed, so the same data gives the same bytes: the newest **`first_seen`** first, then the most recent **`previewed_at`** (a card with none after those with one), then `set` and `collector_number` (natural order: 9 before 10 before 10a), then `scryfall_id`. The release date is never used to order the cards; it only decides who is listed.
- **`first_seen`** (`yyyy-MM-dd`, UTC) is the day a run first saw the printing's id in Scryfall's file. It is the day the printing was added to Scryfall, to the day, as the scraper runs once a day. **`previewed_at`** is Scryfall's own preview date (`preview.previewed_at`), or `null`; it can be earlier than `first_seen`, as Scryfall adds some cards after a reveal. **`name`**, **`oracle_id`**, **`scryfall_id`**, **`set`**, **`set_name`**, **`collector_number`** and **`released_at`** are Scryfall's, as in `preview.card`. Decode every field but `name` and `scryfall_id` as optional.
- **How it is kept.** Each run saves the id of every printing in the file (`state/printing-ids.json.gz`), and an eligible printing whose id the last run did not have gets today's date as its first-seen date, in `state/printing-first-seen.json.gz` (a gzipped JSON object of id to `yyyy-MM-dd`). Old dates are kept. An entry is dropped once its date is more than 30 days old or its printing was released more than 30 days ago, or the printing is no longer in Scryfall's file. Dropping an entry never makes a printing new again, since new means "not in `state/printing-ids.json.gz`", which is never pruned.
- **Bootstrap.** The first run with no `state/printing-first-seen.json.gz` (the deploy of this file, or a lost state) cannot tell old printings from new ones, so every printing in the file counts as old, with no first-seen date, but for two kinds. An eligible printing whose id the previous run did not have is new, and gets today's date. An eligible, unreleased printing that has a Scryfall `preview.previewed_at` in the last 7 days (and not in the future) takes that date as its `first_seen`. So the list holds the cards revealed in the last week at once, rather than being empty for a week. After that run, nothing uses `previewed_at` to date a printing again. The first-ever run, with no ids saved either, bootstraps the same way. A run with a corrupt first-seen file bootstraps again.
- **When it is not written.** On a run that skips the movers (`MOVERS=0`) or could not read Scryfall's file to its end, `previews.json` is not rewritten and the state is not moved on, so the file stays as published by the last run that read the file; check its `generated_at`. The next complete run finds the printings the failed run missed.
- **App.** Fetch `previews.json` separately from `today.json` (it is listed in `explore-manifest.json`, so the manifest says when it changed) and show `count` and the cards. It is `max-age=300`, so a CDN or `URLSession` cache can serve an older copy for up to 5 minutes. A card's image and details are Scryfall's, keyed on `scryfall_id`.

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
  "color_identity": ["U", "R"],
  "scryfall_id": "ecc1027a-8c07-44a0-bdde-fa2844cff694",
  "generated_at": "2026-09-23T02:00:11Z",
  "sections": [
    {
      "tag": "topcards",
      "header": "Top Cards",
      "cards": [{ "name": "Brainstorm", "decks": 28385, "of_decks": 40779, "synergy": 0.28 }]
    }
  ],
  "average_deck": [{ "header": "Lands", "cards": ["Island"] }],
  "oracle_ids": { "Vivi Ornitier": "…", "Brainstorm": "…", "Island": "…" }
}
```

- **`color_identity`** (`W`, `U`, `B`, `R`, `G`; `[]` is colourless) and **`scryfall_id`** (the printing EDHREC shows for the commander) are EDHREC's, on a page written from 5 October 2026; an older page has neither, and either is `null` when EDHREC has none.
- **`sections`** are EDHREC's own groupings: `newcards`, `highsynergycards` (which EDHREC renamed `highliftcards`, High Lift Cards, in October 2026), `topcards`, `gamechangers`, then by card type. A card's `decks` of `of_decks` is how many of this commander's decks play it, and `synergy` is EDHREC's synergy score (0.28 means 28 percentage points more than other decks of the same colours would play it).
- **`average_deck`** is the typical list EDHREC builds for the commander, by card type. Names only, since it is one copy of each apart from basics.
- **`themes`** are EDHREC's themes (tags) for the commander, most decks first, each `{"slug", "name", "decks"}`: `slug` is the theme's EDHREC page, `https://edhrec.com/commanders/{slug}/{theme slug}`. **`bracket_decks`** counts the commander's decks by the Commander Bracket their builders gave them (`{"1": 154, "2": 3202, …}`; most decks give none). **`lands`** and **`basics`** are the land and basic land counts of EDHREC's average deck. All four are on pages written from 21 October 2026: decode them as optional.
- **`oracle_ids`** maps the commander's `name`, every card name in `sections` and every name in `average_deck` to its Scryfall oracle id. A name the catalog doesn't know is left out, so the object is `{}` on a page written by a run that couldn't load the catalog, and a page written before 11 October 2026 has none: decode it as optional and look a missing name up by name.
- Card names here match the `cards/{slug}.json` slug rule, so an app can link straight from a commander's list to a card page.
- Each run refreshes `EDHREC_COMMANDERS_PER_RUN` commanders (150 by default; the scheduled workflow sets 300, over about 4,200 commanders, so each comes round about every two weeks), longest unchecked first, but the commanders in [`edh/top.json`](#edhtopjson) go first, in their rank order, so each run refreshes them and a commander may otherwise be missing until its first turn. **This is EDHREC's data, used with their permission: credit them and link back to `url`.**

## `edh/commanders/{slug}/guide.json`

A commander's play styles and what each of Wizards' five Commander Brackets looks like for it, built from data with no model: EDHREC's theme and bracket pages for the commander, [Commander Spellbook](https://commanderspellbook.com)'s reading of its cards, and Scryfall's catalog. Each style has a whole deck for every bracket it is played at, filled the way the Mooligan app's Commander builder fills one. Not every commander has one; a missing file is a 404.

```json
{
  "schema": 1,
  "slug": "atraxa-praetors-voice",
  "name": "Atraxa, Praetors' Voice",
  "generated_at": "2026-10-21T14:40:00Z",
  "generator": "data-2",
  "model": null,
  "decks": 45745,
  "url": "https://edhrec.com/commanders/atraxa-praetors-voice",
  "styles": [
    {
      "id": "infect",
      "name": "Infect",
      "summary": "Infect is how 3,740 of Atraxa's 45,745 decks on EDHREC are built (8%). It leans on …",
      "brackets": [2, 3, 4],
      "decks": 3740,
      "url": "https://edhrec.com/commanders/atraxa-praetors-voice/infect",
      "cards": [{ "name": "Blighted Agent", "oracle_id": "…", "role": "payoff" }],
      "lists": [
        {
          "level": 3,
          "name": "Upgraded",
          "cards": [{ "name": "Smothering Tithe", "oracle_id": "…", "role": "ramp" }],
          "basics": [{ "name": "Forest", "count": 4 }],
          "lands": 36,
          "price": 812.4,
          "bracket": 3,
          "game_changers": 3,
          "mass_land_denial": 0,
          "extra_turns": 0,
          "combos": ["1529-5902"]
        }
      ]
    }
  ],
  "brackets": [
    {
      "level": 3,
      "name": "Upgraded",
      "summary": "4,033 of Atraxa's decks on EDHREC are built for Bracket 3, Upgraded. Up to three Game Changers, …",
      "decks": 4033,
      "cards": [{ "name": "Smothering Tithe", "oracle_id": "…", "role": "ramp" }]
    }
  ],
  "combos": [
    {
      "id": "1529-5902",
      "cards": [{ "name": "Vraska, Betrayal's Sting", "oracle_id": "…" }, { "name": "Innkeeper's Talent", "oracle_id": "…" }],
      "requires": [],
      "results": ["Target opponent loses the game"],
      "bracket": 3,
      "bracket_tag": "S",
      "two_card": true
    }
  ]
}
```

- **`styles`**: EDHREC's themes for the commander (its tags) with at least 30 decks, most decks first, at most 5. A commander with none gets one style, `Average Deck` (`id` `average-deck`), built from its own page. **`id`** is EDHREC's slug for the theme (`plus-1-plus-1-counters` for `+1/+1 Counters`), unique within the file. **`decks`** is how many of the commander's decks EDHREC tags with the theme, and **`url`** its EDHREC page (credit them and link to it).
  - **`brackets`**: the levels from the lowest to the highest that holds a tenth or more of the theme's decks (by the bracket their builders gave them), ascending and with no gaps; the commander's own split stands in when fewer than 30 of the theme's decks give one, and `[2, 3]` when neither does.
  - **`lists`**: one deck per level of `brackets`, in the same order. **`cards`** are its 99 (98 with a partner pair) less the basics, which **`basics`** counts; a card is listed once. **`lands`** is its land count, basics included. **`price`** is in US dollars, Scryfall's price for each card (its regular printing, else foil, else etched) and the basics, with a card Scryfall has no price for counted as nothing. **`bracket`** is the lowest bracket whose rules the deck keeps, checked as below (a deck built for 5 reads 4: the rules do not tell the two apart). **`game_changers`**, **`mass_land_denial`** and **`extra_turns`** count its cards of each kind. **`combos`** are the ids of the guide's `combos` whose pieces are all in the deck or the commander.
  - **`cards`**: the spells of the style's lowest deck (no lands), the ones the theme's decks play most first, at most 60. With `brackets` and the guide's bracket `cards`, this is what the app has shown since the AI-written guides; `lists` is the whole deck.
- **How a deck is filled.** Every card on the theme's EDHREC page and the bracket's is scored by its share of the theme's decks, moved by how much more or less the bracket's decks play it than the commander's decks overall. A bracket page with fewer than 30 decks gives way to the nearest level's that has more (the higher one on a tie). Cards are dropped when Scryfall's catalog does not know them, when they are outside the colour identity, basic lands, the commander itself, or banned in Commander (Spellbook's reading). Then, as the app's builder does (`Core/Networking/Sources/Collection/Builder`): the best 10 ramp, 10 draw, 10 removal or counterspells, 3 board wipes and 3 protection; a land target of 36, one fewer with 12 or more ramp, one more when the spells' average mana value is over 3.5; payoffs, engines, tutors and the rest in the slots left; then the best nonbasic lands, as many as the theme's decks play on average; and basics for the rest, split by the colour pips of the spells' mana costs. A card the bracket's rules refuse is skipped. A colourless commander gets no basics, only more lands and spells.
- **A card** has **`name`** and **`oracle_id`** as Scryfall's catalog has them (a double-faced card is named with both faces), and **`role`**, one of `land`, `ramp`, `draw`, `removal`, `counter`, `wipe`, `protection`, `tutor`, `payoff`, `engine`, `combo`, `utility`. The role is the app builder's reading of the card's rules text: the first of land, wipe, counter, removal, ramp, tutor, draw, protection, engine (a permanent with "whenever" or "at the beginning of"), payoff (a creature or planeswalker), else utility. In a deck of `lists`, a spell that is a piece of one of the deck's combos is `combo`.
- **The bracket rules** (Wizards', October 2025), checked card by card as a deck is filled: no Game Changers at 1 and 2, at most three at 3; no mass land denial below 4; no extra turns at 1 and at most two at 2 and 3; and no card that completes a combo whose `bracket` is above the deck's. The Game Changers are `scraper/mtgmeta/game_changers.json`, by oracle id; which cards are mass land denial or extra turns, and which are banned, is Spellbook's estimate-bracket reading of the commander's whole card pool (at most 600 cards, the best by inclusion on any of its pages).
- **`brackets`**: always five, levels **1** to **5** in order, with Wizards' names: 1 `Exhibition`, 2 `Core`, 3 `Upgraded`, 4 `Optimized`, 5 `cEDH`. **`decks`** is how many of the commander's decks are built for it. **`cards`** (at most 30) set it apart: the cards its decks play more than the commander's decks overall, most lifted first, within the bracket's rules (the nearest bracket page with 30 decks stands in for a smaller one). The app shows a style's deck at a level as the style's `cards` and these.
- **`combos`**: the combos the guide's decks hold, from Spellbook's estimate-bracket on the commander's card pool, every one some deck of `lists` holds, the most played first, one per set of cards. A combo is kept when Spellbook marks it OK, not a spoiler, legal in Commander and not banned. **`id`** is Spellbook's variant id (`https://commanderspellbook.com/combo/{id}`). **`cards`** are its pieces, the commander among them when it is one, named and identified as Spellbook has them. **`requires`** names the other pieces it needs, as Spellbook's templates (`"Permanent Castable for {C}"`). **`results`** is what it makes, Spellbook's standalone and contextual features only. **`bracket_tag`** is Spellbook's own tag: `E` (Exhibition), `C` (Core), `O` (Oddball), `P` (Powerful), `S` (Spicy), `R` (Ruthless). **`bracket`** is the lowest bracket it is allowed at: from the tag, `E` 1, `C` and `O` 2, `P` and `S` 3, `R` 4, and at least 3 for a **`two_card`** combo, as the brackets allow none below 3. A combo is `two_card` when it has two pieces (the commander counts as one), whatever Spellbook's flags say: Spellbook tags Hullbreaker Horror + Sol Ring `E` and does not call it two-card, but it is `bracket` 3. A combo Spellbook calls two-card (definitely or arguably) is `two_card` too. A style's combos are those its `lists` name.
- **`summary`** of a style and of a bracket is written from these numbers by template, and then, on the daily run when the `ANTHROPIC_API_KEY` secret is set, rewritten by Claude (`claude-sonnet-5-5`) as prose from the guide's own facts, with nothing else changed; **`model`** is then the model that wrote them, and `null` for a templated guide. A guide can be published templated and polished by a later run (a day at most when the batch outlasts the run). A polish is asked for only when the guide's facts changed since its last one: a guide rebuilt with the same facts keeps its polished summaries. **`generator`** names the build (`data-2`); a change to it rebuilds every guide. **`generated_at`** is when it was built. `name` and `decks` are EDHREC's, as on the commander's page.
- **The Game Changers** are kept in `scraper/mtgmeta/game_changers.json` (53 cards on 20 October 2026, read from Scryfall's `is:gamechanger`, which follows Wizards' list). Update it when Wizards changes the list; a change rebuilds every guide on its next run.
- **When it is written.** Each daily run builds the guides of the first 100 commanders of [`edh/top.json`](#edhtopjson)'s windows (`GUIDES_TOP`) and of every commander its `brackets` rank (about 200 together) that are due, at most `GUIDES_PER_RUN` (45) a run, never built first and then the oldest: at most 10 EDHREC pages (up to 5 theme pages and the five bracket pages; the commander's own page is the one the run just wrote), `GUIDE_DELAY` (1) seconds apart, and one Spellbook call each. A guide is due when it was never built by this generator, a week after it was built, when the commander's themes or the Game Changers change, or when its decks have moved by a tenth. `state/guides.json` keeps, per slug, the `generator`, a `fingerprint` of the themes and Game Changers, `built_at`, the `decks` it was built from, the `model` that polished it and the `polish_hash` of the facts it was polished from (the model, the instructions and the guide's facts). The run's polish is one Message Batch of the guides it built whose facts changed; the run waits for it up to `POLISH_WAIT_MINUTES` (15), and a batch still running is kept in `state/polish-batch.json` and written by the next run, if the guide's facts are still the ones it was asked from. A request that fails, or answers without the tool, leaves that guide templated. A commander Spellbook cannot be read for this run is not built, and its published guide stays. `python -m mtgmeta guides DIR --top N` (or `--slug`) builds them by hand, `--brackets` adds every commander `edh/top.json`'s brackets rank, `--limit` caps how many are built, `--polish` polishes them as one batch, and `--force` builds them whether due or not. Guides of commanders that leave the lists are not removed.
- `python -m mtgmeta guide-combos DIR --top N` still adds find-my-combos combos to published AI-written guides, and leaves a guide with a `generator` as it is.
- The card pool it is built from is EDHREC's data, used with their permission: credit them and link to the `url` of the guide and of each style.

## `edh/top.json`

EDHREC's ranked top 100 commanders for the past week (`7d`) and the past month (`30d`), each with its share of the window, and the 50 commanders most played at each Commander Bracket (`brackets`). Each commander's `slug` is the one of its page, `edh/commanders/{slug}.json`; a run puts the windows' commanders at the front of the commander refresh, and reads the pages of the ones `brackets` ranks a week apart, so a commander listed here has a page.

```json
{
  "schema": 1,
  "generated_at": "2026-10-19T14:05:00Z",
  "windows": {
    "7d": {
      "decks": 89845,
      "commanders": [
        {
          "rank": 1,
          "slug": "jace-multiverse-architect",
          "name": "Jace, Multiverse Architect",
          "decks": 4063,
          "share": 4.5,
          "color_identity": ["W", "U", "B", "R"],
          "oracle_id": "3321c134-bf5b-4f63-8035-fca0bbdfa86b",
          "scryfall_id": "55cd03d9-2535-4cf3-a8b2-1418e1190f4a",
          "trend": 50.4
        }
      ]
    },
    "30d": { "decks": 291869, "commanders": [] }
  },
  "brackets": {
    "3": {
      "name": "Upgraded",
      "source": "edhrec",
      "decks": 61234,
      "commanders": [
        {
          "rank": 1,
          "slug": "atraxa-praetors-voice",
          "name": "Atraxa, Praetors' Voice",
          "decks": 5012,
          "of_decks": 45745,
          "share": 8.2,
          "color_identity": ["W", "U", "B", "G"],
          "oracle_id": "…",
          "scryfall_id": "…"
        }
      ]
    },
    "5": {
      "name": "cEDH",
      "source": "edhtop16",
      "window": "3m",
      "entries": 10253,
      "commanders": [
        {
          "rank": 1,
          "slug": "kraum-ludevics-opus-tymna-the-weaver",
          "name": "Kraum, Ludevic's Opus // Tymna the Weaver",
          "entries": 1051,
          "top_cuts": 309,
          "conversion_rate": 29.4,
          "decks": 4142,
          "of_decks": 12131,
          "share": 10.3,
          "color_identity": ["W", "U", "B", "R"],
          "oracle_id": null,
          "scryfall_id": null
        }
      ]
    }
  }
}
```

- **`decks`** of a window is the sum of its 100 commanders' `decks`, and a commander's **`share`** is its `decks` as a percent of that, to one decimal. It is a share of the window's top 100 decks, not of every Commander deck EDHREC has: the shares of a window add up to 100.
- **`rank`** is EDHREC's, 1 the most played; the commanders are listed in rank order. **`trend`** is EDHREC's trend z-score, to one decimal (`null` when it has none).
- **`color_identity`** (`W`, `U`, `B`, `R`, `G`, in that order; `[]` is colourless), **`oracle_id`** and **`scryfall_id`** are Scryfall's, looked up by name in the card catalog, and `null` for a name it does not know, or when the run could not load the catalog. A partner pair EDHREC lists as one commander ("Kraum, Ludevic's Opus // Tymna the Weaver") is no one card: its ids are `null` and its colour identity is both halves' together.
- **A window that could not be read is left out of `windows`**; when neither could be, the file is not rewritten and the last one stays published. Decode `windows` keys as optional. A run with `EDHREC_COMMANDERS_PER_RUN=0` does not read EDHREC for it either.
- **`brackets`** has a key per Commander Bracket, `"1"` to `"5"`, each with Wizards' **`name`** (`Exhibition`, `Core`, `Upgraded`, `Optimized`, `cEDH`) and up to 50 **`commanders`**, most played first. A bracket that could not be ranked this run is left out, and `brackets` itself is missing when none could be (or from a file written before it existed): decode both as optional. The keys are strings, as JSON's must be.
  - **Brackets 1 to 4** (`source` `edhrec`) rank EDHREC's top 300 commanders of the past month by **`decks`**, how many of each one's decks their builders put at that bracket, out of its **`of_decks`** decks on EDHREC (most decks give no bracket, so the levels do not add up to `of_decks`). The bracket's **`decks`** is the sum of its commanders', and a commander's **`share`** its `decks` as a percent of that, to one decimal. EDHREC's counts are over every deck it has for the commander, not only the past month's; the past month picks which commanders are ranked. Bracket 1 counts are small (tens of decks), so its order is noisy.
  - **Bracket 5** (`source` `edhtop16`) ranks the commanders of competitive tournaments by **`entries`**, their decks entered at [EDHTop16](https://edhtop16.com)'s events of 30 or more players in the past three months (**`window`** `3m`), with **`top_cuts`** and **`conversion_rate`** (the percent of entries that made the top cut, to one decimal). The bracket's **`entries`** is the sum of its commanders', and `share` is of that. **`decks`** and **`of_decks`** are EDHREC's Bracket 5 and total counts for the commander, `decks` `null` when it has none. EDHREC's Bracket 5 counts are what builders call their own decks, so they rank popular casual commanders beside cEDH ones (Etali, Primal Conqueror has 2,532 "cEDH" decks on EDHREC and about 40 tournament entries a month); tournament results are what cEDH players do play. A commander EDHTop16 lists that EDHREC has no page for is left out. When EDHTop16 cannot be read (and no read of the past week is cached), Bracket 5 is ranked like the others, by EDHREC's counts, with `source` `edhrec` and no `window` or `entries`.
  - A commander's `name` is EDHREC's (a partner pair is "A // B"), and its ids and colour identity are found as for the windows.
- It is listed in `explore-manifest.json`. **This is EDHREC's data, used with their permission: credit them and link to the commander's `url` on its page. Bracket 5 with `source` `edhtop16` is EDHTop16's tournament data: credit EDHTop16 and link to https://edhtop16.com.**

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


## `rules/keywords.json`

What the Comprehensive Rules say about each keyword, so an app can show the rule behind a word on a card. Wizards publishes the rules as a text file a few times a year (on <https://magic.wizards.com/en/rules>); each run finds the link on that page, reads the file and keeps the keyword actions (rule 701), the keyword abilities (rule 702) and the ability words (rule 207.2c), and nothing else. The file is built on every daily scrape but **changes only when Wizards publishes new rules**: a run that finds the same rules writes nothing, so the file keeps its `generated_at`, its bytes, its hash in `explore-manifest.json` and its ETag, and `generated_at` is when the rules last changed here. It is compact JSON, about 200 KB (45 KB gzipped).

```json
{
  "schema": 1,
  "generated_at": "2026-10-12T14:00:07Z",
  "effective_date": "2026-09-25",
  "source_url": "https://media.wizards.com/2026/downloads/MagicCompRules%2020260925.txt",
  "keywords": {
    "flying": {
      "name": "Flying",
      "number": "702.9",
      "rules": [
        "Flying is an evasion ability.",
        "A creature with flying can’t be blocked except by creatures with flying and/or reach. A creature with flying can block a creature with or without flying.",
        "Multiple instances of flying on the same creature are redundant."
      ]
    }
  },
  "ability_words": {
    "number": "207.2c",
    "text": "An ability word appears in italics at the beginning of some abilities. Ability words are similar to keywords in that they tie together cards that have similar functionality, but they have no special rules meaning and no individual entries in the Comprehensive Rules.",
    "words": ["adamant", "addendum", "alliance", "…", "will of the council"]
  }
}
```

- **`effective_date`** is the date from "These rules are effective as of …", as `YYYY-MM-DD`: show it as the version of the rules.
- **`source_url`** is the text file the rules were read from, the link found on Wizards' rules page (the file name carries its date, so it changes with every edition).
- **`keywords`** holds every named entry of rule 701 (keyword actions) and rule 702 (keyword abilities), about 260, keyed by the **lower-cased name** and in the order of the rules. The introductions of the two sections (701.1, 702.1) are not entries. **`name`** is the name as the rules write it, **`number`** is the rule's number (`702.9`), and **`rules`** are its subrules (`702.9a`, `702.9b`, …) in order, without their letters. Cross references in parentheses are removed ("(See rule 509, “Declare Blockers Step,” and rule 702.17, “Reach.”)"), and so are the examples. A cross reference written as a sentence stays ("See rule 701.28, “Convert.”"), and so does reminder text. Text uses the rules' curly quotes and apostrophes.
- **`ability_words`** is rule 207.2c: **`text`** is its sentences before the list (what an ability word is), and **`words`** are the listed ability words, lower-cased as the rules write them and in their order (about 60; "descend 4" and "descend 8" are two words). An ability word has no entry of its own in the rules, so an app that shows 207.2c for it names the word itself.
- **Looking a word up.** Keys are lower-cased and spelled as the rules spell them, curly apostrophes included (`council’s dilemma`), so lower-case a card's keyword and compare apostrophes the same way. The rules describe a family of keywords in one entry: every “[type]walk” (islandwalk, snow swampwalk) is under `landwalk`, and the typecycling variants (plainscycling, swampcycling) are under `cycling`. An ability word has no entry of its own: `ability_words` is all the rules say about it.
- **When it is missing.** A run that cannot read Wizards' page or file (the site is down, the link or the text changed shape) logs a warning and does not fail; the file stays as last published, and the next run tries again. Until the first successful run the file is a 404.

## `sets/art.json`

Wizards' own art for each set, so a set page can open with a hero banner. Wizards has no list of it, so each run reads their sitemap (<https://magic.wizards.com/en/sitemap.xml>) for the product page of each set (`/en/products/{set}`), its card image gallery (`/en/products/{set}/card-image-gallery`) and, for older sets, the gallery article (`/en/news/card-image-gallery/{set}`), matches each page to a Scryfall set by its name, and takes the `og:image` Wizards sets on the page. On a product page that is the set's promo poster, with its logo and text on it; on a gallery it is the set's key art or a piece of its art, without one.

```json
{
  "schema": 1,
  "generated_at": "2026-10-20T09:30:00Z",
  "sets": {
    "dsk": {
      "url": "https://images.ctfassets.net/s5n2t79q9icq/…/dsk_meta.jpg",
      "width": 1200,
      "height": 630,
      "title": "Duskmourn: House of Horror",
      "source": "wizards",
      "page": "https://magic.wizards.com/en/products/duskmourn-house-of-horror"
    }
  }
}
```

- **`sets`** is keyed by the **lower-case Scryfall set code**. It holds the paper expansions, core sets, Masters sets, Commander decks, Un-sets and draft innovation sets released since 1 January 2015, and the upcoming ones Scryfall lists, as soon as Wizards' page for one carries an image. A set with no page, or no usable image, is **not in the file**: fall back to a crop of one of its cards. Do not expect every set to be there (promo and event sets never are, and most Commander decks are not).
- **`url`** is the image itself, on Wizards' CDN (JPEG or PNG), with **`width`** and **`height`** in pixels, read from the file. It is always landscape (at least 1.2 times as wide as tall). A gallery's image (a product's card image gallery or an older set's gallery article) always beats a product page's poster; between galleries the larger image wins, and a product's gallery wins a tie. So a recent set gets the key art of its gallery's header, an older set the 768 by 432 art of its gallery article, and only a set with no gallery image gets its product page's 1200 by 630 poster. Scale it to fill the banner; do not rely on it being 16:9.
- **`title`** is the set's name, from Scryfall. **`source`** is always `"wizards"`. **`page`** is the Wizards page the image was read from, to link to or credit.
- **Updates.** A page is read again only when the sitemap says it changed, so an image changes when Wizards changes the page: an upcoming set's first image can be a placeholder until its art is ready. The file is rebuilt from the pages read so far on every run, so `generated_at` is the run's and says nothing about the art. A run that cannot read the sitemap or Scryfall's sets logs a warning and does not fail; the file stays as last published. Until the first successful run it is a 404.
- **Images are not ours.** They are Wizards' marketing art, served from their CDN; show them as the set's banner and link to `page` where you credit them.

## `sets/products/{code}.json`

The sealed products of one set (boosters, boxes, bundles, Commander decks), so a set page can show what to buy. TCGplayer lists them; TCGCSV (<https://tcgcsv.com>) mirrors its Magic catalog daily as JSON, and each run reads the products and prices of the group matching each Scryfall set. There is one file per set, keyed by the **lower-case Scryfall set code**: `sets/products/fra.json`. About 60 sets have one.

```json
{
  "schema": 1,
  "set": "fra",
  "generated_at": "2026-10-20T09:30:00Z",
  "products": [
    {
      "name": "Reality Fracture - Play Booster Display",
      "kind": "booster-box",
      "image": "https://tcgplayer-cdn.tcgplayer.com/product/692980_400w.jpg",
      "url": "https://www.tcgplayer.com/product/692980/magic-reality-fracture-reality-fracture-play-booster-display",
      "price": 130.94
    }
  ]
}
```

- **Which sets.** Every paper set Scryfall lists as released since 1 January 2023, plus the ones not out yet, that has at least one sealed product with a picture. A set with none has **no file** (the request is a 404): do not expect a file for every set. Promo, token and memorabilia sets are not looked up. A Scryfall set is matched to TCGplayer's group by abbreviation (it is the set's code for most sets) when the two names also read alike, else by name alone, so a few sets do not match (promo packs, Secret Lair); the matching is by `scraper/mtgmeta/setproducts.py`.
- **`name`** is TCGplayer's product name, as written ("Reality Fracture - Play Booster Display"; TCGplayer calls a booster box a display). **`url`** is the product's TCGplayer page.
- **`image`** is the product's picture on TCGplayer's CDN, the 400 pixel wide version (`…_400w.jpg`). A product whose picture the CDN does not serve (some products not out yet) is left out until it does. They are TCGplayer's images; show them for identification and link to `url`.
- **`price`** is TCGplayer's market price in USD, else its mid price, as of TCGCSV's last daily build (about 20:00 UTC), rounded to cents. It is **`null`** when TCGplayer has no price yet, usually for a product not out yet. Do not show it as $0.
- **`kind`** is read from the name by simple patterns, one of:
  - `booster-box`: a box or display of play, draft, set, Jumpstart or plain boosters ("Play Booster Display", "Draft Booster Box")
  - `collector-booster-box`: a Collector Booster box or display
  - `play-booster`: one Play Booster, or a set's plain "Booster Pack"
  - `collector-booster`: one Collector Booster
  - `bundle`: a Bundle, Gift Bundle or any named bundle (the "Secret Lair Bundle" too)
  - `prerelease`: a Prerelease Pack
  - `commander-deck`: a Commander Deck, or a set of them
  - `starter-kit`: a Starter Kit
  - `other`: anything else: **cases** ("Play Booster Display Case"), Scene Boxes, Draft Night, Draft, Set and Jumpstart packs, sample and Omega packs. Filter by `kind` to show the ones you want.
- **Order** is by `kind` in the order above, then by TCGplayer's product id, which is roughly the order TCGplayer added them.
- Cards (products with a number and a rarity), products TCGplayer sells in another language ("(Japanese)") and products with no picture are not in the file.
- **Updates.** The file is rewritten on every run, so `generated_at` is the run's and not the prices'. A set released in the last 120 days or not yet out is read from TCGCSV after each of its builds, an older one only when TCGCSV says its group changed or every 14 days (`state/set-products.json`). A run that cannot read TCGCSV logs a warning and does not fail; the files stay as last published. Until the first successful run they are a 404.

## `sets/mechanics.json`

The mechanics each set introduced, for "New in this set" on a set page. Built from Scryfall: a keyword is new to the set that holds its **earliest paper printing** (by release date) of any card with that keyword in Scryfall's `keywords` array.

```json
{
  "schema": 1,
  "generated_at": "2026-10-20T09:30:00Z",
  "sets": {
    "sos": [
      {
        "keyword": "Prepared",
        "kind": "keyword action",
        "reminder": "While it's prepared, you may cast a copy of its spell. Doing so unprepares it.",
        "rules": "",
        "example_oracle_ids": ["6cb8b8c4-0674-4f14-9d89-010969fbb80e", "58b0c737-0a84-4f9a-b3b7-300c5de43874", "93056597-b964-421f-be2f-e92abef1c2a4"],
        "first_set": "sos"
      }
    ],
    "tdm": [
      {
        "keyword": "Mobilize",
        "kind": "keyword ability",
        "reminder": "Whenever this creature attacks, create two tapped and attacking 1/1 red Warrior creature tokens. Sacrifice them at the beginning of the next end step.",
        "rules": "Mobilize is a triggered ability. “Mobilize N” means “Whenever this creature attacks, create N 1/1 red Warrior creature tokens. Those tokens enter tapped and attacking. Sacrifice them at the beginning of the next end step.”",
        "example_oracle_ids": ["b12cbda1-ac09-49eb-96b3-a4df27bc37ea", "158d0272-a850-4399-8afa-d0caa143c3cb", "449db6bf-d766-4d09-a7bd-9c45b3d4c4c3"],
        "first_set": "tdm"
      }
    ],
    "m10": []
  }
}
```

- **`sets`** is keyed by the **lower-case Scryfall set code** and holds an entry (an empty array when the set introduced nothing) for every set that can introduce a mechanic: paper expansions, core sets, Masters, Commander decks, draft innovation, Un-sets and the like, about 310. Promo, token, memorabilia, Secret Lair and digital-only sets are not in it, and their printings do not count (a prerelease promo is out a week before its set).
- **A tie.** A set and its Commander decks come out on one day. The mechanic goes to the set, and the Commander deck only when it is the only one with it (then the set with more cards with it, then the code). Each mechanic is in exactly one set, and **`first_set`** repeats that set's code.
- **What is left out.** The evergreen keywords (flying, trample, flash, ward, … and the evergreen actions such as scry and fight), a keyword first printed before 1 January 1999, and variants of one mechanic, which count as it: every `…cycling` is cycling, every landwalk is landwalk, multikicker is kicker, megamorph is morph, nightbound is daybound. Names Scryfall puts in `keywords` that are not keywords (a card's own named abilities) are not in it: a word counts only if the Comprehensive Rules or one of Scryfall's keyword ability, keyword action or ability word catalogs lists it. Scryfall's data decides both the name and the date, so Secrets of Strixhaven's mechanic is **`Prepared`** here, and a keyword Scryfall tags only on a later card (or on a token) is dated by that card.
- **`keyword`** is the name as Scryfall's catalog (else the rules) writes it. **`kind`** is `keyword ability` (rule 702), `keyword action` (rule 701) or `ability word` (rule 207.2c) from `rules/keywords.json`; for a word the rules do not list yet (the Comprehensive Rules are published a few times a year, a new set's mechanics are in Scryfall first), it is the Scryfall catalog it is in.
- **`rules`** is the keyword's rules from `rules/keywords.json` (its subrules joined by a newline); for an ability word it is rule 207.2c's general text, as an ability word has no rules of its own. It is **`""`** for a mechanic the Comprehensive Rules do not list yet.
- **`reminder`** is the reminder text in parentheses from one of the examples' oracle text (without the parentheses), as printed on that card, so it can name that card's number ("Mobilize 2 … create two"). It is **`""`** when no example has one, always for an ability word.
- **`example_oracle_ids`** are up to three cards of the set with the keyword, the most played first: lowest EDHREC rank, then the rarest, then by name. They are the `oracle_id` of `cards/{slug}.json`.
- **Order** in a set is the mechanics with the most cards in the set first, then by name.
- **Updates.** The file is rewritten on every run from Scryfall's every-printing file (the movers' download, read a second time), its catalogs, and `rules/keywords.json`: this run's copy when the rules changed, else the published one. A run that cannot read them logs a warning and does not fail; the file stays as last published. Until the first successful run it is a 404.

## Lore: `lore/app/…`

The Magic story, keyed to cards and sets, for "View lore" on a card and key characters on a set. Built by `python -m mtglore app` in `lore/` from the lore index (see [`lore/README.md`](../lore/README.md)) and Scryfall's card catalog, and uploaded by the `Lore site` workflow. The same index drives the web preview at `lore/index.html`. Ids are the index's entity ids (`jace-beleren`, `dominaria`), stable across rebuilds unless an entity is renamed.

### `lore/app/cards.json`

```json
{"schema": 1, "generated_at": "2026-10-20T01:43:18Z",
 "cards": {"00037840-6089-42ec-8c5c-281f9f474504": ["nissa-revane"]}}
```

A card's Scryfall `oracle_id` to the entities it depicts, usually one. A card missing from the map has no lore page; don't show "View lore". Only confident matches are listed:

- legendary creatures and planeswalkers, when the card's name (or the part before its comma, or a planeswalker's type) agrees word for word with the entity's own name: "Jace, the Mind Sculptor" and "Jace, Wielder of Mysteries" → `jace-beleren`, "Dragonlord Kolaghan" → `kolaghan`;
- lands named for a place or plane: "Kor Haven" → `kor-haven`;
- planes (Planechase): "Llanowar" (`Plane — Dominaria`) → `dominaria`, `llanowar`;
- legendary artifacts named for a story artifact: "Weatherlight" → `weatherlight`.

Two entities sharing a name about equally, or a card printed only in Universes Beyond and other crossover sets, give no match.

### `lore/app/sets.json`

```json
{"schema": 1, "generated_at": "…",
 "sets": {"dom": [{"id": "liliana-vess", "name": "Liliana Vess", "type": "planeswalker", "role": "main", "mentions": 122}, …]},
 "summaries": {"dom": "Dominaria's story follows the Weatherlight's new crew as …"}}
```

`sets` maps each story set (expansions, core sets, draft innovation; not reprint editions or crossovers), by Scryfall set code, to at most 12 entities, most important first. Each set's value stays an array, so readers of the first shape keep working. `type` is `character`, `planeswalker`, `plane`, `location`, `faction` or `artifact`. `role` is `main` for the four characters the set is most about and its leading place, else `supporting`. `mentions` counts the facts linking the entity to the set. A fact belongs to a set when it comes from the set's flavor text, from a wiki section tagged with the set, from a story whose storyline is named for the set, or else from a story published within about six weeks before to four months after the set's release.

`summaries` maps a set code to two or three sentences of that set's story, for the set's About tab. A set without a written summary is missing from the map; show nothing then.

### `lore/app/entities.json`

```json
{"schema": 1, "generated_at": "…", "entities": {"teferi": {
  "name": "Teferi", "type": "planeswalker",
  "summary": "Teferi is a centuries-old time-magic mage and planeswalker of Zhalfir, …",
  "portrait_oracle_id": "5f0fa785-37ab-46a8-9ec0-6f8b29576d93",
  "sets": ["mir", "vis", "usg", "dom", "war", …]}}}
```

Every entity with a page: those with a written bio, those a card depicts, and those key to a set. `portrait_oracle_id` is the card that shows them best (one named exactly for them, else their latest planeswalker card, else their latest card), or `null`. `sets` are the story sets they're key to or first printed in, by release date.

### `lore/app/entities/{id}.md`

One entity's page in [playgraph](https://github.com/missingems/playgraph) primer markdown (`feat/primers-api`): front matter, `##` sections, `[[Card Name]]` links and a `:::cards` block. It is prose to read, not a list of facts: who they are, then their story set by set. Every file parses with playgraph's `exportPrimer` without diagnostics.

```markdown
---
id: teferi
name: Teferi
type: planeswalker
title: Teferi
planes: [Zhalfir, Dominaria]
updated: 2026-10-20
credit: "Parts adapted from MTG Wiki (https://mtg.wiki) by MTG Wiki contributors, CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)."
---

## Who they are

Teferi is a time-manipulating mage and planeswalker from Zhalfir, … He married Subira and they had a daughter, Niambi; …

As of the latest material he is alive in Zhalfir, …

## Story

### Mirage

Teferi unified Zhalfir's houses into guilds, but Kaervek's war reached his isle. …

### Dominaria

Teferi, now mortal, is living with his family when Jhoira asks him to join the Weatherlight. …

## Cards

:::cards
[[Teferi, Hero of Dominaria]] Dominaria, 2018
:::
```

- `credit` (front matter): present when any of the page's text comes from MTG Wiki, which is CC BY-NC-SA 4.0. Show it, for example as a small footnote, whenever the page is shown. A page told only from official sources has no `credit`.
- `## Who they are` (`## What it is` for places, factions and artifacts): the written bio, then a paragraph on where things stand; or the index's description.
- `## Story`: one `###` per set (else storyline, era or year) in story order, each with one short paragraph. For the sets the entity is key to, the paragraph is written as a story (`lore/data/narratives`); for the others, it tells up to four of its events from that set, chosen the same way as the timeline's.
- `## Cards`: the cards that depict the entity, oldest first. `[[Card Name]]` also appears in the prose where it reads naturally, only for the entity's own cards.
- The page carries no links or source list. Which line each sentence rests on stays in the lore index (`lore/data/narratives`, `lore/data/bios` and the index's citations), and the web preview shows it.

### `lore/app/sets/{code}/{id}.md`

What happened to one key entity in one set: open it first when someone taps an entity on a set page, then show the entity's full page below it. There is one for every entity listed under the set in `sets.json`.

```markdown
---
id: teferi
set: dom
name: Teferi
title: Teferi in Dominaria
---

## In Dominaria

Teferi, now mortal, is living with his family when Jhoira asks him to join the Weatherlight. …

## Timeline

- Teferi explains he created a time rift to phase Zhalfir out of Dominaria to protect it from the Phyrexians.
- Joining Jhoira, Teferi agrees to save the world again.
```

- `## In {Set Name}`: the same paragraph as the set's section in the entity's page. Where the set has none of the entity's events and the entity is only on its cards, it is what the cards show of them.
- `## Timeline`: at most 10 of the entity's events in that set, one short line each, in story order. When there are more, it keeps the story's own events before the wiki's, the major ones first, spread from the first to the last so the set's ending stays in. It is left out when there are none.
- `credit`: as for the entity pages.

## Who they are

Teferi is a centuries-old time-magic mage … ([story](https://magic.wizards.com/…#:~:text=…))

## Story

### Mirage

- Teferi phases out Zhalfir … ([MTG Wiki](https://mtg.wiki/page/Teferi#:~:text=…))

## Relationships

- Teferi mentor of Jhoira: … ([story](…))

## Cards

:::cards
[[Teferi, Hero of Dominaria]] Dominaria, 2018
:::

## Sources

- "…". Magic Story, Wizards of the Coast, 10 Apr 2018.

From MTG Wiki, by MTG Wiki contributors under CC BY-NC-SA 4.0 (…):

- "Teferi", section "Biography". MTG Wiki contributors, CC BY-NC-SA 4.0.
```

- `## Who they are` (`## What it is` for places, factions and artifacts): the written bio and where things stand, or the index's description.
- `## Story`: events in story order under one `###` per set (else storyline, era or year); a long life keeps its turning points, at most 80 lines.
- `## Relationships`: at most 30, official sources first.
- Every fact ends with a link to the exact line it rests on. The link says `story` (Magic Story, the old wizards.com columns), `card` (flavor text) or `MTG Wiki` (fan-written). Keep wiki-sourced lines credited: `## Sources` lists the MTG Wiki pages under their CC BY-NC-SA 4.0 credit, apart from the official ones.
