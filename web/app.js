import { createApi } from "./api.js";
import config from "./config.js";

const view = document.getElementById("view");
const dialog = document.getElementById("card-dialog");
const apiReady = createApi();
let renderToken = 0;

// ---- DOM helpers: every value goes through textContent or an attribute, never innerHTML.

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "style") for (const [property, css] of Object.entries(value)) node.style.setProperty(property, css);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

const titleCase = (text) => text.replace(/(^|[\s_-])(\w)/g, (_, gap, letter) => gap.replace(/[_-]/, " ") + letter.toUpperCase());
const formatDate = (iso) =>
  new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const timeframeLabel = (timeframe) => timeframe.replace(/^(\d+)d$/, (_, days) => `${days} days`);
const count = (cards) => cards.reduce((sum, card) => sum + card.quantity, 0);

// ---- Routing: #/<format>[?t=<timeframe>], #/<format>/event/<id>, #/deck/<id>

function parseRoute() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query);
  if (parts[0] === "deck" && parts[1]) return { name: "deck", deckId: parts[1] };
  const format = config.formats.includes(parts[0]) ? parts[0] : config.formats[0];
  if (parts[1] === "event" && parts[2]) return { name: "event", format, eventId: parts[2] };
  const timeframe = config.timeframes.includes(params.get("t")) ? params.get("t") : config.timeframes[0];
  return { name: "meta", format, timeframe };
}

async function render() {
  const token = ++renderToken;
  const route = parseRoute();
  renderFormatNav(route.format);
  view.replaceChildren(el("p", { class: "status" }, "Loading…"));
  try {
    const api = await apiReady;
    showSourceNotice(api.source);
    const content =
      route.name === "deck"
        ? await deckView(api, route)
        : route.name === "event"
          ? await eventView(api, route)
          : await metaView(api, route);
    if (token === renderToken) view.replaceChildren(content);
  } catch (error) {
    if (token !== renderToken) return;
    view.replaceChildren(
      el("p", { class: "status error" }, error.code === "not-found" ? error.message : `Something went wrong: ${error.message}`),
    );
  }
}

function renderFormatNav(current) {
  document.querySelector(".formats").replaceChildren(
    ...config.formats.map((format) =>
      el("a", { href: `#/${format}`, "aria-current": format === current ? "page" : undefined }, titleCase(format)),
    ),
  );
}

function showSourceNotice(source) {
  const notice = document.querySelector(".notice");
  notice.hidden = source !== "sample";
  notice.textContent =
    "Showing a bundled sample from MTGGoldfish (Modern only). Add your Firebase web config to web/config.js to show live data.";
}

// ---- Views

async function metaView(api, { format, timeframe }) {
  const [meta, { events }] = await Promise.all([
    api.getMeta({ format, timeframe }).catch((error) => (error.code === "not-found" ? null : Promise.reject(error))),
    api.getEvents({ format, limit: 15 }),
  ]);
  document.title = `${titleCase(format)} metagame · MTG Metagame`;

  const timeframes = el(
    "nav",
    { class: "segmented", "aria-label": "Timeframe" },
    config.timeframes.map((option) =>
      el("a", { href: `#/${format}?t=${option}`, "aria-current": option === timeframe ? "true" : undefined }, timeframeLabel(option)),
    ),
  );

  return el(
    "div",
    {},
    el(
      "div",
      { class: "page-head" },
      el("div", {}, el("h1", {}, `${titleCase(format)} metagame`),
        el("p", {}, meta ? `Updated ${formatDate(meta.last_updated)}` : "No metagame scraped yet for this timeframe.")),
      timeframes,
    ),
    el("div", { class: "grid" }, metaPanel(meta), eventsPanel(format, events)),
  );
}

function metaPanel(meta) {
  const panel = el("section", { class: "panel" });
  if (!meta) return panel;
  const archetypes = [...meta.archetypes].sort((a, b) => b.percentage - a.percentage);
  const top = archetypes[0]?.percentage || 1;
  const list = el("ol", { class: "meta-list" });
  const renderRows = (limit) =>
    list.replaceChildren(
      ...archetypes.slice(0, limit).map((archetype) =>
        el(
          "li",
          { class: "meta-row" },
          el(
            "a",
            {
              class: "name",
              href: `https://www.mtggoldfish.com/archetype/${encodeURIComponent(archetype.id)}`,
              target: "_blank",
              rel: "noopener",
              style: { "--share": `${(archetype.percentage / top) * 100}%` },
            },
            archetype.name,
          ),
          el("span", { class: "pct" }, `${archetype.percentage.toFixed(1)}%`,
            archetype.deck_count != null ? el("small", {}, `${archetype.deck_count} decks`) : null),
        ),
      ),
    );
  renderRows(20);
  const children = [el("h2", {}, "Archetypes", el("small", {}, `${archetypes.length} tracked`)), list];
  if (archetypes.length > 20) {
    const more = el("button", { class: "show-all", type: "button", onclick: () => { renderRows(Infinity); more.remove(); } },
      `Show all ${archetypes.length}`);
    children.push(more);
  }
  panel.append(...children);
  return panel;
}

function eventsPanel(format, events) {
  return el(
    "section",
    { class: "panel" },
    el("h2", {}, "Recent events"),
    events.length === 0
      ? el("p", { class: "status" }, "No events scraped yet.")
      : el(
          "ul",
          { class: "event-list" },
          events.map((event) => {
            const winner = event.results[0];
            return el(
              "li",
              {},
              el("a", { href: `#/${format}/event/${encodeURIComponent(event.event_id)}` }, event.event_name),
              el("div", { class: "sub" },
                [formatDate(event.date), `${event.results.length} decks`, winner ? `${winner.finish}: ${winner.archetype}` : null]
                  .filter(Boolean).join(" · ")),
            );
          }),
        ),
  );
}

async function eventView(api, { format, eventId }) {
  // There is no single-event callable; the event is among the format's recent ones.
  const { events } = await api.getEvents({ format, limit: 100 });
  const event = events.find((candidate) => candidate.event_id === eventId);
  if (!event) throw Object.assign(new Error(`Event ${eventId} is not among recent ${titleCase(format)} events.`), { code: "not-found" });
  document.title = `${event.event_name} · MTG Metagame`;
  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, event.event_name),
        el("p", {}, `${titleCase(event.format)} · ${formatDate(event.date)} · `,
          el("a", { href: event.url ?? `https://www.mtggoldfish.com/tournament/${eventId}`, target: "_blank", rel: "noopener" }, "MTGGoldfish"))),
      el("a", { href: `#/${format}` }, `← ${titleCase(format)} metagame`)),
    el("section", { class: "panel" },
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Finish"), el("th", {}, "Deck"), el("th", {}, "Player"))),
        el("tbody", {}, event.results.map((result) =>
          el("tr", {},
            el("td", { class: "finish" }, result.finish),
            el("td", {}, el("a", { href: `#/deck/${encodeURIComponent(result.deck_id)}?event=${encodeURIComponent(eventId)}&format=${format}` }, result.archetype)),
            el("td", {}, result.player)))))),
  );
}

async function deckView(api, { deckId }) {
  const deck = await api.getDecklist({ deck_id: deckId });
  document.title = `${deck.archetype} by ${deck.player} · MTG Metagame`;
  const backParams = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const format = deck.format ?? backParams.get("format");
  const eventId = deck.event_id ?? backParams.get("event");
  const back = format && eventId ? el("a", { href: `#/${format}/event/${encodeURIComponent(eventId)}` }, "← Event") : null;

  const board = (title, cards) =>
    el("section", {},
      el("h2", {}, `${title} (${count(cards)})`),
      el("ul", { class: "deck-list" }, cards.map((card) =>
        el("li", {},
          el("span", { class: "qty" }, card.quantity),
          el("button", { class: "card-link", type: "button", onclick: () => showCard(api, card.card_name, format) }, card.card_name)))));

  const copy = el("button", {
    type: "button",
    onclick: async () => {
      const text = [...deck.mainboard.map((c) => `${c.quantity} ${c.card_name}`), "", ...deck.sideboard.map((c) => `${c.quantity} ${c.card_name}`)].join("\n");
      await navigator.clipboard.writeText(text);
      copy.textContent = "Copied";
      setTimeout(() => (copy.textContent = "Copy list"), 1500);
    },
  }, "Copy list");

  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, deck.archetype), el("p", {}, `Piloted by ${deck.player}`)),
      el("div", { class: "deck-actions" }, copy,
        el("a", { class: "button", href: `https://www.mtggoldfish.com/deck/${encodeURIComponent(deckId)}`, target: "_blank", rel: "noopener" }, "MTGGoldfish"),
        back)),
    el("div", { class: "panel boards" }, board("Mainboard", deck.mainboard), deck.sideboard.length ? board("Sideboard", deck.sideboard) : null),
  );
}

// ---- Card details dialog

async function showCard(api, name, format) {
  const body = dialog.querySelector(".card-dialog-body");
  body.replaceChildren(el("p", { class: "status", id: "card-dialog-title" }, `Loading ${name}…`));
  if (!dialog.open) dialog.showModal();
  try {
    const card = await api.getCardDetails({ card_name: name });
    const faces = card.card_faces?.length ? card.card_faces : [card];
    const image = card.image_uris?.normal ?? card.card_faces?.[0]?.image_uris?.normal;
    const legality = format && card.legalities?.[format];
    body.replaceChildren(
      image ? el("img", { src: image, alt: card.name, loading: "lazy" }) : el("div"),
      el("div", {},
        faces.map((face, index) =>
          el("div", { class: "card-face" },
            el("h3", { id: index === 0 ? "card-dialog-title" : undefined }, face.name, face.mana_cost ? el("span", { class: "mana" }, face.mana_cost) : null),
            el("div", { class: "type-line" }, face.type_line ?? ""),
            face.oracle_text ? el("div", { class: "oracle" }, face.oracle_text) : null,
            face.power != null ? el("div", { class: "pt" }, `${face.power}/${face.toughness}`) : null,
            face.loyalty != null ? el("div", { class: "pt" }, `Loyalty ${face.loyalty}`) : null)),
        legality ? el("div", { class: "legal" }, `${titleCase(format)}: ${legality.replace("_", " ")}`) : null,
        card.scryfall_uri ? el("p", {}, el("a", { href: card.scryfall_uri, target: "_blank", rel: "noopener" }, "View on Scryfall")) : null),
    );
  } catch (error) {
    body.replaceChildren(el("p", { class: "status error", id: "card-dialog-title" }, error.message));
  }
}

dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close(); // a click on the backdrop
});

window.addEventListener("hashchange", render);
render();
