# Mooligan API

A Cloudflare Worker with a D1 database that stores and serves archetype primers and their up/down ratings. Primers are written in Markdown in the playgraph repo and exported to JSON documents; the Worker keeps each document as an opaque blob and never parses its sections.

## Routes

All bodies are JSON. GET routes send `Access-Control-Allow-Origin: *`.

| Route | Description |
| --- | --- |
| `GET /v1/primers` | List of `{ archetype, format, title, updated_at, version, up, down }`. |
| `GET /v1/primers/:archetype` | `{ primer, version, ratings: { up, down } }`. `primer` is the stored document with `author`, `written` and `updated` taken from the database. 404 `{ error }` when missing. `Cache-Control: public, max-age=300`. |
| `GET /v1/primers/:archetype/rating?install=<uuid>` | `{ up, down, mine }` where `mine` is -1, 0 or 1. |
| `PUT /v1/primers/:archetype/rating` | Body `{ install: <uuid>, value: -1 \| 0 \| 1 }`. Upserts the rating, 0 deletes it. Returns `{ up, down, mine }`. 400 on invalid input, 413 over 1 KB, 404 for an unknown primer. |
| `PUT /v1/primers/:archetype` | Admin. `Authorization: Bearer <ADMIN_TOKEN>`. Body `{ author, markdown, document, note? }`. Adds a new version, returns 201 `{ version }`. 401 without the token. |

## Local development

```sh
cd api
npm install
cp .dev.vars.example .dev.vars
npm run migrate:local
npm run dev
```

`.dev.vars` is gitignored and holds `ADMIN_TOKEN` for local runs.

Publish a primer from playgraph (run `npm run export` there first):

```sh
ADMIN_TOKEN=change-me node scripts/publish.mjs http://127.0.0.1:8787 modern-eldrazi \
  ~/Developer/GitHub/playgraph/primers/modern-eldrazi.md \
  ~/Developer/GitHub/playgraph/dist/primers/modern-eldrazi.json
```

With the dev server running, `npm run smoke` publishes both playgraph primers and exercises the routes with curl.

## First deploy

`wrangler.toml` carries a placeholder `database_id`; it is filled in on first deploy. These steps have not been run.

1. `npx wrangler login`
2. `npx wrangler d1 create mooligan`
3. Put the returned `database_id` in `wrangler.toml`.
4. `npx wrangler d1 migrations apply mooligan --remote`
5. `npx wrangler secret put ADMIN_TOKEN`
6. `npx wrangler deploy`
7. In the Cloudflare dashboard, add the route `api.mooligan.com` to the `mooligan-api` Worker.
