# MTG Meta Pipeline

A serverless backend that scrapes MTGGoldfish tournament data twice a day and mirrors Scryfall's card database once a day into Firestore. Firebase callable functions serve the data, and a static website on GitHub Pages shows it.

```
Cloud Scheduler ──02:00, 14:00 UTC──▶ Cloud Run Job (scraper/)          ──▶ Firestore: meta, events, decks
Cloud Scheduler ──03:00 UTC─────────▶ scheduledScryfallSync (functions/) ──▶ Firestore: cards
Website (web/, GitHub Pages) ──▶ getMeta · getEvents · getDecklist · getCardDetails ──▶ Firestore
```

| Folder | What it holds |
| --- | --- |
| `functions/` | TypeScript Cloud Functions: the daily Scryfall sync and the four callables |
| `scraper/` | Python SeleniumBase (UC mode) scraper, its Dockerfile and `deploy.sh` for the Cloud Run Job |
| `web/` | Static site: plain HTML and ES modules, no build step |
| `firestore.rules` | Denies every client read and write. Only the Admin SDK touches the database |

## Firestore collections

| Collection | Document ID | Written by |
| --- | --- | --- |
| `meta` | `{format}_{timeframe}`, e.g. `modern_30d` | scraper |
| `events` | MTGGoldfish tournament id | scraper |
| `decks` | MTGGoldfish deck id | scraper (new decks only; published decks never change) |
| `cards` | Scryfall `oracle_id` (the Scryfall `id` for cards without one) | Scryfall sync |
| `sync_state` | `scryfall` plus 16 `hashes` shards | Scryfall sync bookkeeping |

The field names follow the spec. `functions/src/shared/schema.ts` and `scraper/mtgmeta/models.py` define them, and must be kept in step. These fields go beyond the spec:

- `meta.archetypes[].deck_count` and `meta.timeframe`
- `events.url`, and `decks.format` and `decks.event_id`
- `cards.search_names`: the lower-cased full name plus each face name. Decklists name a double-faced card by its front face ("Fable of the Mirror-Breaker"), which `where("name", "==", …)` would never match.

## Scryfall sync

`scheduledScryfallSync` runs daily at 03:00 UTC. It reads `oracle-cards` from Scryfall's bulk-data API, then streams the `jsonl.gz` file through gunzip and readline, so only one line is in memory at a time. It writes to `cards` in `WriteBatch`es of 500, with four batches committing at once.

Each card is reduced to its gameplay fields and hashed. Prices are dropped because they change every day. The hashes live in 16 shard documents, so a run starts with 16 reads and rewrites only the cards whose content changed. The first run writes all ~39k cards, and later runs usually write a handful. If Scryfall's `updated_at` hasn't moved since the last run, the run does nothing. A card that disappears from the file is deleted only when the file held at least 10,000 cards, so a truncated download can never empty the collection.

Measured against the real file (2026-09-21): 38,906 cards, 78 batches, 165 MB peak RSS, largest card document 6 KB, largest hash shard 152 KB.

## Callable functions

| Function | Input | Returns |
| --- | --- | --- |
| `getMeta` | `{ format, timeframe? }`, timeframe defaults to `"30d"` | The `meta` document |
| `getEvents` | `{ format, limit? }`, limit 1–100, default 20 | `{ events: [...] }`, newest first, each with its `results` |
| `getDecklist` | `{ deck_id }` | The deck, with `mainboard` and `sideboard` |
| `getCardDetails` | `{ card_name }`, matched without regard to case, by full or face name | The `cards` document |

Timestamps are returned as ISO 8601 strings. Invalid input throws `invalid-argument`, and a missing document throws `not-found`. The callables need no sign-in, because the website is public. Each function is capped at 10 instances.

## Scraper

`python -m mtgmeta` opens MTGGoldfish in SeleniumBase UC mode. For each format, it:

1. reads the full metagame page for each window in `META_DAYS`. The site's own period selector switches the window, and it offers 7, 14, 30, 90 and 365 days.
2. lists the recent tournaments and reads each tournament page for players, archetypes and finishes. A Challenge finish reads "1st Place", and a League finish is a record such as "5-0".
3. downloads each new decklist as text through `fetch("/deck/download/{id}")` inside the page, so the request reuses the browser's Cloudflare clearance.

One failed page doesn't stop the run. The job exits with status 1 when anything failed, so Cloud Run shows the error.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FORMATS` | `modern,standard,pioneer` | Formats to scrape |
| `META_DAYS` | `30` | Metagame windows, e.g. `30,7` gives `modern_30d` and `modern_7d` |
| `EVENTS_PER_FORMAT` | `10` | Recent events read per format |
| `MAX_NEW_DECKS` | `400` | New decklists downloaded per run. Anything over the limit waits for the next run |
| `REQUEST_DELAY` | `1.5` | Base seconds between requests, plus up to 50% random extra |
| `HEADLESS` | `1` on macOS, `0` on Linux | On Linux, UC mode runs Chrome headed inside Xvfb |

Run it locally:

```bash
cd scraper && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
FORMATS=modern EVENTS_PER_FORMAT=2 MAX_NEW_DECKS=5 .venv/bin/python -m mtgmeta --dry-run output
```

`--dry-run DIR` writes JSON files instead of Firestore documents. Without it, the scraper writes to the project in `GOOGLE_CLOUD_PROJECT` using Application Default Credentials.

## Setting up

You need the Firebase CLI (`npm i -g firebase-tools`), the gcloud CLI, and a Firebase project on the Blaze plan. Scheduled functions and Cloud Run need billing.

1. **Project.** Put your project id in `.firebaserc`. Create the Firestore database in the console, in Native mode.
2. **Rules, indexes and functions.**
   ```bash
   cd functions && npm install && npm test
   cd .. && firebase deploy --only firestore,functions
   ```
   To deploy somewhere other than `us-central1`, set `FUNCTIONS_REGION=<region>` in `functions/.env`, and set the same region in `web/config.js`.
3. **First card load.** Either run the scheduled job once:
   ```bash
   gcloud scheduler jobs run firebase-schedule-scheduledScryfallSync-us-central1 --location us-central1
   ```
   or run the sync from your machine:
   ```bash
   gcloud auth application-default login
   cd functions && GCLOUD_PROJECT=<project-id> npm run sync:local
   ```
4. **Scraper.** `PROJECT_ID=<project-id> ./scraper/deploy.sh` does the following:
   - builds the image with Cloud Build, so Docker isn't needed locally
   - creates a service account that can only write Firestore
   - deploys the Cloud Run Job with 2 CPU, 2 GiB and a 1-hour timeout
   - schedules it for `0 2,14 * * *` UTC

   Start a run straight away with `gcloud run jobs execute mtggoldfish-scraper --region us-central1`.
5. **Website.** Paste the web app config from the Firebase console into `web/config.js`. Then choose **Settings → Pages → Source: GitHub Actions** in the GitHub repository. Each push to `main` that changes `web/` deploys the site. Until `projectId` is set, the site shows the bundled sample in `web/sample/data.json`. To preview it locally, run `python3 -m http.server -d web 8000`.

## Tests

- `functions/`: `npm test` covers the stream parser (gzipped and plain input), card normalisation and hashing, batching, the skip and delete logic of the sync, and every callable against a fake Firestore.
- `scraper/`: `pytest` runs the parsers against trimmed copies of real MTGGoldfish pages from 2026-09-22, and runs a full scrape into JSON files with a fake browser.

CI runs both suites on each push and pull request.

## Caveats

- MTGGoldfish sits behind Cloudflare, and its markup can change. The parsers raise `ParseError` when a page doesn't look as expected. They never write empty data. Check the job's logs when the job fails.
- Scraping may conflict with MTGGoldfish's terms of use. Keep the request rate low, and don't redistribute the data commercially.
- The Docker image hasn't been built on this machine, because Docker isn't installed here. Cloud Build builds it during `deploy.sh`.
