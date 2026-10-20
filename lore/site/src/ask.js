// Answering a question: find what it is about, pull the facts the index holds on it, and (with the visitor's own
// Claude key) have Claude write them up. Claude sees only those facts and must cite one after every sentence;
// a sentence that cites nothing, or a fact it wasn't given, is dropped before it is shown.
import Anthropic from "@anthropic-ai/sdk";
import { fold } from "./data.js";
import { factsOf } from "./ui.js";

const MAX_EVENTS = 40;
const MAX_RELATIONS = 12;
const MAX_SAID = 6;

const STOP = new Set(`a an the of to in on at by for from with and or but is are was were be been do does did what who whom whose which
when where why how that this it its he him his she her they them their about tell me us did happened happen after before
during story magic mtg`.split(/\s+/));

const stem = (word) => word.slice(0, 5);

// The facts on these entities that best fit the question, numbered F1, F2… in story order.
export function retrieve(question, pages) {
  const nameWords = new Set(pages.flatMap((p) => fold(`${p.name} ${p.aliases.join(" ")}`).split(" ")));
  const keywords = [...new Set(fold(question).split(" ").filter((w) => w.length > 2 && !STOP.has(w) && !nameWords.has(w)).map(stem))];
  const ids = new Set(pages.map((p) => p.id));
  const scored = [];
  const seen = new Set();
  for (const page of pages) {
    const facts = factsOf(page);
    for (const [id, fact] of facts) {
      if (seen.has(id)) continue;
      seen.add(id);
      const words = fold(`${fact.text} ${fact.quote}`).split(" ").map(stem);
      let score = keywords.filter((k) => words.includes(k)).length * 3;
      if (fact.kind === "event") {
        if (fact.item.major) score += 1;
        const together = fact.item.who.filter((w) => ids.has(w)).length;
        if (pages.length > 1 && together > 1) score += 4;
      } else if (fact.kind === "relation") {
        if (pages.length > 1 && ids.has(fact.item.source) && ids.has(fact.item.target)) score += 5;
      } else {
        score += fact.source.official ? 1 : 0.5;
      }
      scored.push({ id, fact, score, page });
    }
  }
  const pick = (kind, limit) => {
    const items = scored.filter((s) => s.fact.kind === kind);
    if (!keywords.length && kind === "event" && items.length > limit) {
      // No particular topic: the turning points, spread over the whole story.
      const major = items.filter((s) => s.fact.item.major);
      const pool = major.length >= limit / 2 ? major : items;
      const step = pool.length / limit;
      return pool.length <= limit ? pool : Array.from({ length: limit }, (_, i) => pool[Math.floor(i * step)]);
    }
    return items.map((s, i) => ({ s, i })).sort((a, b) => b.s.score - a.s.score || a.i - b.i).slice(0, limit).map((x) => x.s);
  };
  const chosen = [...pick("said", MAX_SAID), ...pick("event", MAX_EVENTS), ...pick("relation", MAX_RELATIONS)];
  chosen.sort((a, b) => (a.fact.when || "9999").localeCompare(b.fact.when || "9999"));
  return chosen.map((c, i) => ({ ...c, label: `F${i + 1}` }));
}

const names = (pages) => Object.assign({}, ...pages.map((p) => ({ ...p.names, [p.id]: p.name })));

function factLine(c, nameOf) {
  const f = c.fact;
  const where = [f.when ? f.when.slice(0, 4) : "", f.source.work, f.source.official ? "official" : "fan wiki"].filter(Boolean).join(", ");
  let text = f.text;
  if (f.kind === "relation") text = `${nameOf(f.item.source)} ${f.item.relation.replace("_", " ")} ${nameOf(f.item.target)}${f.text ? `: ${f.text}` : ""}`;
  if (f.kind === "said") text = `${nameOf(c.page.id)}: ${f.text}`;
  return `[${c.label}] (${where}) ${text}${f.quote ? ` Quote: "${f.quote}"` : ""}`;
}

const SYSTEM = `You answer questions about the Magic: The Gathering story for fans, using only the numbered facts you are given. Each fact comes from an official Wizards of the Coast source or from MTG Wiki (marked "fan wiki").

- Use only these facts. Do not add anything from your own knowledge, even where you know more or think a fact is wrong.
- End every sentence with the ids of the facts it rests on, in square brackets, like [F3] or [F3][F12]. A sentence with no id is deleted before the reader sees it.
- Tell what happened in story order, in plain prose: two to five short paragraphs, no headings or lists.
- If a point rests only on fan-wiki facts, say "according to MTG Wiki".
- If the facts don't answer the question, reply with exactly NOT_COVERED and nothing else.
- If the question is not about the Magic: The Gathering story, reply with exactly NOT_MTG and nothing else.`;

export function prompt(question, chosen, pages) {
  const all = names(pages);
  const nameOf = (id) => all[id] || id;
  return `Facts:\n${chosen.map((c) => factLine(c, nameOf)).join("\n")}\n\nQuestion: ${question}`;
}

// Splits an answer into sentences with the facts each cites; drops what cites nothing or cites a fact it wasn't given.
export function check(text, chosen) {
  const known = new Map(chosen.map((c) => [c.label, c]));
  const paragraphs = [];
  let dropped = 0;
  for (const block of text.split(/\n\s*\n/)) {
    const sentences = [];
    const pattern = /([^\[]*?\S[^\[]*?)((?:\s*\[F\d+\])+)\s*([.!?…]?)(?=\s|$)/g;
    let match, end = 0;
    while ((match = pattern.exec(block))) {
      const labels = [...match[2].matchAll(/F\d+/g)].map((m) => m[0]);
      // Only the last sentence before the ids is backed by them; any before it cited nothing.
      const pieces = match[1].trim().split(/(?<=[.!?…]["”’']?)\s+/);
      dropped += pieces.length - 1;
      const sentence = (pieces[pieces.length - 1] + match[3]).trim();
      if (!labels.every((l) => known.has(l))) { dropped += 1; end = pattern.lastIndex; continue; }
      sentences.push({ text: sentence, cites: [...new Set(labels)].map((l) => known.get(l)) });
      end = pattern.lastIndex;
    }
    if (block.slice(end).trim()) dropped += 1;
    if (sentences.length) paragraphs.push(sentences);
  }
  return { paragraphs, dropped };
}

export const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];

// Streams Claude's answer; onText gets the text so far. Resolves to { text, stop }.
export async function write({ key, model, question, chosen, pages, onText, signal }) {
  const client = new Anthropic({ apiKey: key, dangerouslyAllowBrowser: true });
  const params = {
    model,
    max_tokens: 4000,
    system: SYSTEM,
    output_config: { effort: "low" },
    messages: [{ role: "user", content: prompt(question, chosen, pages) }],
  };
  // Opus and Sonnet: if a safety check declines, the API retries on a fallback model in the same call.
  if (model !== "claude-haiku-5-5") Object.assign(params, { betas: ["server-side-fallback-2026-07-01"], fallbacks: "default" });
  const stream = client.beta.messages.stream(params, { signal });
  let text = "";
  for await (const event of stream) {
    if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
      text += event.delta.text;
      onText(text);
    }
  }
  const message = await stream.finalMessage();
  return { text, stop: message.stop_reason, model: message.model };
}

export function explain(error) {
  if (error instanceof Anthropic.AuthenticationError) return "That API key was not accepted. Check it in settings (⚙).";
  if (error instanceof Anthropic.PermissionDeniedError) return "That API key doesn't have access to this model. Try another model in settings (⚙).";
  if (error instanceof Anthropic.RateLimitError) return "Anthropic is rate-limiting this key. Wait a moment and try again.";
  if (error instanceof Anthropic.APIError) return `Claude returned an error (${error.status ?? "network"}): ${error.message}`;
  return `Something went wrong: ${error.message}`;
}
