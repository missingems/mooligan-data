# mooligan-data

Scrapes the metagame, tournament results and decklists of Magic Online (from mtgo.com) and paper events (from MTGTop8) once a day, and publishes them as static JSON at **`https://data.mooligan.com`**, a Cloudflare R2 bucket. The mobile app reads them. There's no server or database.

```
GitHub Actions (14:00 UTC)
  └─ download previous snapshots from R2 → scrape what's new → upload to R2
                                                                   │
                            data.mooligan.com (Cloudflare CDN) ◀───┘
                              └─ the app
```

| Path | What it holds |
| --- | --- |
| `scraper/` | Python scraper (plain HTTP to mtgo.com and MTGTop8, no browser), and the snapshot store it publishes |
| `generators/` | Swift generators for the card catalog: image feature prints, pull odds, price catalog (from the MTGImageHash repository; see `generators/README.md`) |
| `docs/data-format.md` | **The published files and their fields.** This is what the app codes against |
| [MTGMetaKit](https://github.com/missingems/MTGMetaKit) | Swift package with models and a client for the feed (separate repository) |
| `ops/` | The scrape, catalog and primer jobs as scripts (`scrape.sh`, `catalog.sh`, `primers.sh`), which the workflows call and which run the same on a Mac |
| `.github/workflows/scrape.yml` | The scheduled scrape and upload |
| `.github/workflows/guides.yml` | After each scrape, Claude writes the archetype primers that are missing or changed and publishes them to api.mooligan.com (see [Archetype primers](#archetype-primers)) |
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
- `today.json` is one response for Explore's Today widgets: up to six breakouts (the strongest by decks and top 8s over the formats, `new` only breaking a tie) with the decks that play them, the day's biggest price mover and loser from `movers/all.json` with their price history, the uprising EDH commander (the one whose deck count on EDHREC rose most since EDHREC was last asked; EDHREC's data, used with their permission, so an app must credit them), and one preview: a printing Scryfall added since the last run from a set not released yet, or none on a day it added no such printing.
- `previews.json` lists the printings Scryfall added in the last 7 days from sets not released yet (`window_days`, `count`, `cards`), ordered by the day each was first seen; it is the list behind Explore's "View N more", and its format is in `docs/data-format.md`.
- `rules/keywords.json` holds what Magic's Comprehensive Rules say about each keyword action and keyword ability, and the ability words, read from the text file Wizards links on magic.wizards.com/en/rules. Every run reads it, but the file changes only when Wizards publishes new rules.
- `rules/comprehensive.json` holds the whole of the same rules as a book (chapters, sections, rules with their subrules and examples, and the glossary), from the same download. It is about 1.1 MB and not in `explore-manifest.json`: the app reads it when it opens the rules.
- `sets/art.json` holds Wizards' official art for each set, keyed by Scryfall set code, for a set page's hero banner. A set Wizards has no art for is left out.
- `sets/tints.json` holds one tint colour per Scryfall set, for a set icon tile (a coloured rounded square with the white set symbol), taken from the set's Wizards art or its most played card's art; a child set has its parent's. A set with neither is left out.
- `sets/products/{code}.json` holds the sealed products (boosters, boxes, bundles, decks) of one set released since 2023 or yet to come, keyed by Scryfall set code, with TCGplayer's picture, link and price, read from TCGCSV. A set with no sealed products has no file.
- `sets/mechanics.json` holds the keyword abilities, keyword actions and ability words each set introduced, by Scryfall set code, with the rules, reminder text and example cards.
- `explore-manifest.json` lists the SHA-256 of each Explore file (`explore.json`, `today.json`, `previews.json`, `edh/top.json`, `rules/keywords.json`, `popular-cards/{format}.json` and `breakouts/{format}.json`), so the app fetches it first and downloads only the files whose hash differs. A file a run does not rewrite keeps its entry from the last manifest, which is kept in `state/explore-manifest.json`.

Card details come from Scryfall's API, not from this pipeline. Scryfall's bulk file is read once a run for card names and oracle ids, and for whether a card is a land, its price and its mana value, which pick the preview cards of results outside a tracked archetype.

## How a run works

`.github/workflows/scrape.yml` runs once a day, scheduled for 14:00 UTC after the card catalog's 10:17 build, so the price movers read that day's prices. GitHub's scheduler has been starting it hours late (between 17:52 and 19:24 UTC on 30 September to 3 October 2026), and the files land over two to three hours after it starts, one format after another and `index.json` last, so read a file's own `generated_at`. It can be started by hand from the Actions tab, though a change is better tried on a Mac first (see [Running locally](#running-locally)), since this private repository's Actions minutes are paid for. The workflow runs `ops/scrape.sh` with `PUBLISH=1`, as a job per format and then one more. The format jobs run one after another (so mtgo.com and MTGTop8 are only ever asked for one page at a time), each with `FORMATS` set to its format and `SHARED=0`: it scrapes that format and publishes its snapshot, decklists, archetype, event, popular-card and breakout files and the state. A format whose job fails keeps the snapshot it had, and the jobs after it run as usual. The last job, `SCRAPE=0`, reads nothing from mtgo.com or MTGTop8: it builds everything made from every format (`index.json`, `explore.json`, `today.json`, the card and commander pages, EDHREC, the guides, the set files, the movers) from the snapshots the format jobs left, whether they passed or not. Until it publishes `index.json`, the published index has the previous snapshots' `sha256`: an app whose cached snapshot matches keeps it, and one that downloads a snapshot in between gets the newer file. A run started by hand with some `formats` runs those formats' jobs and the last job; `fresh` has them ignore their stored snapshots and scrape state, and so start over (nothing in R2 is deleted, the new files overwrite the same keys), and `minutes` sets how long each job may request pages. Once a day matches its sources: MTGJSON builds its prices daily, Scryfall's bulk files and prices change about daily, and EDHREC's numbers about once a day. An MTGO event is published once MTGTop8 has named its decks, or is 3 days old, so an event of the last two days can show up a day or two late.

1. **Download.** It downloads `snapshots/` and `state/` from R2. They are the previous run's output, and the only state the scraper keeps.
2. **Scrape.** `python -m mtgmeta work` reads mtgo.com and MTGTop8 with plain HTTP (the standard library's `urllib`; no browser), one request at a time. For each format it:
   - reads mtgo.com's month page (`/decklists/{yyyy}/{mm}`, and the previous month's while the window reaches into it), and each event on it not yet stored: one page that holds every decklist of the event and its standings. Challenges, Showcases and Leagues are `mtgo_challenge` and `mtgo_league` events with the finishes mtgo.com gives ("12th Place"; a League's "5-0");
   - reads MTGTop8's list of the format (page 1, and older pages only while one holds events not seen yet or does not reach back to the oldest new MTGO event), then the MTGTop8 copy of each MTGO event, which names the decks by player. A deck MTGTop8 did not post takes the archetype whose average 30-day list is nearest (0.8 or more), else its colour letters; an event of the last 2 days with no MTGTop8 copy waits for a later run. See *Sources* in `docs/data-format.md`;
   - reads the paper events (every MTGTop8 event whose source is not mtgo.com) and, for each, the lists of its top 8 to 16 decks, newest first, with finishes "1st Place", "2nd Place", "Top 4", "Top 8" and "Top 16". A list that cannot be read is tried twice, then left (`state/sources.json`);
   - works out the shares of the 7, 14 and 30 day windows from the stored results, and each archetype's history and featured deck.

   Requests are made one at a time, `SCRAPE_DELAY` seconds apart (10 by default, never under 5) plus up to 50% random extra, with the User-Agent `MooliganData/1.0 (+https://github.com/missingems/mooligan-data)`, for at most `SCRAPE_MINUTES` (90) a run, in the order mtgo.com events, names, then paper events newest first. What the time ran out on is read by the next run. A 403, 429 or 5xx from a site stops requests to that site for the run: no retry, no workaround. A network error such as a timeout is retried once, a minute later, and stops the site for the run if it happens again.
3. **Publish.** `SnapshotStore.finish()` builds a page per card from every decklist in the window (reading back from `data.mooligan.com` the ones this run didn't download) (which archetypes play it, in how many decks), drops anything older than `HISTORY_DAYS`, and drops an event whose standings are identical to another's (remembered in `state/duplicate-event-ids.json` so later runs skip them), then merges the archetypes whose decklists show they play one deck under the biggest of them (see *Merged archetypes* in `docs/data-format.md`; `python -m mtgmeta clusters DIR --format modern --days 7` prints what would merge, writing nothing), then writes the snapshots, `explore.json`, a page per archetype in the metagame and per event, the deck id list and `index.json`. The snapshots as scraped, unmerged, go in `state/snapshots/`, which the next run starts from. `ops/scrape.sh` uploads decks first and `index.json` last, so the index never points at a file that isn't there yet. `explore-manifest.json` goes up just before it, after the Explore files it lists and the state, so it never names a hash a file doesn't have yet.

One failed page doesn't stop the run. Whatever was collected is still published, and the format's job is then marked failed so the errors show up in the Actions tab. Two runs never overlap.

Refused requests are different: they are a warning, the run passes and publishes what it has read, and the rest waits for the next run. A site that refused one format's job (a 403, 429 or 5xx) is not asked by the format jobs after it for 12 hours, so a day's refusal is one request. A network error such as a timeout stops that site for its own job only, and isn't counted. The run fails when requests are refused two days in a row. The count and the sites that refused are in `state/deck-downloads.json`, and the last job, which makes no requests, leaves it as it is.

A window with no events in it keeps the one an earlier run published, with its own `last_updated`, and every format still publishes.

A first run backfills 30 days. mtgo.com's roughly 500 events are read in the first run; MTGTop8's roughly 500 event pages for names and the paper decks are about 2,500 requests, which fill in over about a week of daily runs, using the room each leaves in `SCRAPE_MINUTES`. The 7-day window is right within a day or two. A normal day is about 110 requests, roughly 20 minutes.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FORMATS` | the eight below | Formats to scrape: `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `duel_commander` |
| `HISTORY_DAYS` | `30` | How far back events and archetype results go |
| `SCRAPE_DELAY` | `10` | Seconds between requests to mtgo.com and MTGTop8, plus up to 50% random extra. Values under 5 (MTGTop8's `Crawl-delay`) are raised to 5 |
| `SCRAPE_MINUTES` | `90`, `10` with `QUICK=1` | Minutes of requests a run may make; what is not read waits for the next run |
| `FRESH` | `0` | `1` ignores the downloaded snapshots (`snapshots/`, `state/snapshots/`) and the scrape's state (events seen, decks stored, the lists behind the archetypes), so the run starts from nothing. It deletes only local files; nothing in R2 is deleted, and the run overwrites the same keys. `formats` ignores only those of `FORMATS`, which is how the workflow's later format jobs follow the first, and how a fresh dispatch of some formats starts only those over |
| `DECK_RESOLVE_PER_RUN` | `300` | Published decklists read again per run to name entries the card catalog could not name when they were saved; each deck is tried 3 times |
| `SHARED` | `1` | `0` writes only `FORMATS`' own files and the state, and publishes neither `index.json` nor any file built from every format (a format job of the workflow) |
| `SCRAPE` | `1` | `0` reads nothing from mtgo.com or MTGTop8 and builds every file from the stored snapshots of every format, whatever `FORMATS` says (the workflow's last job). `SHARED=0` with `SCRAPE=0` is refused |
| `LOCALIZE` | `1`, `0` with `QUICK=1` | Add the `localized` map (printed names and pictures in ja, fr, it, es and de) to `today.json` and `explore.json`. It streams Scryfall's every-printing file, about 400 MB gzipped, so it adds a minute or two to a run; `0` skips it |
| `LOCALIZE_ALL_CARDS_URL` | Scryfall's `all_cards` bulk file | Read another file instead; a `file://` URL works |
| `KEYWORD_RULES` | `1` | `0` skips `rules/keywords.json` and `rules/comprehensive.json`, which read the Comprehensive Rules from Wizards' site |
| `SET_ART` | `1` | `0` skips `sets/art.json`, which reads each set's art from Wizards' site |
| `SET_ART_DELAY` | `0.5` | Seconds between requests to Wizards' site for `sets/art.json` |
| `SET_TINTS` | `1` | `0` skips `sets/tints.json`, which reads each main set's art (Wizards', else its most played card's from Scryfall) for a tint colour |
| `SET_TINTS_DELAY` | `0.1` | Seconds between requests for `sets/tints.json` (Scryfall asks for at least 0.1) |
| `SET_PRODUCTS` | `1` | `0` skips `sets/products/{code}.json`, which reads each recent set's sealed products from TCGCSV |
| `SET_PRODUCTS_DELAY` | `0.25` | Seconds between requests to TCGCSV (it asks for at least 0.1) |
| `SET_MECHANICS` | `1` | `0` skips `sets/mechanics.json`, which reads Scryfall's every-printing file (about 80 MB gzipped) for the mechanics each set introduced |

## Setup

- **R2:** the bucket is `mtg-meta-data`, with custom domain `data.mooligan.com`. The app is native, so the bucket needs no CORS rule.
- **GitHub secrets:** `R2_ACCOUNT_ID`, and `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` from an account API token with Object Read & Write on that bucket only. `ANTHROPIC_API_KEY` for what Claude writes: the commander guides' summaries, the premier events' formats and the archetype primers. `PRIMERS_ADMIN_TOKEN`, the API Worker's `ADMIN_TOKEN`, for publishing the archetype primers.

## Running locally

```bash
cd scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
FORMATS=modern HISTORY_DAYS=3 SCRAPE_MINUTES=10 .venv/bin/python -m mtgmeta work
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

No keys are needed. With none, a run starts from the live data: it downloads `snapshots/` and `state/` read-only from `https://data.mooligan.com`, as the workflow syncs them from R2. Nothing opens a browser: the scraper uses plain HTTP, so there is no Chrome or Xvfb to install.

```bash
QUICK=1 ops/scrape.sh                                   # modern only, 3 days, 10 minutes of requests, no EDHREC, locator, premier or movers
QUICK=1 FORMATS=pauper,vintage SCRAPE_MINUTES=20 ops/scrape.sh  # any setting overrides the preset
QUICK=1 MOVERS=1 ops/scrape.sh                          # with price movers, today.json's preview and previews.json (downloads Scryfall's bulk file)
QUICK=1 LOCALIZE=1 ops/scrape.sh                        # with the localized names (downloads Scryfall's 400 MB all_cards file)
ops/scrape.sh                                           # the full daily run, without the upload
SYNC=none QUICK=1 ops/scrape.sh                         # from nothing, like a first run
FRESH=1 QUICK=1 ops/scrape.sh                           # the downloaded snapshots and scrape state ignored
```

`QUICK=1` sets `FORMATS=modern`, `HISTORY_DAYS=3`, `SCRAPE_MINUTES=10` (requests stay `SCRAPE_DELAY`, 10 seconds, apart), `EDHREC_CARDS_PER_RUN=0`, `EDHREC_COMMANDERS_PER_RUN=0` (so no bracket rankings either), `GUIDES_PER_RUN=0`, `LOCATOR_PLACES=` (none), `PREMIER_SCHEDULE=0`, `MOVERS=0` and `LOCALIZE=0`, each only when not set already. `SYNC` picks where a run starts from: `auto` (the default: R2 when keys are set, else HTTPS), `r2`, `https` or `none`. The other variables are the scraper's, in the table above.

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

The same download also gives `rules/comprehensive.json`, the whole book: every chapter, section, rule, subrule and example, and the glossary, in the order of the text. It has its own fingerprint (`state/rules-comprehensive.json`) and is written only when the rules changed, like the keyword file. The two are parsed separately, so a text one of them cannot read leaves the other to publish, and a text with fewer than about 60% of the chapters, sections, rules or glossary entries of the current edition is not published.

## Set art

`sets/art.json` is read from Wizards' sitemap: each set's product page and card image gallery are matched to a Scryfall set by name, and their `og:image` is kept with its measured size (see `scraper/mtgmeta/setart.py`). Requests are 0.5 seconds apart with a descriptive User-Agent. The pages read are cached in `state/set-art.json` by URL and the sitemap's `lastmod`, so after the first run (about 300 requests) a run reads only the pages that changed. It can be run alone with `python -m mtgmeta set-art DIR`. When Wizards' site cannot be read the run logs a warning and carries on, and the published file stays as it was. See `docs/data-format.md`.

`sets/tints.json` takes one colour from each main set's picture: Wizards' art for it from `sets/art.json` (fetched 96 pixels wide), else the art crop of its most played card from Scryfall. The picture is shrunk to 16 by 16 pixels, the hue bin with the most saturation times brightness wins, and its colour is made dark or light enough for a white symbol (see `scraper/mtgmeta/settints.py`). Every child set (`parent_set_code`) gets its root parent's colour. Colours are kept in `state/set-tints.json` by set code and picture URL, so after the first run (about 1,000 requests, at least 0.1 seconds apart) a run reads only the new sets and those whose Wizards art changed. It can be run alone with `python -m mtgmeta set-tints DIR`. When Scryfall's sets cannot be read the run logs a warning and carries on, and the published file stays as it was. See `docs/data-format.md`.

## Set products

`sets/products/{code}.json` is read from TCGCSV (<https://tcgcsv.com>), which mirrors TCGplayer's Magic catalog once a day. Each group (TCGplayer's set) is matched to a Scryfall set released since 2023, or not yet out, by abbreviation and name, and its products with no card number and rarity are the sealed ones (see `scraper/mtgmeta/setproducts.py`). Following TCGCSV's usage guidelines, requests carry a custom User-Agent and are 0.25 seconds apart, and a run reads `last-updated.txt` first. A first run makes about 150 requests (a group list, then products and prices for each of about 75 groups). The groups read are kept in `state/set-products.json` with TCGCSV's build time and the group's own `modifiedOn`: a set out in the last 120 days or yet to come is read again after each build (its prices move and its products are added), an older one only when its `modifiedOn` changed or its copy is 14 days old, so a normal run makes a few dozen requests. It can be run alone with `python -m mtgmeta set-products DIR`. When TCGCSV cannot be read the run logs a warning and carries on, and the published files stay as they were. See `docs/data-format.md`.

## Set mechanics

`sets/mechanics.json` is built from Scryfall's every-printing file (`default_cards`, which the movers also read; it is a second download of about 80 MB gzipped), its three catalogs of keyword abilities, keyword actions and ability words, and `rules/keywords.json`: this run's copy when the rules changed, else the published one at `DATA_URL`. A keyword is new to the set holding its earliest paper printing (see `scraper/mtgmeta/setmechanics.py`). It can be run alone with `python -m mtgmeta set-mechanics DIR`. When Scryfall or the rules cannot be read the run logs a warning and carries on, and the published file stays as it was. See `docs/data-format.md`.

## Premier play calendar

`premier/schedule.json` is magic.gg's schedule of Pro Tours, Regional Championships, Spotlight Series, Worlds and CommandFests, read once a run. The page embeds its calendar as Nuxt state, which the scraper evaluates with Node. Each event gets a `region` from its name so an app can show the user's own Regional Championship, and `formats` from its type and name, from `scraper/mtgmeta/premier_format_overrides.json`, or, with `ANTHROPIC_API_KEY` set, from Claude (`claude-haiku-5-5`) reading its magic.gg article once (cached in `state/premier-formats.json`).

## Wizards' event locator

`LOCATOR_PLACES` (semicolon-separated) names places whose upcoming in-store events are read from Wizards' Store & Event Locator and published as `locator/<place>.json`: the next `LOCATOR_DAYS` days within `LOCATOR_DISTANCE_MILES`, one page of 100 events per request, `LOCATOR_DELAY` seconds apart. Note that Wizards' Terms of Use bar automated collection from their sites; this is run at Jun's own decision, kept to a few requests a run, and links every event back to the locator and the store.

## EDHREC

Commander usage on each card page comes from EDHREC, used with their permission. A run refreshes `EDHREC_CARDS_PER_RUN` cards (800 by default, 1600 in `ops/scrape.sh`) and `EDHREC_COMMANDERS_PER_RUN` commanders (150, 300 in `ops/scrape.sh`, so a daily run reads as many as two runs a day did), at `EDHREC_DELAY` seconds apart, longest unchecked first, so the set comes round over days and the rate stays low. A commander page carries what that commander's decks play and its average decklist, so a reader never has to leave for the numbers. Their numbers move about once a day. Anything showing this data must credit EDHREC and link back to the `url` on each entry.

`edh/top.json` also ranks the 50 commanders most played at each Commander Bracket: Brackets 1 to 4 from EDHREC's bracket counts of the past month's top 300 commanders (`BRACKET_PAGES_PER_RUN`, 150, EDHREC pages a run, the rest cached a week in `state/bracket-counts.json`), and cEDH from [EDHTop16](https://edhtop16.com)'s tournament entries of the past three months (two requests a day at most, cached in `state/edhtop16.json`; EDHREC's counts stand in when it cannot be read). EDHTop16 has no published API: the scraper asks its site's own GraphQL endpoint with the query id its page script uses (`EDHTOP16_QUERY_ID` in `top_brackets.py`, read again from the site when it changes).

The guides (`edh/commanders/{slug}/guide.json`) of the first `GUIDES_TOP` (100) commanders of `edh/top.json` and of every one its brackets rank are built from EDHREC's theme and bracket pages, Commander Spellbook's estimate-bracket and Scryfall's catalog: `GUIDES_PER_RUN` (60, 45 in `ops/scrape.sh`) a run, the ones due (never built, a week old, or whose themes changed), `GUIDE_DELAY` (1) seconds between EDHREC pages. With `ANTHROPIC_API_KEY` set (the GitHub secret of the same name), Claude (`claude-haiku-5-5`) then rewrites the summaries of the guides whose facts changed, as one Message Batch at half price; the run waits for it up to `POLISH_WAIT_MINUTES` (30, 15 in `ops/scrape.sh`) and logs its tokens and dollars, and a batch still running is collected by the next run (`state/polish-batch.json`, which holds `{"batches": []}` when none is running, and records the model each batch was sent on, so one sent before a model change is still applied). `GUIDE_POLISH=0` turns that off; `ops/scrape.sh` only polishes on a run that publishes unless `GUIDE_POLISH=1`. `python -m mtgmeta guides DIR --top 5 [--brackets] [--polish]` builds them by hand. See [`docs/data-format.md`](docs/data-format.md#edhcommandersslugguidejson).

## Archetype primers

The deck guides on an archetype's Primers tab are playgraph Markdown on api.mooligan.com (the API's `format_guide` describes it). `.github/workflows/guides.yml` ("Write archetype primers") runs `ops/primers.sh` after each scrape that wasn't cancelled. Claude then writes the primers that are due, as one Message Batch at half price, and the run publishes them.

Which archetypes get a primer, set in one place at the top of `scraper/mtgmeta/primers.py`:

- first, the first 16 (`COUNT`) of each of the six main formats' 30-day standings in `explore.json`;
- then every other archetype with 10 (`MIN_RESULTS`) results or more in `snapshots/{format}.json`, at most 25 (`BACKFILL`) of them a run. Each format's go by most results, and the formats take turns, so Modern's many results don't keep the others waiting. Today that covers 25 archetypes in Standard and 45 in Modern, about 180 in all.

A primer is due when:

- **missing:** the archetype has no primer under its id. The app finds a primer by its archetype's id, so the primer of an archetype since merged into this one (the snapshot's `merges`) doesn't count. A new primer is written under this archetype's id, starting from the old one's text; the old one is left as it is;
- **changed:** its consensus main deck has moved by 6 cards or more since the primer was written, or its top card (the first of `hand`) is new to the deck. `state/primers.json` keeps the consensus each primer written here came from. For a primer written or edited by hand, its `Main cards` grid stands in, and only copies that left the deck count;
- **old:** the primer was last updated 90 or more days ago (`STALE_DAYS`) and its main deck has moved by a card or more since it was written (counted as for *changed*). An old primer whose deck is the same is left alone. A primer with no state (written or edited by hand) is old by its age alone, since its grid sees only some of the deck.

A primer that fails its checks (declined, cut off, or still invalid after the repair) is noted as failed that day in `state/primers.json` and isn't due again for 7 days (`FAILED_DAYS`), unless asked for with `--archetype`, so a primer that keeps failing isn't paid for every run.

Everything else is left alone:

- archetypes past the 16th with fewer than 10 results, and their primers;
- Commander, whose guides the scrape builds (see [EDHREC](#edhrec)).

A primer that is due again is replaced by a new version of the same id, with a note saying what it was written from and why.

A missing primer is written by `claude-opus-5-5` at effort high. A refresh of one that exists (changed or old) is a revision by `claude-sonnet-5-5` at effort medium: it is told to keep what still holds in the primer it has now and to rewrite what the changes make wrong (the Main cards grid, the sideboard and matchups, and anything said about cards the deck no longer plays or now plays), and it replies with the whole primer.

Claude is sent:

- the archetype's shares, consensus and other cards;
- its recent results;
- the format's other top archetypes;
- the Oracle text of every card;
- the primer as it stands.

Each draft is checked by the API's `validate_primer`. It is then checked for problems:

- cards Scryfall doesn't know;
- matchups that aren't archetypes of the format;
- `in:` cards the sideboard doesn't play and `out:` cards the main deck doesn't play;
- matchups that bring in a different number of cards than they take out.

A draft with problems is sent back once, as a single streamed call to the same model at the standard price, in one new message with the facts, the draft and its problems (the batch's own turn isn't replayed), and one that still has them is not published. No draft is sent back after 120 minutes of the run (`RUN_MINUTES`), so the run always ends, and uploads its state, inside the job's 150. Every draft and its problems are kept for 30 days as the run's `primers` artifact.

The run sends the primers it can afford as one batch and polls it every 30 seconds for at most `MINUTES` (60 when 0, 90 in the workflow, which leaves an hour of the job's 150 minutes for checks and drafts sent back). A batch that hasn't ended by then is kept in `state/primer-batch.json` (the day it was sent, and each request's primer id, archetype, format and model), which `ops/primers.sh` downloads and uploads beside `state/primers.json`, from a trap, so a run that is cancelled or timed out keeps it too. The next run collects it first, once it has ended. A primer of it that is still due is checked and published as if it had come back at once (dated by the day the batch was sent), and isn't sent again. A batch with a primer that isn't due in that run (it was narrowed by `formats`, `count` or `--archetype`, or the standings moved) isn't read: it stays, its primers held, for a run that has them all, and 14 days after it was sent (`HOLD_DAYS`) it is read all the same and the primers not due are dropped and logged. A batch the API no longer has is dropped; one that can't be read for another reason is kept. A primer that can't be checked is failed, and the others go on. A batch still running keeps its primers out of that run's batch. With no batch left the file holds `{"batches": []}`, because `ops/primers.sh` never deletes in R2. A run that doesn't publish uploads nothing, so a batch it leaves running is lost.

A primer costs about $0.30 by Opus and a revision about $0.15 by Sonnet, at batch prices: 13k tokens in, plus up to 25k of thinking and primer. These are the estimates (`ESTIMATES`) that pick the primers a run sends: in order, while their sum fits `BUDGET` ($5) less what the batches it collected first cost and the estimates of the batches still in flight. A batch holds its estimates in the budget from the moment it is sent until it is collected; its real cost, from its usage, is then spent in their place and logged with the tokens; a draft sent back costs a call at the standard price, twice an estimate, and is sent only if the budget covers it. The primers left wait for the next run: the first 16 before the others, and missing ones first. Most batches end within the hour, though one may take up to 24. This is not yet timed. Catching up on the roughly 107 primers due today, if all are missing, comes to about $32 whatever the budget; the budget only sets the pace, about 7 runs at $5. Once every primer is current only a moved deck costs anything, as a revision; there is no figure for how many a day yet. A run is meant to stay within `BUDGET`, though the estimates can be off, so $5 a day comes to about $150 a month at most.

The workflow needs these GitHub secrets:

- `ANTHROPIC_API_KEY`;
- `PRIMERS_ADMIN_TOKEN`;
- the R2 keys, for `state/primers.json` and `state/primer-batch.json`.

It shares the scrape's concurrency group, because the scrape uploads the `state/` it downloaded when it started. From the Actions tab, Run workflow takes:

- a mode: `write`; `plan`, which lists what is due and why; or `check`, which validates the published primers. `plan` and `check` need no key and spend nothing;
- the formats;
- the count;
- the budget.

From a terminal:

```bash
gh workflow run guides.yml -f mode=plan
```

```bash
gh workflow run guides.yml -f mode=write -f formats=pauper -f budget=2
```

On a Mac, `ops/primers.sh` does the same, and publishes nothing unless `PUBLISH=1`. The drafts land in `scraper/work-primers/primers/`:

```bash
MODE=plan ops/primers.sh
```

```bash
MODE=check FORMATS=modern ops/primers.sh
```

```bash
FORMATS=pauper BUDGET=1 ops/primers.sh    # needs ANTHROPIC_API_KEY
```

`python -m mtgmeta primers DIR [--archetype ID] [--plan | --check | --publish]`, run in `scraper/`, is the step itself.

## Sources and courtesy

The results come from **mtgo.com**, whose decklist pages are Wizards' official ones (its `robots.txt` is a 404, so it states no rules), and **MTGTop8**, whose `robots.txt` asks for a `Crawl-delay` of 5 seconds; we wait 10. The scraper asks for one page at a time, names itself in its User-Agent, makes about 110 requests on a normal day, reads each finished event and decklist once, and stops asking a site that refuses. The app credits both sources where it shows their results.

## Caveats

- mtgo.com's and MTGTop8's markup can change. The parsers raise `ParseError` rather than write empty data, so a layout change shows up as a failed run.
- If a site refuses requests (the log says which, with the HTTP status), raise `SCRAPE_DELAY`; the run does not look for a way round. Two days in a row with a refusal fail the job.
- GitHub disables scheduled workflows in a public repo after 60 days without commits. If the schedule stops, re-enable it from the Actions tab.
- Scraping may conflict with the sites' terms of use. Keep the rate low, and don't redistribute the data commercially.
