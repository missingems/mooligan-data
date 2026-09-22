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

Card details come from Scryfall's API, not from this pipeline.

## How a run works

`.github/workflows/scrape.yml` runs at 02:00 and 14:00 UTC, and can be started by hand from the Actions tab.

1. **Download.** It downloads `snapshots/` and `state/deck-ids.json` from R2. They are the previous run's output, and the only state the scraper keeps.
2. **Scrape.** `python -m mtgmeta work` opens MTGGoldfish in SeleniumBase UC mode, with Chrome inside Xvfb on the runner. For each format it:
   - reads the metagame page (30-day window);
   - reads each archetype's page for its featured deck, then `/archetype/<id>/decks` for its results. Results merge with the previous snapshot, so a run stops at the first page with nothing new;
   - reads the 10 latest events plus up to `MAX_NEW_EVENTS` older ones that the archetype lists mention;
   - downloads new decklists through `fetch("/deck/download/{id}")` inside the page, up to `MAX_NEW_DECKS` a run. Featured decks come first, then the newest.
3. **Publish.** `SnapshotStore.finish()` drops anything older than `HISTORY_DAYS`, then writes the snapshots, the deck id list and `index.json`. The workflow uploads decks first and `index.json` last, so the index never points at a file that isn't there yet.

One failed page doesn't stop the run. Whatever was collected is still published, and the job is then marked failed so the errors show up in the Actions tab. Two runs never overlap.

A first run reads a month of history for every archetype, so it takes a few hours. Later runs usually read one page per archetype.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FORMATS` | `modern,standard,pioneer` | Formats to scrape |
| `META_DAYS` | `30` | Metagame windows; `30,7` would publish both |
| `EVENTS_PER_FORMAT` | `10` | Events read from the tournaments list, which never shows more than 10 |
| `MAX_NEW_EVENTS` | `60` | Older events per format read per run |
| `HISTORY_DAYS` | `30` | How far back events and archetype results go |
| `ARCHETYPE_DECKS` | `100` | Archetypes per format, most played first, whose results are kept |
| `MAX_ARCHETYPE_PAGES` | `20` | Deck-list pages per archetype per run |
| `MAX_NEW_DECKS` | `400` | New decklists per run |
| `REQUEST_DELAY` | `2` in the workflow | Base seconds between requests, plus up to 50% random extra |

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

## Caveats

- MTGGoldfish sits behind Cloudflare, and its markup can change. The parsers raise `ParseError` rather than write empty data, so a layout change shows up as a failed run.
- Cloudflare challenges an address that scrapes a lot. GitHub's runners have got through so far. If runs start failing with "Blocked on …", raise `REQUEST_DELAY`.
- GitHub disables scheduled workflows in a public repo after 60 days without commits. If the schedule stops, re-enable it from the Actions tab.
- Scraping may conflict with MTGGoldfish's terms of use. Keep the rate low, and don't redistribute the data commercially.
