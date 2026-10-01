# lore

An index of the official Magic story, built from the Magic Story articles and the planeswalker and plane profiles on magic.wizards.com, for answering questions like "who is Jace?" and "what happened to Jace?" with the quote and link behind every fact.

```
python -m mtglore scrape    # every article and profile → data/stories, data/profiles
python -m mtglore extract   # Claude reads each page → data/extracted (Message Batches API)
python -m mtglore build     # one index → data/index
```

Each step only does what is new: scrape skips pages already saved, extract skips pages already extracted with the current `PROMPT_VERSION`, and build is rebuilt from scratch. The `Lore` workflow (`.github/workflows/lore.yml`) runs all three and commits `data/`. It runs every Monday, on demand, and on any push to the branch that edits `run.json`, which sets how many pages to extract (`extract_limit`, `null` for all) and Claude's effort. Extraction needs an `ANTHROPIC_API_KEY` repository secret.

## What is in data/

| Path | What it holds |
| --- | --- |
| `stories/<slug>.json` | One article: title, url, authors, `story_date` (when it first came out; stories from before 2022 were republished, so this is read from the editor's note or the slug), the storyline's chapter list when the page has one, and the paragraphs with their scene numbers |
| `profiles/<slug>.json` | A planeswalker's or plane's bio page under /en/story |
| `extracted/{stories,profiles}/<slug>.json` | What Claude found on that page: entities, events and relations. Every event and relation carries a verbatim quote and its paragraph; ones whose quote is not in the page, or that name someone not listed, are under `rejected` |
| `state/batch.json` | The batch in flight, while there is one, so the next run collects it rather than paying twice |
| `merges.json` | Hand-kept fixes to how names are grouped: `same` (lists of names for one entity), `different` (pairs to keep apart), `rename` (a name to the name the entity should go by) |
| `index/entities.json` | Every entity, most pages first: id, name, type, aliases, description, pages, first and last seen |
| `index/entity/<id>.json` | One entity with its `timeline` (events in story order), `relations`, and `pages_say` (what each page says of them) |
| `index/events.json`, `relations.json` | All of them, in story order, each with a `link` that opens the page with the quote highlighted |
| `index/names.json` | Each name and alias, folded to lower case, to the entity ids it may mean |
| `index/storylines.json`, `pages.json` | The storylines and their pages, and every page in story order |
| `index/review.json` | What to look at by hand: aliases more than one entity claims, entities typed differently on different pages, how many facts were rejected |

Story order is the day a page first came out, then its place in its storyline's chapter list.

The text is Wizards of the Coast's. It is kept here, in a private repository, to build the index; what an app shows of it should be the short quotes and the links back.
