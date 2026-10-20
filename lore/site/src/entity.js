// An entity's page: who or what it is (the bio), what happened (the timeline), who it stands with, and what each
// source says of it. Every fact has a chip that shows the quote and where it is from.
import { chip, cited, day, factsOf, h, link } from "./ui.js";

const TYPE_LABEL = { character: "Character", creature: "Creature", deity: "Deity", plane: "Plane", location: "Place", faction: "Faction", artifact: "Artifact", event: "Event", concept: "Concept" };

const RELATION_LABEL = {
  ally: ["Allies", "Allies"], enemy: ["Enemies", "Enemies"], family: ["Family", "Family"], romantic: ["Romance", "Romance"],
  mentor_of: ["Mentor of", "Mentored by"], member_of: ["Member of", "Members"], leader_of: ["Leads", "Led by"],
  serves: ["Serves", "Served by"], created: ["Created", "Created by"], killed: ["Killed", "Killed by"],
  located_in: ["Located in", "Holds"], other: ["Other ties", "Other ties"],
};

export const legend = () => h("p", { class: "note small muted sans" }, "Tap a number to see the line it comes from. ",
  h("span", { class: "chip" }, "1"), " official story · ", h("span", { class: "chip fan" }, "1"), " MTG Wiki (fan-written)");

export function renderEntity(view, page) {
  const facts = factsOf(page);
  const numbers = new Map();
  const number = (id) => {
    if (!numbers.has(id)) numbers.set(id, numbers.size + 1);
    return String(numbers.get(id));
  };
  const name = (id) => (id === page.id ? page.name : page.names[id] || id);
  const nameLink = (id) => (id === page.id ? h("b", {}, page.name) : link(id, name(id)));

  const seen = [page.first_seen, page.last_seen].filter(Boolean).map(day);
  const head = h("section", { class: "head" },
    h("div", { class: "sans small muted" }, TYPE_LABEL[page.type] || page.type),
    h("h1", {}, page.name),
    page.aliases.length ? h("div", { class: "muted small" }, "Also: ", page.aliases.slice(0, 12).join(" · ")) : null,
    h("div", { class: "facts" },
      `On ${page.pages} page${page.pages === 1 ? "" : "s"}`,
      seen.length === 2 && seen[0] !== seen[1] ? ` · ${seen[0]} to ${seen[1]}` : seen.length ? ` · ${seen[0]}` : "",
      ` · ${page.timeline.length} events`),
  );

  let bio;
  if (page.bio && page.bio.summary) {
    bio = h("section", { class: "bio" },
      h("p", { class: "lead" }, cited(page.bio.summary, facts, number)),
      page.bio.bio.length ? h("p", {}, page.bio.bio.map((s) => [cited(s, facts, number), " "])) : null,
      page.bio.status ? h("p", { class: "status" }, h("span", { class: "tag" }, "Where things stand"), " ", cited(page.bio.status, facts, number)) : null,
      legend(),
    );
  } else if (page.description) {
    bio = h("section", { class: "bio" }, h("p", { class: "lead" }, page.description));
  }

  const panes = {
    Timeline: () => timeline(page, nameLink),
    Relations: () => relations(page, nameLink),
    Sources: () => sources(page),
  };
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const pane = h("section", { role: "tabpanel" });
  const show = (title) => {
    for (const b of tabs.children) b.setAttribute("aria-selected", String(b.textContent.startsWith(title)));
    pane.replaceChildren(panes[title]());
  };
  const counts = { Timeline: page.timeline.length, Relations: page.relations.length, Sources: page.said.length };
  for (const title of Object.keys(panes)) tabs.append(h("button", { type: "button", role: "tab", onclick: () => show(title) }, `${title} (${counts[title]})`));

  view.replaceChildren(head, bio || null, tabs, pane);
  show("Timeline");
}

function timeline(page, nameLink) {
  const state = { major: page.timeline.length > 120, official: false, text: "" };
  const list = h("ol", { class: "timeline" });
  const draw = () => {
    const words = state.text.toLowerCase().split(/\s+/).filter(Boolean);
    const events = page.timeline.filter((e) =>
      (!state.major || e.major) &&
      (!state.official || page.sources[e.page].official) &&
      words.every((w) => `${e.summary} ${e.quote}`.toLowerCase().includes(w)));
    const rows = [];
    let year = null;
    for (const e of events) {
      const y = e.when ? e.when.slice(0, 4) : "Undated";
      if (y !== year) { rows.push(h("li", { class: "year" }, y)); year = y; }
      const source = page.sources[e.page];
      rows.push(h("li", { class: e.major ? "event major" : "event" },
        h("div", { class: "when" },
          e.date ? day(e.date) : e.era ? `${e.era} era` : "",
          e.storyline ? ` · ${e.storyline}` : "",
          ` · ${source.work}`),
        h("div", {}, e.summary, " ", chip("quote", { quote: e.quote, text: "", link: e.link, source })),
        e.who.length > 1 ? h("div", { class: "small muted" }, e.who.filter((id) => id !== page.id).slice(0, 6).map((id, i) => [i ? ", " : "With ", nameLink(id)])) : null,
      ));
    }
    list.replaceChildren(...(rows.length ? rows : [h("li", { class: "muted" }, "Nothing matches.")]));
  };
  const box = (key, label) => h("label", {}, h("input", { type: "checkbox", checked: state[key], onchange: (ev) => { state[key] = ev.target.checked; draw(); } }), ` ${label}`);
  const filters = h("div", { class: "filters" },
    box("major", "Turning points only"),
    box("official", "Official sources only"),
    h("input", { type: "search", placeholder: "Filter events", oninput: (ev) => { state.text = ev.target.value; draw(); } }),
  );
  draw();
  return h("div", {}, filters, list);
}

function relations(page, nameLink) {
  if (!page.relations.length) return h("p", { class: "muted" }, "No relations recorded.");
  const groups = new Map();
  for (const r of page.relations) {
    const outgoing = r.source === page.id;
    const label = (RELATION_LABEL[r.relation] || [r.relation, r.relation])[outgoing ? 0 : 1];
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push({ r, other: outgoing ? r.target : r.source });
  }
  return h("div", {}, [...groups].map(([label, items]) => h("div", { class: "rel-group" },
    h("h3", {}, label),
    h("ul", {}, items.map(({ r, other }) => h("li", {},
      nameLink(other), r.note ? ` — ${r.note}` : "", " ",
      chip("quote", { quote: r.quote, text: "", link: r.link, source: page.sources[r.page] })))))));
}

function sources(page) {
  return h("ul", { class: "said" }, page.said.map((s) => {
    const source = page.sources[s.page];
    return h("li", {},
      h("div", {}, h("a", { href: source.url, target: "_blank", rel: "noopener" }, source.work), " ",
        h("span", { class: "small muted" }, [source.series, day(source.date)].filter(Boolean).join(" · ")),
        source.official ? null : [" ", h("span", { class: "tag", style: "color:var(--fan)" }, "Fan wiki")]),
      s.description ? h("div", { class: "small" }, s.description) : null);
  }));
}
