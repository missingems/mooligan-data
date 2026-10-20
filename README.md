# mooligan-data

Scrapes MTGGoldfish's metagame, tournament results and decklists once a day, and publishes them as static JSON at **`https://data.mooligan.com`**, a Cloudflare R2 bucket. The mobile app reads them. There's no server or database.

```
GitHub Actions (14:00 UTC)
  └─ download previous snapshots from R2 → scrape what's new → upload to R2
                                                                   │
                            data.mooligan.com (Cloudflare CDN) ◀───┘
                              └─ the app
```

| Path | What it holds |
| --- | --- |
| `scraper/` | Python SeleniumBase (UC mode) scraper, and the snapshot store it publishes |
| `generators/` | Swift generators for the card catalog: image feature prints, pull odds, price catalog (from the MTGImageHash repository; see `generators/README.md`) |
| `docs/data-format.md` | **The published files and their fields.** This is what the app codes against |
| [MTGMetaKit](https://github.com/missingems/MTGMetaKit) | Swift package with models and a client for the feed (separate repository) |
| `ops/` | The scrape and catalog jobs as scripts (`scrape.sh`, `catalog.sh`), which the workflows call and which run the same on a Mac |
| `.github/workflows/scrape.yml` | The scheduled scrape and upload |
| `.github/workflows/catalog.yml` | The card catalog build on macOS (Vision), publishing under `catalog/` |
| `.github/workflows/r2-check.yml` | Manual check that the R2 token, bucket and domain work together |

## Published data

See [docs/data-format.md](docs/data-format.md). In short:

- `index.json` gives each format's snapshot with a hash, so clients download only when something changed.
- `explore.json` is a small summary for a landing screen: the top archetypes, the colour shares of the whole metagame and the latest events of the six main formats, built from the snapshots.
- `archetypes/{id}.json` and `events/{id}.json` are one level below `explore.json`: an archetype's shares and recent decks, and an event's whole standings, each row linking to a `decks/{id}.json`.
- `snapshots/{format}.json` holds the metagame, the last 30 days of events, and every archetype's results.
- `decks/{id}.json` holds one decklist per file, cached for good.
- `cards/{slug}.json` says where a card is played, across every format, with links to decks, plus its Commander usage from EDHREC.
- `popular-cards/{format}.json` ranks the cards a format's dated decks play over the last 7, 14 and 30 days, mainboard by kind of card and sideboard apart, basics left out, with each card's trend.
- `breakouts/{format}.json` lists the cards new to a format's metagame: played by the last 7 days' decks and barely by the 23 days before, with their top 8s, wins and every recent deck that plays them.
- `movers/{format}.json` lists the cards whose price rose or fell most over the last day, week and month, among the cards legal in a format, from the catalog's price history (a card costs its cheapest paper printing in the regular finish, compared like for like: a printing priced for the first time is no move).
- `today.json` is one response for Explore's Today widgets: up to three breakouts (the strongest by decks and top 8s over the formats, `new` only breaking a tie) with the decks that play them, the day's biggest price mover and loser from `movers/all.json` with their price history, the uprising EDH commander (the one whose deck count on EDHREC rose most since EDHREC was last asked; EDHREC's data, used with their permission, so an app must credit them), and one preview: a printing Scryfall added since the last run from a set not released yet, or none on a day it added no such printing.
- `previews.json` lists the printings Scryfall added in the last 7 days from sets not released yet (`window_days`, `count`, `cards`), ordered by the day each was first seen; it is the list behind Explore's "View N more", and its format is in `docs/data-format.md`.
- `rules/keywords.json` holds what Magic's Comprehensive Rules say about each keyword action and keyword ability, and the ability words, read from the text file Wizards links on magic.wizards.com/en/rules. Every run reads it, but the file changes only when Wizards publishes new rules.
- `sets/art.json` holds Wizards' official art for each set, keyed by Scryfall set code, for a set page's hero banner. A set Wizards has no art for is left out.
- `sets/products/{code}.json` holds the sealed products (boosters, boxes, bundles, decks) of one set released since 2023 or yet to come, keyed by Scryfall set code, with TCGplayer's picture, link and price, read from TCGCSV. A set with no sealed products has no file.
- `sets/mechanics.json` holds the keyword abilities, keyword actions and ability words each set introduced, by Scryfall set code, with the rules, reminder text and example cards.
- `explore-manifest.json` lists the SHA-256 of each Explore file (`explore.json`, `today.json`, `previews.json`, `edh/top.json`, `rules/keywords.json`, `popular-cards/{format}.json` and `breakouts/{format}.json`), so the app fetches it first and downloads only the files whose hash differs. A file a run does not rewrite keeps its entry from the last manifest, which is kept in `state/explore-manifest.json`.

Card details come from Scryfall's API, not from this pipeline. Scryfall's bulk file is read once a run for card names and oracle ids, and for whether a card is a land, its price and its mana value, which pick the preview cards of results outside a tracked archetype.

## How a run works

`.github/workflows/scrape.yml` runs once a day, scheduled for 14:00 UTC after the card catalog's 10:17 build, so the price movers read that day's prices. GitHub's scheduler has been starting it hours late (between 17:52 and 19:24 UTC on 30 September to 3 October 2026), and the files land about an hour after it starts, so read a file's own `generated_at`. It can be started by hand from the Actions tab, though a change is better tried on a Mac first (see [Running locally](#running-locally)), since this private repository's Actions minutes are paid for. The workflow runs `ops/scrape.sh` with `PUBLISH=1`. Once a day matches its sources: MTGJSON builds its prices daily, Scryfall's bulk files and prices change about daily, and EDHREC's numbers about once a day. MTGGoldfish adds results through the day, so a day's later events show up the next day.

1. **Download.** It downloads `snapshots/` and `state/` from R2. They are the previous run's output, and the only state the scraper keeps.
2. **Scrape.** `python -m mtgmeta work` opens MTGGoldfish in SeleniumBase UC mode, with Chrome inside Xvfb on the runner. For each format it:
   - reads the metagame page (30-day window);
   - reads each archetype's page for its featured deck, then `/archetype/<id>/decks` for its results. Results merge with the previous snapshot, so an archetype stops at the first page with nothing new;
   - reads every event of the window from MTGGoldfish's tournament search (20 a page, `MAX_SEARCH_PAGES` at most), plus the archetype lists' mentions for multi-format events, and reads up to `MAX_NEW_EVENTS` not yet stored, newest first. Each event is classed by name and source (Pro Tour, Regional Championship, RCQ, Store Championship, MTGO Challenge or League, other; a League is MTGO's only when its results came from mtgo.com), and each result keeps the colour pips MTGGoldfish shows beside its deck;
   - picks the new decklists to download, up to `MAX_NEW_DECKS` per format. A deck MTGGoldfish has deleted redirects to its metagame page; those ids go in `state/missing-deck-ids.json` so later runs skip them. Featured decks come first, then the newest.

   Only the metagame and tournaments-list pages are real browser visits. Everything else is fetched with `fetch()` from inside the open page, `CONCURRENCY` requests at a time. Those requests reuse the page's Cloudflare clearance and skip rendering, so a batch of 6 takes about a second, where a visit takes about 7. For these pages, a refused batch (403 or a challenge page, as happens straight after the first page load) makes the browser reload a page to renew the clearance and retry.

   The decklists are downloaded after every format's pages, and slowly, like a reader. A run once downloaded 501 decks in two minutes, and the next run had every download refused. So the formats take turns, newest decks first within each, and every few decks follow a real visit to the event or archetype page they come from. They download two at a time, with random gaps (a median of `DECK_DELAY` seconds, and now and then 20 to 60), at most `DECKS_PER_RUN` decks a run and `DECK_MINUTES` minutes. When a download is refused, it waits 30 seconds, then 60, and visits the page again before retrying. After 3 refusals in a row it stops downloading decks for the run, logs one line with the HTTP status and headers, and leaves the rest for the next run.
3. **Publish.** `SnapshotStore.finish()` builds a page per card from every decklist in the window (reading back from `data.mooligan.com` the ones this run didn't download) (which archetypes play it, in how many decks), drops anything older than `HISTORY_DAYS`, and drops events MTGGoldfish imported twice (identical standings under a second id, remembered in `state/duplicate-event-ids.json` so later runs skip them), then merges the archetypes whose decklists show they play one deck under the biggest of them (see *Merged archetypes* in `docs/data-format.md`; `python -m mtgmeta clusters DIR --format modern --days 7` prints what would merge, writing nothing), then writes the snapshots, `explore.json`, a page per archetype in the metagame and per event, the deck id list and `index.json`. The snapshots as scraped, unmerged, go in `state/snapshots/`, which the next run starts from. `ops/scrape.sh` uploads decks first and `index.json` last, so the index never points at a file that isn't there yet. `explore-manifest.json` goes up just before it, after the Explore files it lists and the state, so it never names a hash a file doesn't have yet.

One failed page doesn't stop the run. Whatever was collected is still published, and the job is then marked failed so the errors show up in the Actions tab. Two runs never overlap.

Blocked deck downloads are different: they are a warning, the run passes, and the decks wait for the next run. The run fails when the downloads are blocked two runs in a row. The count is in `state/deck-downloads.json`.

A first run reads a month of history for every archetype. For Vintage (23 archetypes, 400 decklists) that took 4 minutes; Modern has about three times as many archetypes. Later runs usually read one page per archetype.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FORMATS` | the nine below | Formats to scrape: `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful`, `duel_commander` |
| `META_DAYS` | `30,14,7` in `ops/scrape.sh` | Metagame windows to publish |
| `EVENTS_PER_FORMAT` | `10` | Events taken from the tournaments list, which never shows more than 10 |
| `RECHECK_DAYS` | `7` | Events dated within this many days of the run are read again every run, stored or not |
| `MAX_NEW_EVENTS` | `150` | Events not yet stored read per format per run |
| `MAX_SEARCH_PAGES` | `25` | Tournament-search pages read per format, 20 events each |
| `HISTORY_DAYS` | `30` | How far back events and archetype results go |
| `ARCHETYPE_DECKS` | `100` | Archetypes per format, most played first, whose results are kept |
| `MAX_ARCHETYPE_PAGES` | `20` | Deck-list pages per archetype per run |
| `MAX_NEW_DECKS` | `400`, `1500` in `ops/scrape.sh` | New decklists per format per run. `DECKS_PER_RUN` caps the total |
| `DECKS_PER_RUN` | `800` | New decklists per run, all formats together |
| `DECK_RESOLVE_PER_RUN` | `300` | Published decklists read again per run to name entries the card catalog could not name when they were saved; each deck is tried 3 times |
| `DECK_CONCURRENCY` | `2` | Decklists downloaded at once |
| `DECK_DELAY` | `2` | Median seconds between decklist batches, randomised, with a long pause now and then |
| `DECK_MINUTES` | `40` | Minutes the decklist downloads may take, all formats together |
| `CONCURRENCY` | `6` | Requests fetched at once from inside the page, for the pages other than decklists |
| `REQUEST_DELAY` | `1` in `ops/scrape.sh` | Base seconds between those batches, plus up to 50% random extra |
| `LOCALIZE` | `1`, `0` with `QUICK=1` | Add the `localized` map (printed names and pictures in ja, fr, it, es and de) to `today.json` and `explore.json`. It streams Scryfall's every-printing file, about 400 MB gzipped, so it adds a minute or two to a run; `0` skips it |
| `LOCALIZE_ALL_CARDS_URL` | Scryfall's `all_cards` bulk file | Read another file instead; a `file://` URL works |
| `KEYWORD_RULES` | `1` | `0` skips `rules/keywords.json`, which reads the Comprehensive Rules from Wizards' site |
| `SET_ART` | `1` | `0` skips `sets/art.json`, which reads each set's art from Wizards' site |
| `SET_ART_DELAY` | `0.5` | Seconds between requests to Wizards' site for `sets/art.json` |
| `SET_PRODUCTS` | `1` | `0` skips `sets/products/{code}.json`, which reads each recent set's sealed products from TCGCSV |
| `SET_PRODUCTS_DELAY` | `0.25` | Seconds between requests to TCGCSV (it asks for at least 0.1) |
| `SET_MECHANICS` | `1` | `0` skips `sets/mechanics.json`, which reads Scryfall's every-printing file (about 80 MB gzipped) for the mechanics each set introduced |

## Setup

- **R2:** the bucket is `mtg-meta-data`, with custom domain `data.mooligan.com`. The app is native, so the bucket needs no CORS rule.
- **GitHub secrets:** `R2_ACCOUNT_ID`, and `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` from an account API token with Object Read & Write on that bucket only.

## Running locally

```bash
cd scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
FORMATS=modern ARCHETYPE_DECKS=5 HISTORY_DAYS=3 MAX_NEW_DECKS=5 .venv/bin/python -m mtgmeta work
```

A local run writes into `scraper/work/` and publishes nothing. To run the whole job the way the workflow does, use `ops/scrape.sh` below.

### The whole job on a Mac, for development

`ops/scrape.sh` and `ops/catalog.sh` are the whole jobs. The workflows call them with `PUBLISH=1`; run them on the Mac to try a change without spending Actions minutes. Locally they publish nothing unless told to: everything lands in `scraper/work/` (or `generators/work/catalog/`) to look at. Each run starts by emptying that folder, as a fresh Actions checkout would, so copy a run's output elsewhere first to compare it with the next.

One-time setup (the scripts also create and repair the venv themselves):

```bash
mise install python@3.12
"$(mise where python@3.12)/bin/python3.12" -m venv scraper/.venv
scraper/.venv/bin/pip install -r scraper/requirements-dev.txt -r ops/requirements.txt
```

No keys are needed. With none, a run starts from the live data: it downloads `snapshots/` and `state/` read-only from `https://data.mooligan.com`, as the workflow syncs them from R2. Chrome opens a window on the Mac (UC mode runs headed; Linux uses Xvfb instead).

```bash
QUICK=1 ops/scrape.sh                                   # modern only, few decks, no EDHREC, locator, premier or movers
QUICK=1 FORMATS=pauper,vintage MAX_NEW_DECKS=50 ops/scrape.sh  # any setting overrides the preset
QUICK=1 MOVERS=1 ops/scrape.sh                          # with price movers, today.json's preview and previews.json (downloads Scryfall's bulk file)
QUICK=1 LOCALIZE=1 ops/scrape.sh                        # with the localized names (downloads Scryfall's 400 MB all_cards file)
ops/scrape.sh                                           # the full daily run, without the upload
SYNC=none QUICK=1 ops/scrape.sh                         # from nothing, like a first run
```

`QUICK=1` sets `FORMATS=modern`, `MAX_NEW_DECKS=20`, `MAX_NEW_EVENTS=10`, `MAX_SEARCH_PAGES=2`, `EDHREC_CARDS_PER_RUN=0`, `EDHREC_COMMANDERS_PER_RUN=0`, `LOCATOR_PLACES=` (none), `PREMIER_SCHEDULE=0`, `MOVERS=0` and `LOCALIZE=0`, each only when not set already. `SYNC` picks where a run starts from: `auto` (the default: R2 when keys are set, else HTTPS), `r2`, `https` or `none`. The other variables are the scraper's, in the table above.

`ops/backfill_oracle_ids.py DIR` is a one-off: it reads the published decks listed in `DIR/state/deck-ids.json` (from `DATA_URL`) and adds those with an entry lacking an `oracle_id` to `DIR/state/unresolved-deck-ids.json`, for the next run to name. Run it against a work dir freshly populated from the live state, so the merge keeps the tries already recorded, then upload the result to R2 before the next scheduled run, because that run syncs `state/` down from R2 and would overwrite a file that only exists locally:

```bash
python3 ops/fetch_live.py DIR
scraper/.venv/bin/python ops/backfill_oracle_ids.py DIR
aws s3 cp DIR/state/unresolved-deck-ids.json "s3://$R2_BUCKET/state/unresolved-deck-ids.json" \
  --endpoint-url "$R2_ENDPOINT" --content-type application/json --cache-control "no-cache"
```

**In the app.** A Debug build reads the Explore files from a folder instead of the feed when launched with `-exploreFixture <path to explore.json>`; the folder must hold the files where the feed does, as `scraper/work/` does after a run. The simulator reads the Mac's files, so give the absolute path. In Xcode, add it under the scheme's Run > Arguments Passed On Launch, or launch an installed build with:

```bash
xcrun simctl launch booted com.missingems.mooligan -exploreFixture "$PWD/scraper/work/explore.json"
```

The fixture never falls back to the feed, so a file the run did not write shows as missing. `explore.json` covers every format, from the downloaded snapshots, but a `QUICK` run writes the archetype, event, popular-card and breakout pages of its own formats only, `decks/` holds only the decks it downloaded (the rest stay on R2), and without movers `today.json` has no price cards. Run the formats you are looking at, and `MOVERS=1` for Today.

The catalog runs the same way and needs no keys either; the generators read the published catalog from `data.mooligan.com` as their previous state. `MTG_LIMIT=300` caps the faces the indexer processes:

```bash
MTG_LIMIT=300 ops/catalog.sh
```

**Publishing from a Mac** is the exception, for when Actions cannot run. Put the three R2 keys in `~/.config/mooligan-data/env` (mode 600; `ops/env.example` is the template; variables already set in the environment win over the file) and set `PUBLISH=1`:

```bash
mkdir -p ~/.config/mooligan-data && cp ops/env.example ~/.config/mooligan-data/env && chmod 600 ~/.config/mooligan-data/env
PUBLISH=1 ops/scrape.sh
```

A publishing run always starts from R2 itself, never from the HTTPS copy. Nothing stops it overlapping a scheduled workflow, so don't run it near 10:17 or 14:00 UTC, and run the catalog before the scrape.

## Card catalog

`generators/` holds the three Swift programs that used to live in the MTGImageHash repository, unchanged: `ImageHashIndexer` (Vision feature prints of every card face, incremental patches over a master), `PullOdds` (MTGJSON booster odds) and `Prices` (the MTGJSON price catalog). `.github/workflows/catalog.yml` runs them once a day at 10:17 UTC on a macOS runner, through `ops/catalog.sh`, and publishes to `catalog/` on R2, so the app's base URL becomes `https://data.mooligan.com/catalog`. The file layout is documented in `generators/README.md`. Run the workflow once with `seed_from_pages` to copy the current GitHub Pages output into R2 first, so the indexer's first run is incremental. The MTGImageHash workflow keeps GitHub Pages current until the app has switched.

## Localized names

After `today.json` is built, each run adds a `localized` map to it and to `explore.json`: the printed name and picture of each card they show, in Japanese, French, Italian, Spanish and German (`today.json` also gets the type line and rules text). It reads Scryfall's every-printing file (`all_cards`, about 400 MB gzipped, 2.5 to 3 GB unpacked) once, as a stream, so a run takes one to two minutes longer and holds under 100 MB; `LOCALIZE=0` skips it. A run saves the cards it found, with their text, to `state/localized.json.gz` (tens of KB). When Scryfall's file cannot be read, the run fills the map from that file instead and logs a warning; with no saved file the two files go out without `localized`, with a warning too. Neither fails the run. See `docs/data-format.md`.

## Price movers

Each run also builds `movers/{format}.json` from `catalog/prices/history.bin.gz`, which the card catalog workflow publishes, and Scryfall's default-cards bulk file, which says which printings are one card and where it is legal. Set `MOVERS=0` to skip it, or `MOVERS_PRICES_URL` to read another price history.

The same read of the default-cards file finds the preview in `today.json`. Each run saves the id of every printing in it to `state/printing-ids.json.gz`, a sorted, gzipped JSON array of about 2.4 MB, and a printing whose id the last run did not save is new. Ids, because a printing's Scryfall id never changes; a count and hash per set would say that a set changed but not which of its printings are new. A first run only saves the ids, so it has no preview. The same read also keeps `state/printing-first-seen.json.gz` (id to the day a run first saw an eligible printing, pruned after 30 days), from which `previews.json` lists the unreleased printings first seen in the last 7 days; the first run without that file counts every existing printing as old, except unreleased ones Scryfall says were previewed in the last 7 days. A run with `MOVERS=0`, or one that could not read the file to its end, has none either and leaves the saved ids as they were, so the next run still finds the printings it missed.

## Keyword rules

Each run also reads the Comprehensive Rules for `rules/keywords.json`: it finds the link to the text file on <https://magic.wizards.com/en/rules> (the file name carries its date, so the link is never hard-coded), downloads it, and keeps rule 701 (keyword actions), rule 702 (keyword abilities) and the ability words of rule 207.2c. The state keeps a fingerprint of what was published (`state/rules-keywords.json`), and a run that finds the same rules writes nothing, so the file, its hash in the manifest and its ETag stay as they were until Wizards publishes new rules. When Wizards' site cannot be read, or its page or text has changed shape, the run logs a warning and carries on, and the published file stays as it was. See `scraper/mtgmeta/rules.py` and `docs/data-format.md`.

## Set art

`sets/art.json` is read from Wizards' sitemap: each set's product page and card image gallery are matched to a Scryfall set by name, and their `og:image` is kept with its measured size (see `scraper/mtgmeta/setart.py`). Requests are 0.5 seconds apart with a descriptive User-Agent. The pages read are cached in `state/set-art.json` by URL and the sitemap's `lastmod`, so after the first run (about 300 requests) a run reads only the pages that changed. It can be run alone with `python -m mtgmeta set-art DIR`. When Wizards' site cannot be read the run logs a warning and carries on, and the published file stays as it was. See `docs/data-format.md`.

## Set products

`sets/products/{code}.json` is read from TCGCSV (<https://tcgcsv.com>), which mirrors TCGplayer's Magic catalog once a day. Each group (TCGplayer's set) is matched to a Scryfall set released since 2023, or not yet out, by abbreviation and name, and its products with no card number and rarity are the sealed ones (see `scraper/mtgmeta/setproducts.py`). Following TCGCSV's usage guidelines, requests carry a custom User-Agent and are 0.25 seconds apart, and a run reads `last-updated.txt` first. A first run makes about 150 requests (a group list, then products and prices for each of about 75 groups). The groups read are kept in `state/set-products.json` with TCGCSV's build time and the group's own `modifiedOn`: a set out in the last 120 days or yet to come is read again after each build (its prices move and its products are added), an older one only when its `modifiedOn` changed or its copy is 14 days old, so a normal run makes a few dozen requests. It can be run alone with `python -m mtgmeta set-products DIR`. When TCGCSV cannot be read the run logs a warning and carries on, and the published files stay as they were. See `docs/data-format.md`.

## Set mechanics

`sets/mechanics.json` is built from Scryfall's every-printing file (`default_cards`, which the movers also read; it is a second download of about 80 MB gzipped), its three catalogs of keyword abilities, keyword actions and ability words, and `rules/keywords.json`: this run's copy when the rules changed, else the published one at `DATA_URL`. A keyword is new to the set holding its earliest paper printing (see `scraper/mtgmeta/setmechanics.py`). It can be run alone with `python -m mtgmeta set-mechanics DIR`. When Scryfall or the rules cannot be read the run logs a warning and carries on, and the published file stays as it was. See `docs/data-format.md`.

## Premier play calendar

`premier/schedule.json` is magic.gg's schedule of Pro Tours, Regional Championships, Spotlight Series, Worlds and CommandFests, read once a run. The page embeds its calendar as Nuxt state, which the scraper evaluates with Node. Each event gets a `region` from its name so an app can show the user's own Regional Championship.

## Wizards' event locator

`LOCATOR_PLACES` (semicolon-separated) names places whose upcoming in-store events are read from Wizards' Store & Event Locator and published as `locator/<place>.json`: the next `LOCATOR_DAYS` days within `LOCATOR_DISTANCE_MILES`, one page of 100 events per request, `LOCATOR_DELAY` seconds apart. Note that Wizards' Terms of Use bar automated collection from their sites; this is run at Jun's own decision, kept to a few requests a run, and links every event back to the locator and the store.

## EDHREC

Commander usage on each card page comes from EDHREC, used with their permission. A run refreshes `EDHREC_CARDS_PER_RUN` cards (800 by default, 1600 in `ops/scrape.sh`) and `EDHREC_COMMANDERS_PER_RUN` commanders (150, 300 in `ops/scrape.sh`, so a daily run reads as many as two runs a day did), at `EDHREC_DELAY` seconds apart, longest unchecked first, so the set comes round over days and the rate stays low. A commander page carries what that commander's decks play and its average decklist, so a reader never has to leave for the numbers. Their numbers move about once a day. Anything showing this data must credit EDHREC and link back to the `url` on each entry.

## Caveats

- MTGGoldfish sits behind Cloudflare, and its markup can change. The parsers raise `ParseError` rather than write empty data, so a layout change shows up as a failed run.
- Cloudflare challenges an address that scrapes a lot. GitHub's runners have got through so far. If runs start failing with "Blocked on …", lower `CONCURRENCY` or raise `REQUEST_DELAY`. If decklists are refused, the log says with which HTTP status; raise `DECK_DELAY`, lower `DECK_CONCURRENCY` or `DECKS_PER_RUN`.
- GitHub disables scheduled workflows in a public repo after 60 days without commits. If the schedule stops, re-enable it from the Actions tab.
- Scraping may conflict with MTGGoldfish's terms of use. Keep the rate low, and don't redistribute the data commercially.
