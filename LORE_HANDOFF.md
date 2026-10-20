# Lore handoff

The Magic: The Gathering story as data for the Mooligan app: who the characters, planeswalkers, planes and places are, what happened to them, which cards show them, and which characters each set is about. Every fact links to the line it comes from.

**Branches:** `feat/lore` (this handoff) and `claude/lucid-allen-jjvx9l` (where the work happened, and where the publishing workflows run) hold the same commits.

**Published feed:** `https://data.mooligan.com/lore/app/` (uploaded by the `Lore site` workflow).
**Web preview:** `https://data.mooligan.com/lore/index.html`, an unlisted page showing the same data.

## What the app reads

The full schema is in [`docs/data-format.md`](docs/data-format.md#lore-loreapp).

| File | Holds | Key |
| --- | --- | --- |
| `lore/app/cards.json` | Each card to the entities it depicts. A card missing from the map has no lore, so hide "View lore" | Scryfall `oracle_id` |
| `lore/app/sets.json` | Each set's key characters and places (up to 12, most important first), each `main` or `supporting` | Scryfall set code |
| `lore/app/entities.json` | Per entity: name, type, one-sentence summary, the card whose art shows it best (`portrait_oracle_id`), its sets | entity id (`jace-beleren`) |
| `lore/app/entities/{id}.md` | The entity's lore page in playgraph primer markdown | entity id |

The suggested flow:
- **Card screen:** look up `cards.json[oracle_id]`. If it has an entity, "View lore" opens `entities/{id}.md`, using `entities.json[id]` for the header.
- **Set page:** list `sets.json[code]`, each with `entities.json[id].portrait_oracle_id` as its image.

### The `.md` files

They are playgraph primer markdown (`missingems/playgraph`, branch `feat/primers-api`). All 1,605 files parse with its `exportPrimer` without diagnostics.

```
---
id / name / type / title / planes / updated
---
## Who they are     (## What it is for places, factions and artifacts)
## Story           ### one per set (else storyline, era or year), one bullet per event
## Relationships
## Cards           :::cards block of [[Card Name]] lines
## Sources         official credits, then the MTG Wiki pages under their CC BY-NC-SA 4.0 credit
```

- **Citations:** every fact ends with a citation link to the exact line it rests on: `([story](…))`, `([card](…))` or `([MTG Wiki](…))`.
- **Links in playgraph:** the `exportPrimer` on `feat/primers-api` has no link run, so links come through as their text ("(story)") and the URL is dropped. To make citations tappable, playgraph needs a `link` run.
- **Not used:** there are no `card:`/`keyword:` links on that branch, so the files don't use them.

## Coverage (this build)

**Entities with a page:** 1,605 (504 with a written, cited bio), counted in `entities.json` and the `.md` files.

| Type | Entities |
| --- | --- |
| Characters | 1,008 |
| Planeswalkers | 98 |
| Locations | 292 |
| Factions | 100 |
| Planes | 62 |
| Artifacts | 45 |

**Cards mapped to an entity:** 1,721, out of Scryfall's 6,191 legends, planeswalkers, planes and lands.

| Card kind | Mapped |
| --- | --- |
| Planeswalkers | 314 of 348 |
| Legendary creatures | 1,210 of 4,027; most of the rest are minor or Universes Beyond legends the story doesn't cover |
| Plane cards | 98 of 184 |
| Legendary lands | 19 of 98 |

**Portraits:** 1,092 entities have a `portrait_oracle_id`.

**Sets with key characters:** 134, covering every expansion, core and draft-innovation set except:
- Unlimited through Tenth Edition, which only reprint.
- Jumpstart, crossover sets (Lord of the Rings, Final Fantasy, Marvel, TMNT, Assassin's Creed, D&D…), and a few products without a story.

**Behind it:** the index the feed is cut from has 11,952 entities, 26,049 events and 13,701 relations from 3,370 pages. The sources are:
- 484 Magic Story articles and 79 story profiles from magic.wizards.com;
- 225 old wizards.com story columns from the Internet Archive;
- flavor text from 581 sets;
- 2,500+ MTG Wiki articles.

## Where it comes from

Everything is in `lore/` (see [`lore/README.md`](lore/README.md)):

| Step | What it does |
| --- | --- |
| `python -m mtglore scrape`, `scrape-cards`, `scrape-archive`, `scrape-wiki`, `scrape-scryfall` | Fetch the sources into `lore/data/{stories,profiles,cards,archive,wiki,scryfall}`. |
| `lore/data/extracted/` | What Claude found on each page: entities, events and relations, each with a verbatim quote that is checked against the page. |
| `python -m mtglore build` | Builds the index in `lore/data/index`, with bios from `lore/data/bios` and era tags from `lore/data/eras.json`. |
| `python -m mtglore app` | Writes this feed to `lore/site/dist/app`. |
| `python -m mtglore publish` | Writes the web preview's data. |
| `Lore site` workflow | Builds both and uploads them to R2 under `lore/`. It runs on a push to `claude/lucid-allen-jjvx9l` that edits `lore/site/publish.json` (bump `run`), or by hand once the workflow is on `main`. |

**Tests:** `cd lore && python -m pytest`, plus `cd lore/site && npm test`.

## Known gaps and cautions

- **MTG Wiki is CC BY-NC-SA 4.0: non-commercial.** Many facts come from it. Jun decided to keep them: the app is free with no ads. They stay marked `MTG Wiki` and credited in `## Sources`; keep that credit visible wherever they're shown. If the app ever becomes paid or ad-supported, those lines have to go: `python -m mtglore app` would need an official-sources-only mode, leaving out `mtg-wiki` facts.
- **Wizards' text:** pages carry short quotes in their links and summaries written from the sources, not the stories themselves. Keep it that way.
- **Order and eras:** story order is the order the story was published in, not in-world time. Wiki events are dated by the set or year that told them (`eras.json`), and a few dozen of those era tags are best guesses.
- **Card matching** is name-based and deliberately strict. Card names that differ from the character's own name (nicknames, titles, flavor names) stay unmatched rather than guessed. Some aliases in the index are wrong (Ashiok was listed under Jace); the card matcher ignores aliases that don't agree with the entity's own name, but other wrong aliases may still show in entity pages.
- **Merged characters:** two different characters named Finneas are still merged into one entity, and 885 aliases are claimed by more than one entity (`lore/data/index/review.json`).
- **Thin pages:** many minor entities have a description and a few events but no written bio.
- **Not in the feed:** question answering. The web preview asks Claude with the visitor's own key; an app would need an on-device model or a small server.
