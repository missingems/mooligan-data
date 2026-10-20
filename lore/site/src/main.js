// Routes: #/ home, #/e/<id> an entity, #/ask?q=<question> an answer.
import { MODELS, check, explain, retrieve, write } from "./ask.js";
import { entity, meta, namedIn, search, suggest } from "./data.js";
import { renderEntity } from "./entity.js";
import { chip, h, hidePop, installPopover, link } from "./ui.js";

const view = document.getElementById("view");
const input = document.getElementById("q");
const list = document.getElementById("suggest");

const store = {
  get(key) { try { return localStorage.getItem(`lore.${key}`) || ""; } catch { return ""; } },
  set(key, value) { try { value ? localStorage.setItem(`lore.${key}`, value) : localStorage.removeItem(`lore.${key}`); } catch { /* private mode */ } },
};

let current = null; // the answer in flight, so a new question can stop it

async function route() {
  hidePop();
  if (current) { current.abort(); current = null; }
  const hash = location.hash.slice(1) || "/";
  const [path, query = ""] = hash.split("?");
  window.scrollTo(0, 0);
  try {
    if (path.startsWith("/e/")) {
      view.replaceChildren(h("p", { class: "muted" }, "Loading…"));
      input.value = "";
      const page = await entity(decodeURIComponent(path.slice(3)));
      document.title = `${page.name} · Lore Index`;
      renderEntity(view, page);
    } else if (path === "/ask") {
      const question = new URLSearchParams(query).get("q") || "";
      input.value = question;
      document.title = `${question} · Lore Index`;
      await renderAsk(question);
    } else {
      document.title = "Lore Index";
      input.value = "";
      await renderHome();
    }
  } catch (error) {
    view.replaceChildren(h("h1", {}, "Not found"), h("p", { class: "muted" }, "That page isn't in the index."), h("a", { href: "#/" }, "Back to the start"));
    console.error(error);
  }
  view.focus({ preventScroll: true });
}

async function renderHome() {
  const index = await search();
  const top = (types, n) => index.entities.filter((e) => types.includes(e.type)).slice(0, n);
  const cards = (items) => h("div", { class: "grid" }, items.map((e) => h("a", { class: "card", href: `#/e/${encodeURIComponent(e.id)}` }, h("b", {}, e.name), h("span", {}, e.description))));
  const examples = ["Who is Jace Beleren?", "What happened to Urza?", "Who killed Elspeth?", "How did Nicol Bolas lose his power?", "What is the Mending?", "Who is Sheoldred?"];
  view.replaceChildren(
    h("section", { class: "hero" },
      h("h1", {}, "The Magic story, with sources"),
      h("p", {}, `Search ${index.entities.length.toLocaleString()} characters, planes, factions and events, or ask a question. Every fact links to the line it came from.`),
      h("div", { class: "examples" }, examples.map((q) => h("a", { href: `#/ask?q=${encodeURIComponent(q)}` }, q)))),
    h("h2", {}, "Characters"), cards(top(["character"], 18)),
    h("h2", {}, "Planes"), cards(top(["plane"], 9)),
    h("h2", {}, "Factions and events"), cards(top(["faction", "event"], 9)),
  );
}

async function renderAsk(question) {
  const index = await search();
  const named = namedIn(index, question).slice(0, 3);
  if (!named.length) {
    view.replaceChildren(
      h("h1", {}, question),
      h("div", { class: "ask" }, h("p", {}, "I couldn't find a character, place or event from the Magic story in that question. Try naming one, like “What happened to Gideon?”"),
        suggestionsFor(index, question)));
    return;
  }
  const pages = await Promise.all(named.map((e) => entity(e.id)));
  const chosen = retrieve(question, pages);
  const about = h("p", { class: "note" }, "About ", named.map((e, i) => [i ? ", " : "", link(e.id, e.name)]), ` · ${chosen.length} facts found`);
  const answer = h("div", { class: "answer" });
  const box = h("div", { class: "ask" }, about, answer);
  view.replaceChildren(h("h1", {}, question), box, h("h2", {}, "The facts"), factList(chosen));

  const key = store.get("key");
  if (!key) {
    const bios = pages.filter((p) => p.bio && p.bio.summary);
    answer.replaceChildren(
      ...bios.map((p) => h("p", {}, h("b", {}, p.name), ": ", p.bio.summary.text, p.bio.status ? ` ${p.bio.status.text}` : "")),
      h("p", { class: "note" }, "Below are the facts the index holds that fit the question. To have Claude write them up into an answer, add your Anthropic API key in ",
        h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); openSettings(); } }, "settings"), "."));
    return;
  }
  const model = MODELS.includes(store.get("model")) ? store.get("model") : MODELS[0];
  const controller = new AbortController();
  current = controller;
  answer.replaceChildren(h("p", { class: "cursor" }));
  try {
    const { text, stop, model: served } = await write({
      key, model, question, chosen, pages, signal: controller.signal,
      onText: (sofar) => { answer.replaceChildren(h("p", { class: "cursor" }, sofar.replace(/\s*\[F\d+\]/g, ""))); },
    });
    if (current === controller) current = null;
    const trimmed = text.trim();
    if (stop === "refusal") return answer.replaceChildren(h("p", {}, "Claude declined to answer this one. The facts below are what the index holds."));
    if (trimmed === "NOT_MTG") return answer.replaceChildren(h("p", {}, "That doesn't look like a question about the Magic story."));
    if (trimmed === "NOT_COVERED") return answer.replaceChildren(h("p", {}, "The facts the index holds don't answer that. Here is what it has on the subject."));
    const { paragraphs, dropped } = check(trimmed, chosen);
    answer.replaceChildren(
      ...paragraphs.map((sentences) => h("p", {}, sentences.map((s) => [s.text, ...s.cites.map((c) => chip(c.label.slice(1), c.fact)), " "]))),
      h("p", { class: "note" },
        `Written by ${served || model} from the facts below.`,
        dropped ? ` ${dropped} sentence${dropped === 1 ? " was" : "s were"} left out because ${dropped === 1 ? "it" : "they"} cited no fact.` : "",
        stop === "max_tokens" ? " The answer was cut off at its length limit." : ""));
  } catch (error) {
    if (controller.signal.aborted) return;
    answer.replaceChildren(h("p", {}, explain(error)));
  }
}

function factList(chosen) {
  if (!chosen.length) return h("p", { class: "muted" }, "None.");
  return h("ul", { class: "facts-list" }, chosen.map((c) => h("li", {},
    h("span", { class: "small muted sans" }, c.label.slice(1), ". ", c.fact.label, " · ", c.fact.source.work, " "),
    h("div", {}, c.fact.text || c.fact.quote, " ", chip("quote", c.fact)))));
}

function suggestionsFor(index, text) {
  const words = text.split(/\s+/).filter((w) => w.length > 3);
  const found = words.flatMap((w) => suggest(index, w, 3).filter((e) => [e.name, ...e.aliases].some((n) => n.toLowerCase().startsWith(w.toLowerCase()))));
  const unique = [...new Map(found.map((e) => [e.id, e])).values()].slice(0, 6);
  return unique.length ? h("p", { class: "note" }, "Did you mean: ", unique.map((e, i) => [i ? ", " : "", link(e.id, e.name)])) : null;
}

// The search box: suggestions as you type; Enter opens the highlighted one, or asks the question.
let options = [];
let selected = -1;
function drawSuggestions(items) {
  options = items;
  selected = -1;
  list.replaceChildren(...items.map((item, i) => h("li", { role: "option", "aria-selected": "false", onmousedown: (ev) => { ev.preventDefault(); choose(i); } },
    item.ask ? [h("span", { class: "ask" }, "Ask"), item.text] : [h("b", {}, item.e.name), h("span", { class: "small muted" }, item.e.type)])));
  list.hidden = !items.length;
}
function choose(i) {
  const item = options[i];
  list.hidden = true;
  input.blur();
  location.hash = item.ask ? `#/ask?q=${encodeURIComponent(item.text)}` : `#/e/${encodeURIComponent(item.e.id)}`;
}
input.addEventListener("input", async () => {
  const text = input.value.trim();
  if (!text) return drawSuggestions([]);
  const index = await search();
  const items = suggest(index, text, 7).map((e) => ({ e }));
  const question = text.split(/\s+/).length > 2 || /\?$/.test(text);
  drawSuggestions(question ? [{ ask: true, text }, ...items] : [...items, { ask: true, text }]);
});
input.addEventListener("keydown", (ev) => {
  if (list.hidden) return;
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    selected = (selected + (ev.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
    [...list.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === selected)));
  } else if (ev.key === "Escape") list.hidden = true;
});
input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 100));
document.getElementById("search").addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (options.length) choose(selected >= 0 ? selected : 0);
  else if (input.value.trim()) location.hash = `#/ask?q=${encodeURIComponent(input.value.trim())}`;
});

// Settings: the visitor's Claude key and model, kept in this browser.
const dialog = document.getElementById("settings");
function openSettings() {
  document.getElementById("key").value = store.get("key");
  document.getElementById("model").value = MODELS.includes(store.get("model")) ? store.get("model") : MODELS[0];
  dialog.showModal();
}
document.getElementById("settings-open").addEventListener("click", openSettings);
dialog.addEventListener("close", () => {
  if (dialog.returnValue === "save") {
    store.set("key", document.getElementById("key").value.trim());
    store.set("model", document.getElementById("model").value);
  } else if (dialog.returnValue === "clear") {
    store.set("key", "");
  }
  if (location.hash.startsWith("#/ask")) route();
});

meta().then((m) => {
  document.getElementById("meta").textContent = `${m.entities.toLocaleString()} entities, ${m.events.toLocaleString()} events from ${m.pages.toLocaleString()} pages · built ${m.built}`;
}).catch(() => {});

installPopover();
window.addEventListener("hashchange", route);
route();
