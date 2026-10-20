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

They are playgraph primer markdown (`missingems/playgraph`, branch `feat/primers-api`). All 1,799 files parse with its `exportPrimer` without diagnostics.

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
- **Links in playgraph:** `exportPrimer` gets a `{ t: "link", href, label }` run in [missingems/playgraph#1](https://github.com/missingems/playgraph/pull/1) (branch `feat/primer-links`, into `feat/primers-api`). Once that is merged, citations come through as tappable links; before it, they come through as their text ("(story)") and the URL is dropped.
- **Not used:** there are no `card:`/`keyword:` links on that branch, so the files don't use them.

## Coverage (this build)

**Entities with a page:** 1,799 (612 with a written, cited bio), counted in `entities.json` and the `.md` files.

| Type | Entities |
| --- | --- |
| Characters | 1,152 |
| Planeswalkers | 98 |
| Locations | 321 |
| Factions | 106 |
| Planes | 74 |
| Artifacts | 48 |

**Cards mapped to an entity:** 1,926, out of Scryfall's 4,637 planeswalkers, legendary creatures, plane cards and legendary lands.

| Card kind | Mapped |
| --- | --- |
| Planeswalkers | 313 of 348 |
| Legendary creatures | 1,372 of 4,014; most of the rest are minor or Universes Beyond legends the story doesn't cover |
| Plane cards | 112 of 184 |
| Legendary lands | 17 of 91 |

**Portraits:** 1,285 entities have a `portrait_oracle_id`.

**Sets with key characters:** 134, covering every expansion, core and draft-innovation set except:
- Unlimited through Tenth Edition, which only reprint.
- Jumpstart, crossover sets (Lord of the Rings, Final Fantasy, Marvel, TMNT, Assassin's Creed, D&D…), and a few products without a story.

**Behind it:** the index the feed is cut from has 14,191 entities, 30,994 events and 17,542 relations from 6,293 pages. The sources are:
- 480 Magic Story articles and 79 story profiles from magic.wizards.com;
- 229 old wizards.com story columns from the Internet Archive;
- card flavor text, one page per set (320 sets);
- 5,185 MTG Wiki articles, including the short stub articles.

## Where it comes from

Everything is in `lore/` (see [`lore/README.md`](lore/README.md)):

| Step | What it does |
| --- | --- |
| `python -m mtglore scrape`, `scrape-cards`, `scrape-archive`, `scrape-wiki`, `scrape-scryfall` | Fetch the sources into `lore/data/{stories,profiles,cards,archive,wiki,scryfall}`. |
| `lore/data/extracted/` | What Claude found on each page: entities, events and relations, each with a verbatim quote that is checked against the page. |
| `python -m mtglore build` | Builds the index in `lore/data/index` (not committed; CI rebuilds it), with bios from `lore/data/bios`, era tags from `lore/data/eras.json` and name fixes from `lore/data/merges.json`. |
| `python -m mtglore app` | Writes this feed to `lore/site/dist/app`. |
| `python -m mtglore publish` | Writes the web preview's data. |
| `Lore site` workflow | Builds the index, both outputs, and uploads them to R2 under `lore/`. It runs after the weekly `Lore` run, on a push to `claude/lucid-allen-jjvx9l` that edits `lore/site/publish.json` (bump `run`), or by hand once the workflow is on `main`. |
| `Lore` workflow | Weekly: scrapes new chapters, extracts them with Claude, then calls `Lore site` so they reach the app. Extraction needs an `ANTHROPIC_API_KEY` repository secret. New bios are not written by it. |

**Tests:** `cd lore && python -m pytest`, plus `cd lore/site && npm test`.

## Known gaps and cautions

- **MTG Wiki is CC BY-NC-SA 4.0: non-commercial.** Many facts come from it. Jun decided to keep them: the app is free with no ads. They stay marked `MTG Wiki` and credited in `## Sources`; keep that credit visible wherever they're shown. If the app ever becomes paid or ad-supported, those lines have to go: `python -m mtglore app` would need an official-sources-only mode, leaving out `mtg-wiki` facts.
- **Wizards' text:** pages carry short quotes in their links and summaries written from the sources, not the stories themselves. Keep it that way.
- **Order and eras:** story order is the order the story was published in, not in-world time. Wiki events are dated by the set or year that told them (`eras.json`), and a few dozen of those era tags are best guesses.
- **Card matching** is name-based and deliberately strict. Card names that differ from the character's own name (nicknames, titles, flavor names) stay unmatched rather than guessed. The card matcher also ignores aliases that don't agree with the entity's own name.
- **Names:** `lore/data/merges.json` fixes known mix-ups: wrong aliases (`drop_aliases`), phrases that aren't names (`not_names`), and one name used by two characters (`split`; the two Finneases are now separate). 725 aliases are still claimed by more than one entity (`review.json` in the built index); most are shared titles or family names. Mirri is still one entity covering both the Weatherlight's cat warrior and Sami's cat from Edge of Eternities; her bio says so.
- **Thin pages:** many minor entities have a description and a few events but no written bio.
- **Not in the feed:** question answering. The web preview asks Claude with the visitor's own key; an app would need an on-device model or a small server.
