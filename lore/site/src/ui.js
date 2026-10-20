// Small DOM helpers, citation chips and the quote popover.

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const link = (id, name) => h("a", { href: `#/e/${encodeURIComponent(id)}` }, name);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// When a fact happened, as precisely as it is known: the day a story came out, or the era a wiki section is set in.
export function whenLabel(item) {
  if (item.date) return day(item.date);
  if (item.era) return `${item.era} era`;
  return item.when ? item.when.slice(0, 4) : "undated";
}

export function day(date) {
  if (!date) return "";
  const [y, m, d] = date.split("-");
  return d ? `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}` : y;
}

// A fact, whatever it is, as the popover shows it: { quote, text, link, source }.
// `source` is an entry of an entity file's `sources`: { work, series, kind, official, url, date, credit }.
export function chip(label, fact) {
  const fan = fact.source && !fact.source.official;
  return h("button", {
    type: "button",
    class: fan ? "chip fan" : "chip",
    title: fact.source ? fact.source.work : "",
    onclick: (event) => { event.stopPropagation(); showPop(event.currentTarget, fact); },
  }, label);
}

const pop = () => document.getElementById("pop");

export function showPop(anchor, fact) {
  const box = pop();
  const s = fact.source || {};
  box.replaceChildren(...[
    fact.quote ? h("blockquote", {}, `“${fact.quote}”`) : null,
    fact.text ? h("p", {}, fact.text) : null,
    h("div", { class: "credit" },
      h("span", { class: "tag", style: s.official ? "" : "color:var(--fan)" }, s.official ? "Official" : "Fan wiki"), " ",
      s.credit || s.work || ""),
    fact.link ? h("a", { class: "open", href: fact.link, target: "_blank", rel: "noopener" }, fact.quote ? "Read it in context ↗" : "Open the source ↗") : null,
  ].filter(Boolean));
  box.hidden = false;
  const r = anchor.getBoundingClientRect();
  const width = box.offsetWidth;
  const left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - width - 8));
  box.style.left = `${left}px`;
  box.style.top = `${window.scrollY + r.bottom + 6}px`;
}

export function hidePop() { pop().hidden = true; }

// Closes the popover on a click elsewhere or Escape.
export function installPopover() {
  document.addEventListener("click", (event) => { if (!pop().contains(event.target)) hidePop(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") hidePop(); });
}

// The facts an entity file holds, by the ids bios and answers cite: event ids, relation ids and "p:<page>".
export function factsOf(page) {
  const facts = new Map();
  for (const e of page.timeline) facts.set(e.id, { kind: "event", quote: e.quote, text: e.summary, link: e.link, source: page.sources[e.page], when: e.when, label: whenLabel(e), item: e });
  for (const r of page.relations) facts.set(r.id, { kind: "relation", quote: r.quote, text: r.note, link: r.link, source: page.sources[r.page], when: r.when, label: whenLabel({ date: r.when }), item: r });
  for (const s of page.said) {
    const source = page.sources[s.page];
    facts.set(`p:${s.page}`, { kind: "said", quote: "", text: s.description, link: source.url, source, when: s.when, label: whenLabel({ date: s.when }), item: s });
  }
  return facts;
}

// A sentence followed by a chip for each fact it cites.
export function cited(sentence, facts, numbering) {
  const chips = sentence.cites.map((id) => {
    const fact = facts.get(id);
    return fact ? chip(numbering(id), fact) : null;
  });
  return [sentence.text, " ", ...chips];
}
