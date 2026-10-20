# lore

An index of the official Magic story, built from the Magic Story articles and the planeswalker and plane profiles on magic.wizards.com, for answering questions like "who is Jace?" and "what happened to Jace?" with the quote and link behind every fact.

```
python -m mtglore scrape    # every article and profile → data/stories, data/profiles
python -m mtglore extract   # Claude reads each page → data/extracted (Message Batches API)
python -m mtglore build     # one index → data/index
python -m mtglore prompt stories/<slug>          # what the batch would send Claude for one page
python -m mtglore ingest stories/<slug> raw.json # check and save an extraction made some other way
python -m mtglore recheck                        # run every saved extraction through the quote check again
python -m mtglore publish                        # the site's data → site/dist/data
python -m mtglore scrape-scryfall                # Scryfall's card catalog → data/scryfall (oracle ids, printings, sets)
python -m mtglore app                            # the app's feed → site/dist/app (see docs/data-format.md, LORE_HANDOFF.md)
```

The first full extraction was made without the API: Claude Code sub-agents (Claude Sonnet 5.5) read each page with `prompt` and wrote its JSON, which `ingest` ran through the same quote check; their files say so under `model`. `recheck` runs every saved extraction through the check again, as after the check is made stricter.

Each step only does what is new: scrape skips pages already saved, extract skips pages already extracted with the current `PROMPT_VERSION`, and build is rebuilt from scratch. The `Lore` workflow (`.github/workflows/lore.yml`) runs all three and commits `data/`. It runs every Monday, on demand, and on any push to the branch that edits `run.json`, which sets how many pages to extract (`extract_limit`, `null` for all) and Claude's effort (`refresh: true` fetches every page again, for after a parser change); bump `run` to start one with nothing else changed. Extraction needs an `ANTHROPIC_API_KEY` repository secret.

## What is in data/

| Path | What it holds |
| --- | --- |
| `stories/<slug>.json` | One article: title, url, authors, `story_date` (when it first came out; stories from before 2022 were republished, so this is read from the editor's note or the slug), the storyline's chapter list when the page has one, and the paragraphs with their scene numbers |
| `profiles/<slug>.json` | A planeswalker's or plane's bio page under /en/story |
| `archive/<slug>.json`, `cards/<set>.json`, `wiki/<slug>.json` | The older sources, in the same shape (see `mtglore/sources.py`): wizards.com's old columns, each set's flavor text, MTG Wiki articles |
| `bios/<id>.json` | A short bio of one of the most-mentioned entities, every sentence citing what it rests on (see `mtglore/bios.py`) |
| `extracted/{stories,profiles}/<slug>.json` | What Claude found on that page: entities, events and relations. Every event and relation carries a verbatim quote and its paragraph; ones whose quote is not in the page, or that name someone not listed, are under `rejected` |
| `state/batch.json` | The batch in flight, while there is one, so the next run collects it rather than paying twice |
| `eras.json` | When each MTG Wiki section's story is set, so the wiki's undated events can be put in order: `{page: {section: {era, label, date}}}`, where `era` is the set code of the set that told it (or a year), and `date` that set's release date (see `mtglore/eras.py`, `python -m mtglore era-ingest <file>`) |
| `merges.json` | Hand-kept fixes to how names are grouped: `same` (lists of names for one entity), `different` (pairs to keep apart), `rename` (a name to the name the entity should go by), `storylines` (a storyline's name to the spelling to use) |
| `index/entities.json` | Every entity, most pages first: id, name, type, aliases, description, pages, first and last seen |
| `index/entity/<id>.json` | One entity with its `timeline` (events in story order), `relations`, and `pages_say` (what each page says of them) |
| `index/events.json`, `relations.json` | All of them, in story order, each with a `link` that opens the page with the quote highlighted |
| `index/names.json` | Each name and alias, folded to lower case, to the entity ids it may mean |
| `index/storylines.json`, `pages.json` | The storylines and their pages, and every page in story order |
| `index/review.json` | What to look at by hand: aliases more than one entity claims, entities typed differently on different pages, how many facts were rejected, and the pages left out as copies of another |

## Sources and citations

Every fact in the index says where it comes from. Each event, relation and entry in `pages_say` carries a `citation`; each bio sentence carries `citations` (one per event, relation or page it rests on); and each entity carries `description_citations`. `index/sources.json` lists every page the index draws on, with its citation and how many facts come from it.

```json
{"source": "wizards", "official": true, "publisher": "Wizards of the Coast",
 "work": "Jace, Alone", "series": "Magic Story", "authors": ["Alison Lührs"], "date": "2017-09-06",
 "url": "https://magic.wizards.com/en/news/magic-story/jace-alone-2017-09-06",
 "link": "https://magic.wizards.com/en/news/magic-story/jace-alone-2017-09-06#:~:text=…",
 "archived": null, "license": null,
 "text": "\"Jace, Alone\" by Alison Lührs. Magic Story, Wizards of the Coast, 6 Sep 2017."}
```

| `source` | What it is | `url` / `link` |
| --- | --- | --- |
| `wizards` | magic.wizards.com: Magic Story articles and story profiles | the page; `link` scrolls to the quote |
| `wizards-archive` | wizards.com's old story columns (Savor the Flavor, Uncharted Realms, Magic Arcana, features), read from the Internet Archive | `url` is the page as Wizards published it, `archived` the Archive's copy, which `link` opens |
| `card-text` | a card's flavor text; `work` is the card, `series` its set | the card on Scryfall |
| `mtg-wiki` | MTG Wiki, fan-written, so `official` is false. Under CC BY-NC-SA 4.0: where it is shown, show `text` (which credits the wiki's contributors and the licence) and link to `url` | the article |

`text` is a credit line ready to show. An app should show it, or at least the `work` and `publisher`, with every fact, and should keep `official` facts and fan-wiki facts apart.

Story order is the day a page first came out, then its place in its storyline's chapter list. A wiki event has no day of its own, so it takes its section's era from `eras.json` (and carries it as `era`): the release of the set that told that part of the story, so the Brothers' War sorts with Antiquities and the Phyrexian invasion with Invasion. That is the order the story was told in, not in-world chronology.

An old wizards.com column the Internet Archive holds under several dates is indexed once, from its earliest copy; `index/review.json` lists the copies left out.

The text is Wizards of the Coast's. It is kept here, in a private repository, to build the index; what an app shows of it should be the short quotes and the links back.

## The site

`site/` is a static page over the index: search, a page per entity (its bio, timeline, relations and sources, every fact with a chip that shows its quote and links to it), and questions. `python -m mtglore publish` cuts the index down to what the browser loads (`search.json`, one `e/<id>.json` per entity, `meta.json`; quotes only, no page text), and `npm run build` in `site/` bundles the script next to it in `site/dist`. `npm run serve` builds and serves it on port 8000; `npm test` checks the question code.

A question is answered in the browser. The names in it pick the entities (up to three); `site/src/ask.js` takes the facts on them that fit the question best, numbers them, and, if the visitor has added their own Anthropic API key in settings, has Claude write an answer from those facts alone, citing one after every sentence. Sentences that cite nothing, or a fact Claude wasn't given, are dropped before the answer is shown. Without a key the page shows the bios and the facts. The key stays in the visitor's browser and goes straight to Anthropic; the site has no server. A question that names nothing from the story is turned away before any call.

The `Lore site` workflow builds it from the committed index and, when run with "publish", uploads it to the R2 bucket under `lore/`.
