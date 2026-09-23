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

const FORMAT_NAMES = { penny_dreadful: "Penny Dreadful", duel_commander: "Duel Commander" };
// Scryfall's legality keys differ from MTGGoldfish's format ids for these two.
const SCRYFALL_LEGALITY = { penny_dreadful: "penny", duel_commander: "duel" };
const formatName = (format) => FORMAT_NAMES[format] ?? titleCase(format);
const titleCase = (text) => text.replace(/(^|[\s_-])(\w)/g, (_, gap, letter) => gap.replace(/[_-]/, " ") + letter.toUpperCase());
const formatDate = (iso) =>
  new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const timeframeLabel = (timeframe) => timeframe.replace(/^(\d+)d$/, (_, days) => `${days} days`);
const count = (cards) => cards.reduce((sum, card) => sum + card.quantity, 0);

const EVENT_KINDS = {
  pro_tour: "Pro Tour",
  regional_championship: "Regional Championship",
  rcq: "RCQ",
  store_championship: "Store Championship",
  mtgo_challenge: "MTGO Challenge",
  mtgo_league: "MTGO League",
  other: "Other",
};
const kindName = (kind) => EVENT_KINDS[kind] ?? "Other";

const cardSlug = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// ---- Routing: #/<format>[?t=<window>], #/<format>/event/<id>, #/<format>/archetype/<id>, #/deck/<id>, #/card/<slug>

function parseRoute() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query);
  if (parts[0] === "deck" && parts[1]) return { name: "deck", deckId: parts[1] };
  if (parts[0] === "card" && parts[1]) return { name: "card", slug: parts[1] };
  if (parts[0] === "commander" && parts[1]) return { name: "commander", slug: parts[1] };
  const format = config.formats.includes(parts[0]) ? parts[0] : config.formats[0];
  if (parts[1] === "event" && parts[2]) return { name: "event", format, eventId: parts[2] };
  if (parts[1] === "archetype" && parts[2]) return { name: "archetype", format, archetypeId: parts[2] };
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
    const content =
      route.name === "commander"
        ? await commanderView(api, route)
        : route.name === "card"
          ? await cardView(api, route)
          : route.name === "deck"
            ? await deckView(api, route)
            : route.name === "event"
              ? await eventView(api, route)
              : route.name === "archetype"
                ? await archetypeView(api, route)
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
      el("a", { href: `#/${format}`, "aria-current": format === current ? "page" : undefined }, formatName(format)),
    ),
  );
}

// ---- Views

async function metaView(api, { format, timeframe }) {
  const [meta, { events }] = await Promise.all([
    api.getMeta({ format, timeframe }).catch((error) => (error.code === "not-found" ? null : Promise.reject(error))),
    api.getEvents({ format, limit: 100 }),
  ]);
  document.title = `${formatName(format)} metagame · MTG Metagame`;

  // The snapshot keys them alphabetically ("14d", "30d", "7d"); show them by length.
  const windows = [...(meta?.windows ?? [])].sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  const timeframes = windows.length < 2 ? null : el(
    "nav",
    { class: "segmented", "aria-label": "Timeframe" },
    windows.map((option) =>
      el("a", { href: `#/${format}?t=${option}`, "aria-current": option === (meta.timeframe ?? timeframe) ? "true" : undefined },
        timeframeLabel(option)),
    ),
  );

  return el(
    "div",
    {},
    el(
      "div",
      { class: "page-head" },
      el("div", {}, el("h1", {}, `${formatName(format)} metagame`),
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
              href: `#/${meta.format}/archetype/${encodeURIComponent(archetype.id)}`,
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
  const panel = el("section", { class: "panel" }, el("h2", {}, "Recent events", el("small", {}, `${events.length} stored`)));
  if (events.length === 0) {
    panel.append(el("p", { class: "status" }, "No events scraped yet."));
    return panel;
  }
  // One chip per tier present, so the Pro Tours and RCQs stand out from the daily MTGO events.
  const kinds = Object.keys(EVENT_KINDS).filter((kind) => events.some((event) => (event.kind ?? "other") === kind));
  let selected = null;
  const list = el("ul", { class: "event-list" });
  const chips = el("nav", { class: "segmented chips", "aria-label": "Event tier" });
  const shown = () => (selected ? events.filter((event) => (event.kind ?? "other") === selected) : events);
  const renderRows = (limit) => {
    const rows = shown();
    list.replaceChildren(
      ...rows.slice(0, limit).map((event) => {
        const winner = event.results[0];
        return el(
          "li",
          {},
          el("a", { href: `#/${format}/event/${encodeURIComponent(event.event_id)}` }, event.event_name),
          el("div", { class: "sub" },
            [formatDate(event.date), kindName(event.kind), `${event.results.length} decks`, winner ? `${winner.finish}: ${winner.archetype}` : null]
              .filter(Boolean).join(" · ")),
        );
      }),
    );
    more.hidden = rows.length <= limit;
    more.textContent = `Show all ${rows.length}`;
  };
  const more = el("button", { class: "show-all", type: "button", onclick: () => renderRows(Infinity) });
  const renderChips = () =>
    chips.replaceChildren(
      el("a", { href: "#", "aria-current": selected ? undefined : "true", onclick: (e) => { e.preventDefault(); selected = null; renderChips(); renderRows(20); } }, "All"),
      ...kinds.map((kind) =>
        el("a", { href: "#", "aria-current": selected === kind ? "true" : undefined,
          onclick: (e) => { e.preventDefault(); selected = kind; renderChips(); renderRows(20); } }, kindName(kind))),
    );
  renderChips();
  renderRows(20);
  panel.append(kinds.length > 1 ? chips : null, list, more);
  return panel;
}

async function eventView(api, { format, eventId }) {
  const event = await api.getEvent({ format, event_id: eventId }).catch((error) => {
    if (error.code !== "not-found") throw error;
    return null;
  });
  if (!event) return notStoredYet(`This event hasn't been scraped yet.`, `https://www.mtggoldfish.com/tournament/${encodeURIComponent(eventId)}`, format);
  document.title = `${event.event_name} · MTG Metagame`;
  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, event.event_name),
        el("p", {}, `${formatName(event.format)} · ${formatDate(event.date)} · ${kindName(event.kind)}${event.source ? ` · from ${event.source}` : ""} · `,
          el("a", { href: event.url ?? `https://www.mtggoldfish.com/tournament/${eventId}`, target: "_blank", rel: "noopener" }, "MTGGoldfish"))),
      el("a", { href: `#/${format}` }, `← ${formatName(format)} metagame`)),
    el("section", { class: "panel" },
      el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Finish"), el("th", {}, "Deck"), el("th", {}, "Player"), el("th", {}, "Archetype"))),
        el("tbody", {}, event.results.map((result) =>
          el("tr", {},
            el("td", { class: "finish" }, result.finish),
            el("td", {}, el("a", { href: `#/deck/${encodeURIComponent(result.deck_id)}?event=${encodeURIComponent(eventId)}&format=${format}` }, result.archetype)),
            el("td", {}, result.player),
            el("td", {}, result.archetype_id
              ? el("a", { href: `#/${format}/archetype/${encodeURIComponent(result.archetype_id)}` }, "All results")
              : null)))))),
  );
}

async function deckView(api, { deckId }) {
  const deck = await api.getDecklist({ deck_id: deckId }).catch((error) => {
    if (error.code !== "not-found") throw error;
    return null;
  });
  if (!deck) {
    const format = new URLSearchParams(location.hash.split("?")[1] ?? "").get("format");
    return notStoredYet("This decklist hasn't been downloaded yet. Each scrape adds more.", `https://www.mtggoldfish.com/deck/${encodeURIComponent(deckId)}`, format);
  }
  document.title = `${deck.archetype} by ${deck.player} · MTG Metagame`;
  const backParams = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const format = deck.format ?? backParams.get("format");
  // Decks downloaded before they carried an archetype id are looked up in the snapshot.
  const archetypeId =
    deck.archetype_id ?? (format ? (await api.findArchetypeOfDeck({ format, deck_id: deckId }).catch(() => null))?.archetype_id : null);
  const eventId = deck.event_id ?? backParams.get("event");
  const back = eventId && format
    ? el("a", { href: `#/${format}/event/${encodeURIComponent(eventId)}` }, "← Event")
    : format
      ? el("a", { href: `#/${format}` }, `← ${formatName(format)} metagame`)
      : null;

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
      el("div", {},
        el("h1", {}, deck.archetype),
        el("p", {}, `Piloted by ${deck.player}`,
          archetypeId && format
            ? el("span", {}, " · ",
                el("a", { href: `#/${format}/archetype/${encodeURIComponent(archetypeId)}` }, `All ${deck.archetype} results`))
            : null)),
      el("div", { class: "deck-actions" }, copy,
        el("a", { class: "button", href: `https://www.mtggoldfish.com/deck/${encodeURIComponent(deckId)}`, target: "_blank", rel: "noopener" }, "MTGGoldfish"),
        back)),
    el("div", { class: "panel boards" }, board("Mainboard", deck.mainboard), deck.sideboard.length ? board("Sideboard", deck.sideboard) : null),
  );
}

async function archetypeView(api, { format, archetypeId }) {
  const archetype = await api.getArchetype({ format, archetype_id: archetypeId }).catch((error) => {
    if (error.code !== "not-found") throw error;
    return null;
  });
  const goldfish = `https://www.mtggoldfish.com/archetype/${encodeURIComponent(archetypeId)}`;
  if (!archetype) return notStoredYet("This archetype's results haven't been scraped yet.", goldfish, format);
  document.title = `${archetype.name} · MTG Metagame`;

  // Results are newest first, so events come out in date order as they are first seen.
  const events = new Map();
  for (const result of archetype.results) {
    const key = result.event_id ?? result.event_name;
    if (!events.has(key)) events.set(key, { id: result.event_id, name: result.event_name, date: result.date, results: [] });
    events.get(key).results.push(result);
  }
  const groups = [...events.values()];
  const deckHref = (deckId, eventId) =>
    `#/deck/${encodeURIComponent(deckId)}?format=${format}${eventId ? `&event=${encodeURIComponent(eventId)}` : ""}`;

  const list = el("div", { class: "archetype-events" });
  const renderGroups = (limit) =>
    list.replaceChildren(
      ...groups.slice(0, limit).map((group) =>
        el("section", { class: "panel archetype-event" },
          el("h2", {},
            group.id ? el("a", { href: `#/${format}/event/${encodeURIComponent(group.id)}` }, group.name) : group.name,
            el("small", {}, `${formatDate(group.date)} · ${group.results.length} ${group.results.length === 1 ? "deck" : "decks"}`)),
          el("table", {},
            el("tbody", {}, group.results.map((result) =>
              el("tr", {},
                el("td", { class: "finish" }, result.finish),
                el("td", {}, el("a", { href: deckHref(result.deck_id, group.id) }, result.player)))))))),
    );
  renderGroups(30);
  const more = groups.length > 30
    ? el("button", { class: "show-all", type: "button", onclick: () => { renderGroups(Infinity); more.remove(); } }, `Show all ${groups.length} events`)
    : null;

  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, archetype.name),
        el("p", {}, `${archetype.results.length} decks in ${groups.length} events · updated ${formatDate(archetype.last_updated)}`)),
      el("div", { class: "deck-actions" },
        archetype.deck_id
          ? el("a", { class: "button", href: deckHref(archetype.deck_id, null) },
              archetype.featured_player ? `Featured list by ${archetype.featured_player}` : "Featured list")
          : null,
        el("a", { class: "button", href: goldfish, target: "_blank", rel: "noopener" }, "MTGGoldfish"),
        el("a", { href: `#/${format}` }, `← ${formatName(format)} metagame`))),
    groups.length ? list : el("p", { class: "status" }, "No results in the history window."),
    more,
  );
}

async function commanderView(api, { slug }) {
  const commander = await api.getCommander({ slug }).catch((error) => {
    if (error.code !== "not-found") throw error;
    return null;
  });
  if (!commander) {
    return notStoredYet(
      "This commander hasn't been fetched yet. Each run adds more.",
      `https://edhrec.com/commanders/${encodeURIComponent(slug)}`,
      null,
    );
  }
  document.title = `${commander.name} · MTG Metagame`;
  const cardLink = (name) => el("a", { href: `#/card/${encodeURIComponent(cardSlug(name.split("//")[0]))}` }, name);

  const inclusionSection = (section) =>
    el("section", { class: "panel archetype-event" },
      el("h2", {}, section.header || section.tag),
      el("table", {},
        el("tbody", {}, section.cards.map((card) =>
          el("tr", {},
            el("td", {}, cardLink(card.name)),
            el("td", { class: "finish" }, `${Math.round((card.decks / card.of_decks) * 100)}%`),
            el("td", { class: "finish" }, card.synergy == null ? "" : `${card.synergy > 0 ? "+" : ""}${Math.round(card.synergy * 100)}%`))))));

  const averageSection = (section) =>
    el("section", {},
      el("h2", {}, `${section.header} (${section.cards.length})`),
      el("ul", { class: "deck-list" }, section.cards.map((name) => el("li", {}, el("span", { class: "qty" }), cardLink(name)))));

  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, commander.name),
        el("p", {}, `${commander.decks.toLocaleString()} Commander decks${commander.salt == null ? "" : ` · salt ${commander.salt}`} · updated ${formatDate(commander.generated_at)}`)),
      el("a", { class: "button", href: commander.url, target: "_blank", rel: "noopener" }, "EDHREC")),
    commander.average_deck.length
      ? el("div", { class: "panel boards" }, commander.average_deck.map(averageSection))
      : null,
    el("p", { class: "legal" }, "Percentages are how many of this commander's decks play the card; synergy is EDHREC's. Data from EDHREC, used with permission."),
    el("div", { class: "archetype-events" }, commander.sections.map(inclusionSection)),
  );
}

function notStoredYet(message, goldfishUrl, format) {
  document.title = "MTG Metagame";
  return el("div", {},
    el("p", { class: "status" }, message, " ",
      el("a", { href: goldfishUrl, target: "_blank", rel: "noopener" }, "View it on MTGGoldfish"), "."),
    format ? el("a", { href: `#/${format}` }, `← ${formatName(format)} metagame`) : null);
}

async function cardView(api, { slug }) {
  const [card, details] = await Promise.all([
    api.getCard({ slug }).catch((error) => {
      if (error.code !== "not-found") throw error;
      return null;
    }),
    api.getCardDetails({ card_name: slug.replace(/-/g, " ") }).catch(() => null),
  ]);
  const name = card?.card_name ?? details?.name ?? slug;
  document.title = `${name} · MTG Metagame`;
  if (!card) {
    return el("div", {},
      el("div", { class: "page-head" }, el("div", {}, el("h1", {}, name))),
      el("p", { class: "status" }, "No stored deck in the tracked formats plays this card."));
  }

  const image = details?.image_uris?.normal ?? details?.card_faces?.[0]?.image_uris?.normal;
  const playRate = (entry) => entry.decks / entry.of_decks;
  const played = Object.entries(card.formats).sort((a, b) => playRate(b[1]) - playRate(a[1]));

  const archetypeRow = (format, archetype) =>
    el("tr", {},
      el("td", {},
        archetype.archetype_id
          ? el("a", { href: `#/${format}/archetype/${encodeURIComponent(archetype.archetype_id)}` }, archetype.name)
          : archetype.name),
      el("td", { class: "finish" }, `${archetype.decks} ${archetype.decks === 1 ? "deck" : "decks"}`),
      el("td", { class: "finish" }, `${archetype.avg_copies}×`),
      el("td", {}, archetype.deck_ids.slice(0, 3).map((deckId, index) =>
        el("span", {}, index ? " " : "", el("a", { href: `#/deck/${encodeURIComponent(deckId)}?format=${format}` }, `#${index + 1}`)))));

  const edhPanel = (edh) =>
    el("section", { class: "panel archetype-event" },
      el("h2", {},
        el("a", { href: edh.url, target: "_blank", rel: "noopener" }, "Commander"),
        el("small", {}, `${(100 * edh.decks / edh.of_decks).toFixed(1)}% · ${edh.decks.toLocaleString()} of ${edh.of_decks.toLocaleString()} decks`)),
      el("table", {},
        el("tbody", {}, edh.commanders.map((commander) =>
          el("tr", {},
            el("td", {}, el("a", { href: `#/commander/${encodeURIComponent(commander.slug)}` }, commander.name)),
            el("td", { class: "finish" }, commander.decks.toLocaleString()),
            el("td", { class: "finish" }, commander.of_decks ? `${Math.round((commander.decks / commander.of_decks) * 100)}%` : ""))))),
      el("p", { class: "legal" }, "Commander data from EDHREC, used with permission."));

  const formatPanel = ([format, entry]) =>
    el("section", { class: "panel archetype-event" },
      el("h2", {},
        el("a", { href: `#/${format}` }, formatName(format)),
        el("small", {}, `${Math.round(playRate(entry) * 100)}% · ${entry.decks} of ${entry.of_decks} decks`)),
      el("table", {}, el("tbody", {}, entry.archetypes.map((archetype) => archetypeRow(format, archetype)))));

  return el(
    "div",
    {},
    el("div", { class: "page-head" },
      el("div", {},
        el("h1", {}, name),
        el("p", {}, `Played in ${played.length} ${played.length === 1 ? "format" : "formats"}${card.edh ? " and Commander" : ""} · updated ${formatDate(card.generated_at)}`)),
      details?.scryfall_uri
        ? el("a", { class: "button", href: details.scryfall_uri, target: "_blank", rel: "noopener" }, "Scryfall")
        : null),
    el("div", { class: "card-played" },
      image ? el("img", { class: "card-art", src: image, alt: name, loading: "lazy" }) : null,
      el("div", { class: "archetype-events" }, [...played.map(formatPanel), card.edh ? edhPanel(card.edh) : null])),
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
    const legality = format && card.legalities?.[SCRYFALL_LEGALITY[format] ?? format];
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
        legality ? el("div", { class: "legal" }, `${formatName(format)}: ${legality.replace("_", " ")}`) : null,
        el("p", {},
          el("a", { href: `#/card/${encodeURIComponent(cardSlug(card.name.split("//")[0]))}`, onclick: () => dialog.close() }, "Where it's played"),
          card.scryfall_uri ? el("span", {}, " · ", el("a", { href: card.scryfall_uri, target: "_blank", rel: "noopener" }, "Scryfall")) : null)),
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
