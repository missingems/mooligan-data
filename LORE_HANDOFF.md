# Lore handoff

The Magic: The Gathering story as data for the Mooligan app: who the characters, planeswalkers, planes and places are, what happened to them, which cards show them, and which characters each set is about. Every fact links to the line it comes from.

**Branches:** the feed is on `main` (merged in #24). Follow-up work happens on `claude/lucid-allen-jjvx9l`, and `feat/lore` is kept level with it.

**Published feed:** `https://data.mooligan.com/lore/app/` (uploaded by the `Lore site` workflow).
**Web preview:** `https://data.mooligan.com/lore/index.html`, an unlisted page showing the same data.

## What the app reads

The full schema is in [`docs/data-format.md`](docs/data-format.md#lore-loreapp).

| File | Holds | Key |
| --- | --- | --- |
| `lore/app/cards.json` | Each card to the entities it depicts. A card missing from the map has no lore, so hide "View lore" | Scryfall `oracle_id` |
| `lore/app/sets.json` | Each set's key characters and places (up to 12, most important first), each `main` or `supporting`; and `summaries`, a few sentences of each set's story for its About tab | Scryfall set code |
| `lore/app/entities.json` | Per entity: name, type, one-sentence summary, the card whose art shows it best (`portrait_oracle_id`), its sets | entity id (`jace-beleren`) |
| `lore/app/entities/{id}.md` | The entity's lore page in playgraph primer markdown, as prose: who they are, then their story set by set | entity id |
| `lore/app/sets/{code}/{id}.md` | What happened to one of the set's key entities in that set, and a short timeline | set code, entity id |

The suggested flow:
- **Card screen:** look up `cards.json[oracle_id]`. If it has an entity, "View lore" opens `entities/{id}.md`, using `entities.json[id]` for the header.
- **Set page:** list `sets.json.sets[code]`, each with `entities.json[id].portrait_oracle_id` as its image, and `sets.json.summaries[code]` on the About tab. Tapping one opens `sets/{code}/{id}.md`, with the full `entities/{id}.md` below it.

### The `.md` files

They are playgraph primer markdown (`missingems/playgraph`, branch `feat/primers-api`; all 1,903 entity files and 1,662 set files parse without diagnostics), written to be read rather than scanned: prose paragraphs, no citation links and no sources list.

```
---
id / name / type / title / planes / updated / credit
---
## Who they are     (## What it is for places, factions and artifacts)
## Story           ### one per set (else storyline, era or year), one short paragraph each
## Cards           :::cards block of [[Card Name]] lines
```

`sets/{code}/{id}.md` has `id / set / name / title / credit` in its front matter, then `## In {Set Name}` (a paragraph or two) and `## Timeline` (at most 10 short lines).

- **Prose:** the paragraphs for the sets an entity is key to are written by Claude from the index's events for that set (`lore/data/narratives`), like the bios. Each sentence has to cite events from that set, and any quote has to match those events' quotes, or it is dropped. Other sets get a paragraph that tells up to four of their events.
- **Citations** stay in the index (`lore/data/narratives`, `lore/data/bios`), not in the app's files. The web preview still shows them.
- **`credit`:** when any text on the page comes from MTG Wiki, the front matter carries its CC BY-NC-SA 4.0 credit, once. Show it as a footnote. Pages told only from official sources have none.
- **Card links:** `[[Card Name]]` appears in the prose only for the entity's own cards.

## Coverage (this build)

**Entities with a page:** 1,903 (610 with a written bio; the 821 key to a set have story prose for those sets), counted in `entities.json` and the `.md` files.

| Type | Entities |
| --- | --- |
| Characters | 1,228 |
| Planeswalkers | 102 |
| Locations | 331 |
| Factions | 107 |
| Planes | 76 |
| Artifacts | 59 |

**Cards mapped to an entity:** 2,018, out of Scryfall's 4,637 planeswalkers, legendary creatures, plane cards and legendary lands.

| Card kind | Mapped |
| --- | --- |
| Planeswalkers | 317 of 348 |
| Legendary creatures | 1,440 of 4,014; most of the rest are minor or Universes Beyond legends the story doesn't cover |
| Plane cards | 112 of 184 |
| Legendary lands | 24 of 91 |

**Portraits:** 1,376 entities have a `portrait_oracle_id`.

**Sets with key characters:** 141 (1,662 set pages; 140 with a story summary), covering every expansion, core and draft-innovation set except:
- Unlimited through Tenth Edition, which only reprint.
- Jumpstart, crossover sets (Lord of the Rings, Final Fantasy, Marvel, TMNT, Assassin's Creed, D&D…), and a few products without a story.

**Behind it:** the index the feed is cut from has 16,172 entities, 31,674 events and 18,813 relations from 6,682 pages. The sources are:
- 480 Magic Story articles and 79 story profiles from magic.wizards.com;
- 229 old wizards.com story columns from the Internet Archive;
- card flavor text, one page per set (581 sets);
- 5,313 MTG Wiki articles, including the short stub articles.

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

- **MTG Wiki is CC BY-NC-SA 4.0: non-commercial.** Many facts come from it. Jun decided to keep them: the app is free with no ads. Pages that use them carry the credit in their front matter (`credit:`); keep it visible wherever they're shown. If the app ever becomes paid or ad-supported, those lines have to go: `python -m mtglore app` would need an official-sources-only mode, leaving out `mtg-wiki` facts.
- **Wizards' text:** pages carry summaries written from the sources, with at most a short quote inline, not the stories themselves. Keep it that way.
- **Order and eras:** story order is the order the story was published in, not in-world time. Wiki events are dated by the set or year that told them (`eras.json`), and a few dozen of those era tags are best guesses.
- **Card matching** is name-based and deliberately strict. Card names that differ from the character's own name (nicknames, titles, flavor names) stay unmatched rather than guessed. The card matcher also ignores aliases that don't agree with the entity's own name.
- **Names:** `lore/data/merges.json` fixes known mix-ups: wrong aliases (`drop_aliases`), phrases that aren't names (`not_names`), and one name used by two characters (`split`; the two Finneases are now separate). 807 aliases are still claimed by more than one entity (`review.json` in the built index); most are shared titles or family names. Mirri is still one entity covering both the Weatherlight's cat warrior and Sami's cat from Edge of Eternities; her bio says so.
- **Thin pages:** many minor entities have a description and a few events but no written bio.
- **Not in the feed:** question answering. The web preview asks Claude with the visitor's own key; an app would need an on-device model or a small server.
