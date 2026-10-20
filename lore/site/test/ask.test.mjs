import assert from "node:assert/strict";
import test from "node:test";
import { check, prompt, retrieve } from "../src/ask.js";

const source = { work: "A Story", series: "Magic Story", kind: "wizards", official: true, url: "https://example.com/a", date: "2020-01-01", credit: "A Story" };
const page = {
  id: "urza", name: "Urza", type: "character", aliases: ["Lord Protector"],
  names: { mishra: "Mishra", argoth: "Argoth" },
  timeline: [
    { id: "a-e0", date: "2020-01-01", era: "", when: "2020-01-01", storyline: "", summary: "Urza and Mishra find the Mightstone.", who: ["urza", "mishra"], where: "", major: false, quote: "the stone glowed", link: "https://example.com/a#1", page: "stories/a" },
    { id: "a-e1", date: "2020-01-02", era: "", when: "2020-01-02", storyline: "", summary: "Urza destroys Argoth with the Sylex.", who: ["urza"], where: "argoth", major: true, quote: "the blast took everything", link: "https://example.com/a#2", page: "stories/a" },
  ],
  relations: [{ id: "a-r0", source: "urza", relation: "family", target: "mishra", note: "brothers", when: "2020-01-01", quote: "his brother", link: "https://example.com/a#3", page: "stories/a" }],
  said: [{ page: "stories/a", when: "2020-01-01", presence: "appears", description: "An artificer." }],
  sources: { "stories/a": source },
};

test("retrieve numbers the facts in story order and puts the fitting ones in", () => {
  const chosen = retrieve("What happened at Argoth?", [page]);
  assert.deepEqual(chosen.map((c) => c.label), chosen.map((_, i) => `F${i + 1}`));
  assert.ok(chosen.some((c) => c.id === "a-e1"));
  const text = prompt("What happened at Argoth?", chosen, [page]);
  assert.match(text, /Urza destroys Argoth/);
  assert.match(text, /Quote: "the blast took everything"/);
  assert.match(text, /Urza family Mishra: brothers/);
});

test("check keeps cited sentences and drops what cites nothing or cites a fact it was not given", () => {
  const chosen = retrieve("What happened at Argoth?", [page]);
  const real = chosen.find((c) => c.id === "a-e1").label;
  const { paragraphs, dropped } = check(`Urza destroyed Argoth [${real}]. An uncited claim. Another claim [${real}].\n\nA made-up fact [F99]. Trailing words with no cite.`, chosen);
  assert.equal(paragraphs.length, 1);
  assert.deepEqual(paragraphs[0].map((s) => s.text), ["Urza destroyed Argoth.", "Another claim."]);
  assert.equal(paragraphs[0][0].cites[0].id, "a-e1");
  assert.equal(dropped, 3);
});
