// Loads the published index (data/) and finds entities by name.

const cache = new Map();

async function json(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(`data/${path}`).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

export const meta = () => json("meta.json");
export const entity = (id) => json(`e/${encodeURIComponent(id)}.json`);

let searchIndex = null;

// Every entity, most pages first, plus a map from each folded name and alias to the entities it may mean.
export async function search() {
  if (searchIndex) return searchIndex;
  const entities = await json("search.json");
  const byName = new Map();
  for (const e of entities) {
    for (const name of [e.name, ...e.aliases]) {
      const key = fold(name);
      if (!key) continue;
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key).push(e);
    }
  }
  searchIndex = { entities, byName, byId: new Map(entities.map((e) => [e.id, e])) };
  return searchIndex;
}

export function fold(text) {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[’']/g, "'").replace(/[^a-z0-9' -]+/g, " ").replace(/\s+/g, " ").trim();
}

// Suggestions for what is typed in the search box: names that start with it first, then names containing it.
export function suggest(index, text, limit = 8) {
  const q = fold(text);
  if (!q) return [];
  const starts = [], contains = [];
  const seen = new Set();
  for (const e of index.entities) {
    const names = [e.name, ...e.aliases].map(fold);
    if (names.some((n) => n.startsWith(q) || n.includes(` ${q}`))) starts.push(e);
    else if (q.length > 2 && names.some((n) => n.includes(q))) contains.push(e);
    if (starts.length >= limit) break;
  }
  return [...starts, ...contains].filter((e) => !seen.has(e.id) && seen.add(e.id)).slice(0, limit);
}

// Words that never name an entity on their own, however an alias is spelled.
const COMMON = new Set(`a an the of to in on at by for from with and or but not no is are was were be been being am do does did done
have has had who whom whose what which when where why how that this these those there here it its he him his she her they them
their we us our you your i me my mine all any some each every more most other such only own same so than too very can will just
should now then once about after before again against between into through during above below up down out off over under further
happened happen happens become became story stories tell told know about kill killed killing die died death dead live lives living
did first last new old best good great war world man woman king queen lord lady god gods city plane planes magic power fight
love loves loved friend friends enemy enemies family brother sister father mother son daughter`.split(/\s+/));

// The entities a question names, longest names first, each the best-known holder of that name.
export function namedIn(index, question) {
  const words = fold(question).split(" ").filter(Boolean);
  const found = [];
  const used = new Array(words.length).fill(false);
  for (let size = Math.min(6, words.length); size >= 1; size--) {
    for (let start = 0; start + size <= words.length; start++) {
      if (used.slice(start, start + size).some(Boolean)) continue;
      const phrase = words.slice(start, start + size).join(" ");
      if (size === 1 && (COMMON.has(phrase) || phrase.length < 3)) continue;
      const matches = index.byName.get(phrase) || index.byName.get(phrase.replace(/'s$/, ""));
      if (!matches) continue;
      const best = matches.reduce((a, b) => (b.pages > a.pages ? b : a));
      if (!found.some((e) => e.id === best.id)) found.push(best);
      for (let i = start; i < start + size; i++) used[i] = true;
    }
  }
  return found;
}
