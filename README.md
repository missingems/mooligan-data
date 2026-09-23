# MTG Meta Pipeline

Scrapes MTGGoldfish's metagame, tournament results and decklists twice a day, and publishes them as static JSON at **`https://data.mooligan.com`**, a Cloudflare R2 bucket. A mobile app and the website read the same files. There's no server or database.

```
GitHub Actions (02:00, 14:00 UTC)
  └─ download previous snapshots from R2 → scrape what's new → upload to R2
                                                                   │
                            data.mooligan.com (Cloudflare CDN) ◀───┘
                              ├─ the app
                              └─ web/ on GitHub Pages
```

| Path | What it holds |
| --- | --- |
| `scraper/` | Python SeleniumBase (UC mode) scraper, and the snapshot store it publishes |
| `web/` | Static site: plain HTML and ES modules, no build step |
| `docs/data-format.md` | **The published files and their fields.** This is what the app codes against |
| `.github/workflows/scrape.yml` | The scheduled scrape and upload |
| `.github/workflows/r2-check.yml` | Manual check that the R2 token, bucket and domain work together |

## Published data

See [docs/data-format.md](docs/data-format.md). In short:

- `index.json` gives each format's snapshot with a hash, so clients download only when something changed.
- `snapshots/{format}.json` holds the metagame, the last 30 days of events, and every archetype's results.
- `decks/{id}.json` holds one decklist per file, cached for good.
- `cards/{slug}.json` says where a card is played, across every format, with links to decks, plus its Commander usage from EDHREC.

Card details come from Scryfall's API, not from this pipeline. Scryfall's bulk file is read once a run for card names and oracle ids.

## How a run works

`.github/workflows/scrape.yml` runs at 02:00 and 14:00 UTC, and can be started by hand from the Actions tab.

1. **Download.** It downloads `snapshots/` and `state/` from R2. They are the previous run's output, and the only state the scraper keeps.
2. **Scrape.** `python -m mtgmeta work` opens MTGGoldfish in SeleniumBase UC mode, with Chrome inside Xvfb on the runner. For each format it:
   - reads the metagame page (30-day window);
   - reads each archetype's page for its featured deck, then `/archetype/<id>/decks` for its results. Results merge with the previous snapshot, so an archetype stops at the first page with nothing new;
   - reads every event of the window from MTGGoldfish's tournament search (20 a page, `MAX_SEARCH_PAGES` at most), plus the archetype lists' mentions for multi-format events, and reads up to `MAX_NEW_EVENTS` not yet stored, newest first. Each event is classed by name (Pro Tour, Regional Championship, RCQ, Store Championship, MTGO Challenge or League, other);
   - downloads new decklists, up to `MAX_NEW_DECKS` a run. A deck MTGGoldfish has deleted redirects to its metagame page; those ids go in `state/missing-deck-ids.json` so later runs skip them. Featured decks come first, then the newest.

   Only the metagame and tournaments-list pages are real browser visits. Everything else is fetched with `fetch()` from inside the open page, `CONCURRENCY` requests at a time. Those requests reuse the page's Cloudflare clearance and skip rendering, so a batch of 6 takes about a second, where a visit takes about 7. A refused batch (403 or a challenge page, as happens straight after the first page load) makes the browser reload a page to renew the clearance and retry.
3. **Publish.** `SnapshotStore.finish()` builds a page per card from every decklist in the window (reading back from `data.mooligan.com` the ones this run didn't download) (which archetypes play it, in how many decks), drops anything older than `HISTORY_DAYS`, and drops events MTGGoldfish imported twice (identical standings under a second id, remembered in `state/duplicate-event-ids.json` so later runs skip them), then writes the snapshots, the deck id list and `index.json`. The workflow uploads decks first and `index.json` last, so the index never points at a file that isn't there yet.

One failed page doesn't stop the run. Whatever was collected is still published, and the job is then marked failed so the errors show up in the Actions tab. Two runs never overlap.

A first run reads a month of history for every archetype. For Vintage (23 archetypes, 400 decklists) that took 4 minutes; Modern has about three times as many archetypes. Later runs usually read one page per archetype.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FORMATS` | the nine below | Formats to scrape: `modern`, `standard`, `pioneer`, `legacy`, `pauper`, `vintage`, `premodern`, `penny_dreadful`, `duel_commander` |
| `META_DAYS` | `30,14,7` in the workflow | Metagame windows to publish |
| `EVENTS_PER_FORMAT` | `10` | Events read from the tournaments list, which never shows more than 10 |
| `MAX_NEW_EVENTS` | `150` | Events not yet stored read per format per run |
| `MAX_SEARCH_PAGES` | `25` | Tournament-search pages read per format, 20 events each |
| `HISTORY_DAYS` | `30` | How far back events and archetype results go |
| `ARCHETYPE_DECKS` | `100` | Archetypes per format, most played first, whose results are kept |
| `MAX_ARCHETYPE_PAGES` | `20` | Deck-list pages per archetype per run |
| `MAX_NEW_DECKS` | `1500` in the workflow | New decklists per format per run |
| `CONCURRENCY` | `6` | Requests fetched at once from inside the page |
| `REQUEST_DELAY` | `1` in the workflow | Base seconds between batches, plus up to 50% random extra |

## Setup

- **R2:** the bucket is `mtg-meta-data`, with custom domain `data.mooligan.com` and CORS allowing `https://missingems.github.io` and `http://localhost:8765`.
- **GitHub secrets:** `R2_ACCOUNT_ID`, and `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` from an account API token with Object Read & Write on that bucket only.
- **Website:** GitHub Pages, deployed from `web/` on each push to `main`. It's at https://missingems.github.io/mtg-meta-pipeline/.

## Running locally

```bash
cd scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
FORMATS=modern ARCHETYPE_DECKS=5 HISTORY_DAYS=3 MAX_NEW_DECKS=5 .venv/bin/python -m mtgmeta work
python3 -m http.server -d web 8765   # the site, reading data.mooligan.com
```

A local run writes into `scraper/work/` and publishes nothing.

## Premier play calendar

`premier/schedule.json` is magic.gg's schedule of Pro Tours, Regional Championships, Spotlight Series, Worlds and CommandFests, read once a run. The page embeds its calendar as Nuxt state, which the scraper evaluates with Node. Each event gets a `region` from its name so an app can show the user's own Regional Championship.

## Wizards' event locator

`LOCATOR_PLACES` (semicolon-separated) names places whose upcoming in-store events are read from Wizards' Store & Event Locator and published as `locator/<place>.json`: the next `LOCATOR_DAYS` days within `LOCATOR_DISTANCE_MILES`, one page of 100 events per request, `LOCATOR_DELAY` seconds apart. Note that Wizards' Terms of Use bar automated collection from their sites; this is run at Jun's own decision, kept to a few requests a run, and links every event back to the locator and the store.

## EDHREC

Commander usage on each card page comes from EDHREC, used with their permission. A run refreshes `EDHREC_CARDS_PER_RUN` cards (800 by default) and `EDHREC_COMMANDERS_PER_RUN` commanders (150), at `EDHREC_DELAY` seconds apart, longest unchecked first, so the set comes round over days and the rate stays low. A commander page carries what that commander's decks play and its average decklist, so a reader never has to leave for the numbers. Their numbers move about once a day. Anything showing this data must credit EDHREC and link back to the `url` on each entry.

## Caveats

- MTGGoldfish sits behind Cloudflare, and its markup can change. The parsers raise `ParseError` rather than write empty data, so a layout change shows up as a failed run.
- Cloudflare challenges an address that scrapes a lot. GitHub's runners have got through so far. If runs start failing with "Blocked on …", lower `CONCURRENCY` or raise `REQUEST_DELAY`.
- GitHub disables scheduled workflows in a public repo after 60 days without commits. If the schedule stops, re-enable it from the Actions tab.
- Scraping may conflict with MTGGoldfish's terms of use. Keep the rate low, and don't redistribute the data commercially.
