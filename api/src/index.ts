interface Env {
  DB: D1Database;
  ADMIN_TOKEN?: string;
}

interface PrimerRow {
  archetype: string;
  format: string;
  title: string;
  current_version: number;
  written_at: string;
  updated_at: string;
  author_name: string;
  document: string;
}

interface Counts {
  up: number;
  down: number;
}

const MAX_RATING_BYTES = 1024;
const MAX_PRIMER_BYTES = 1024 * 1024;
const ARCHETYPE_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

class HTTPError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function readJSON(request: Request, maxBytes: number): Promise<unknown> {
  const declared = Number(request.headers.get("Content-Length") ?? 0);
  if (declared > maxBytes) throw new HTTPError(413, "Body too large");
  const text = await request.text();
  if (new TextEncoder().encode(text).length > maxBytes) throw new HTTPError(413, "Body too large");
  try {
    return JSON.parse(text);
  } catch {
    throw new HTTPError(400, "Body is not valid JSON");
  }
}

async function isAuthorized(request: Request, env: Env): Promise<boolean> {
  const expected = env.ADMIN_TOKEN;
  if (!expected) return false;
  const header = request.headers.get("Authorization") ?? "";
  const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
  const encoder = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

async function counts(db: D1Database, archetype: string): Promise<Counts> {
  const row = await db
    .prepare(
      `SELECT COALESCE(SUM(value = 1), 0) AS up, COALESCE(SUM(value = -1), 0) AS down
       FROM ratings WHERE archetype = ?`,
    )
    .bind(archetype)
    .first<Counts>();
  return { up: row?.up ?? 0, down: row?.down ?? 0 };
}

async function ratingState(db: D1Database, archetype: string, install: string | null) {
  const totals = await counts(db, archetype);
  let mine = 0;
  if (install) {
    const row = await db
      .prepare("SELECT value FROM ratings WHERE archetype = ? AND install_id = ?")
      .bind(archetype, install)
      .first<{ value: number }>();
    mine = row?.value ?? 0;
  }
  return { ...totals, mine };
}

async function primerExists(db: D1Database, archetype: string): Promise<boolean> {
  const row = await db.prepare("SELECT 1 AS found FROM primers WHERE archetype = ?").bind(archetype).first();
  return row !== null;
}

async function getPrimer(env: Env, archetype: string): Promise<Response> {
  const row = await env.DB.prepare(
    `SELECT p.archetype, p.format, p.title, p.current_version, p.written_at, p.updated_at,
            a.name AS author_name, v.document
     FROM primers p
     JOIN primer_versions v ON v.archetype = p.archetype AND v.version = p.current_version
     JOIN authors a ON a.id = v.author_id
     WHERE p.archetype = ?`,
  )
    .bind(archetype)
    .first<PrimerRow>();
  if (!row) return json({ error: "Primer not found" }, 404);

  const document = JSON.parse(row.document) as Record<string, unknown>;
  const primer = {
    ...document,
    archetype: row.archetype,
    format: row.format,
    title: row.title,
    author: row.author_name,
    written: row.written_at.slice(0, 10),
    updated: row.updated_at.slice(0, 10),
  };
  return json({ primer, version: row.current_version, ratings: await counts(env.DB, archetype) }, 200, {
    "Cache-Control": "public, max-age=300",
    ...corsHeaders,
  });
}

async function listPrimers(env: Env): Promise<Response> {
  const { results } = await env.DB.prepare(
    `SELECT p.archetype, p.format, p.title, p.updated_at, p.current_version AS version,
            COALESCE((SELECT SUM(value = 1) FROM ratings r WHERE r.archetype = p.archetype), 0) AS up,
            COALESCE((SELECT SUM(value = -1) FROM ratings r WHERE r.archetype = p.archetype), 0) AS down
     FROM primers p
     ORDER BY p.updated_at DESC, p.archetype`,
  ).all();
  return json(results, 200, { "Cache-Control": "public, max-age=300", ...corsHeaders });
}

async function getRating(env: Env, archetype: string, url: URL): Promise<Response> {
  const install = url.searchParams.get("install");
  if (install !== null && !UUID_PATTERN.test(install)) throw new HTTPError(400, "install must be a UUID");
  return json(await ratingState(env.DB, archetype, install), 200, corsHeaders);
}

async function putRating(env: Env, archetype: string, request: Request): Promise<Response> {
  const body = await readJSON(request, MAX_RATING_BYTES);
  if (!isRecord(body)) throw new HTTPError(400, "Body must be an object");
  const { install, value } = body;
  if (typeof install !== "string" || !UUID_PATTERN.test(install)) throw new HTTPError(400, "install must be a UUID");
  if (value !== -1 && value !== 0 && value !== 1) throw new HTTPError(400, "value must be -1, 0 or 1");
  if (!(await primerExists(env.DB, archetype))) return json({ error: "Primer not found" }, 404);

  const key = install.toLowerCase();
  if (value === 0) {
    await env.DB.prepare("DELETE FROM ratings WHERE archetype = ? AND install_id = ?").bind(archetype, key).run();
  } else {
    await env.DB.prepare(
      `INSERT INTO ratings (archetype, install_id, value, updated_at) VALUES (?, ?, ?, ?)
       ON CONFLICT (archetype, install_id) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
    )
      .bind(archetype, key, value, new Date().toISOString())
      .run();
  }
  return json(await ratingState(env.DB, archetype, key));
}

async function putPrimer(env: Env, archetype: string, request: Request): Promise<Response> {
  if (!(await isAuthorized(request, env))) return json({ error: "Unauthorized" }, 401);

  const body = await readJSON(request, MAX_PRIMER_BYTES);
  if (!isRecord(body)) throw new HTTPError(400, "Body must be an object");
  const { author, markdown, document, note } = body;
  if (typeof author !== "string" || author === "") throw new HTTPError(400, "author is required");
  if (typeof markdown !== "string" || markdown === "") throw new HTTPError(400, "markdown is required");
  if (!isRecord(document)) throw new HTTPError(400, "document must be an object");
  if (note !== undefined && note !== null && typeof note !== "string") throw new HTTPError(400, "note must be a string");
  const { title, format, written } = document;
  if (typeof title !== "string" || title === "") throw new HTTPError(400, "document.title is required");
  if (typeof format !== "string" || format === "") throw new HTTPError(400, "document.format is required");

  const authorRow = await env.DB.prepare("SELECT id FROM authors WHERE id = ?").bind(author).first();
  if (!authorRow) throw new HTTPError(400, "Unknown author");

  const now = new Date().toISOString();
  const writtenAt = typeof written === "string" && DATE_PATTERN.test(written) ? `${written}T00:00:00.000Z` : now;

  const [, , latest] = await env.DB.batch<{ version: number }>([
    env.DB.prepare(
      `INSERT INTO primer_versions (archetype, version, author_id, markdown, document, note, created_at)
       VALUES (?1, (SELECT COALESCE(MAX(version), 0) + 1 FROM primer_versions WHERE archetype = ?1), ?2, ?3, ?4, ?5, ?6)`,
    ).bind(archetype, author, markdown, JSON.stringify(document), note ?? null, now),
    env.DB.prepare(
      `INSERT INTO primers (archetype, format, title, current_version, written_at, updated_at)
       VALUES (?1, ?2, ?3, (SELECT MAX(version) FROM primer_versions WHERE archetype = ?1), ?4, ?5)
       ON CONFLICT (archetype) DO UPDATE SET
         format = excluded.format,
         title = excluded.title,
         current_version = excluded.current_version,
         updated_at = excluded.updated_at`,
    ).bind(archetype, format, title, writtenAt, now),
    env.DB.prepare("SELECT current_version AS version FROM primers WHERE archetype = ?").bind(archetype),
  ]);
  return json({ version: latest.results[0].version }, 201);
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const parts = url.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  const method = request.method;

  if (method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders });
  if (parts[0] !== "v1" || parts[1] !== "primers") return json({ error: "Not found" }, 404);

  const readOnly = method === "GET" || method === "HEAD";

  if (parts.length === 2) {
    if (readOnly) return listPrimers(env);
    return json({ error: "Method not allowed" }, 405, { Allow: "GET, HEAD, OPTIONS" });
  }

  const archetype = parts[2];
  if (!ARCHETYPE_PATTERN.test(archetype) || archetype.length > 64) throw new HTTPError(400, "Invalid archetype");

  if (parts.length === 3) {
    if (readOnly) return getPrimer(env, archetype);
    if (method === "PUT") return putPrimer(env, archetype, request);
    return json({ error: "Method not allowed" }, 405, { Allow: "GET, HEAD, PUT, OPTIONS" });
  }

  if (parts.length === 4 && parts[3] === "rating") {
    if (readOnly) return getRating(env, archetype, url);
    if (method === "PUT") return putRating(env, archetype, request);
    return json({ error: "Method not allowed" }, 405, { Allow: "GET, HEAD, PUT, OPTIONS" });
  }

  return json({ error: "Not found" }, 404);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await route(request, env);
    } catch (error) {
      if (error instanceof HTTPError) return json({ error: error.message }, error.status);
      console.error(error);
      return json({ error: "Internal error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
