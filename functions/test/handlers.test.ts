import { Timestamp } from "firebase-admin/firestore";
import { describe, expect, it } from "vitest";
import { getArchetype, getCardDetails, getDecklist, getEvent, getEvents, getMeta } from "../src/api/handlers.js";
import { normalizeCard } from "../src/scryfall/normalizeCard.js";
import { rawCard } from "./cardFixtures.js";
import { fakeFirestore } from "./fakeFirestore.js";

const day = (date: string) => Timestamp.fromDate(new Date(`${date}T00:00:00Z`));

const fable = normalizeCard(
  rawCard({
    id: "fable-id",
    oracle_id: "fable-oracle",
    name: "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
    card_faces: [{ name: "Fable of the Mirror-Breaker" }, { name: "Reflection of Kiki-Jiki" }],
  }),
)!;

const db = fakeFirestore({
  meta: {
    modern_30d: {
      format: "modern",
      timeframe: "30d",
      last_updated: day("2026-09-21"),
      archetypes: [{ name: "Orzhov Necro", percentage: 12.5, id: "modern-orzhov-necrodominance" }],
    },
  },
  events: {
    "1": { event_name: "Modern Challenge 32", format: "modern", date: day("2026-09-18"), results: [] },
    "2": { event_name: "Modern League", format: "modern", date: day("2026-09-20"), results: [] },
    "3": { event_name: "Pioneer Challenge", format: "pioneer", date: day("2026-09-21"), results: [] },
    "4": { event_name: "Modern Showcase", format: "modern", date: day("2026-09-19"), results: [] },
  },
  archetypes: {
    "modern_modern-izzet-prowess": {
      format: "modern",
      archetype_id: "modern-izzet-prowess",
      name: "Izzet Prowess",
      deck_id: "7945486",
      featured_player: "Roy Varney",
      results: [
        { deck_id: "7966110", date: day("2026-09-21"), player: "Xsper", event_id: "66753", event_name: "Modern Challenge 32", finish: "13th Place" },
      ],
      last_updated: day("2026-09-22"),
    },
  },
  decks: {
    "7967157": {
      player: "Numot",
      archetype: "Orzhov Necro",
      mainboard: [{ quantity: 4, card_name: "Force of Despair" }],
      sideboard: [{ quantity: 2, card_name: "Fatal Push" }],
    },
  },
  cards: {
    "fable-oracle": { ...fable, last_updated: day("2026-09-21") },
    "fury-oracle": { ...normalizeCard(rawCard())!, last_updated: day("2026-09-21") },
  },
});

describe("getMeta", () => {
  it("returns the format and timeframe document with ISO dates", async () => {
    const meta = await getMeta(db, { format: "Modern", timeframe: "30d" });
    expect(meta.id).toBe("modern_30d");
    expect(meta.last_updated).toBe("2026-09-21T00:00:00.000Z");
    expect(meta.archetypes[0]?.percentage).toBe(12.5);
  });

  it("defaults the timeframe", async () => {
    expect((await getMeta(db, { format: "modern" })).id).toBe("modern_30d");
  });

  it("reports a missing format as not found", async () => {
    await expect(getMeta(db, { format: "legacy", timeframe: "30d" })).rejects.toMatchObject({ code: "not-found" });
  });

  it("rejects bad input", async () => {
    await expect(getMeta(db, null)).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getMeta(db, { format: "../x" })).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getMeta(db, { format: 3 })).rejects.toMatchObject({ code: "invalid-argument" });
  });
});

describe("getEvents", () => {
  it("returns the newest events of one format", async () => {
    const { events } = await getEvents(db, { format: "modern", limit: 2 });
    expect(events.map((event) => event.event_id)).toEqual(["2", "4"]);
    expect(events[0]?.date).toBe("2026-09-20T00:00:00.000Z");
  });

  it("validates the limit", async () => {
    await expect(getEvents(db, { format: "modern", limit: 0 })).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getEvents(db, { format: "modern", limit: 1.5 })).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getEvents(db, { format: "modern", limit: 101 })).rejects.toMatchObject({ code: "invalid-argument" });
  });
});

describe("getEvent", () => {
  it("returns one event by id, however old", async () => {
    const event = await getEvent(db, { event_id: "1" });
    expect(event.event_name).toBe("Modern Challenge 32");
    expect(event.date).toBe("2026-09-18T00:00:00.000Z");
  });

  it("reports unknown events", async () => {
    await expect(getEvent(db, { event_id: "999" })).rejects.toMatchObject({ code: "not-found" });
    await expect(getEvent(db, { event_id: "../1" })).rejects.toMatchObject({ code: "invalid-argument" });
  });
});

describe("getArchetype", () => {
  it("returns the archetype's results with ISO dates", async () => {
    const archetype = await getArchetype(db, { format: "modern", archetype_id: "modern-izzet-prowess" });
    expect(archetype.id).toBe("modern_modern-izzet-prowess");
    expect(archetype.results[0]).toMatchObject({ deck_id: "7966110", date: "2026-09-21T00:00:00.000Z" });
  });

  it("validates and reports unknown archetypes", async () => {
    await expect(getArchetype(db, { format: "modern", archetype_id: "Bad Id" })).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getArchetype(db, { format: "modern", archetype_id: "modern-nope" })).rejects.toMatchObject({ code: "not-found" });
  });
});

describe("getDecklist", () => {
  it("returns both boards", async () => {
    const deck = await getDecklist(db, { deck_id: "7967157" });
    expect(deck.mainboard).toEqual([{ quantity: 4, card_name: "Force of Despair" }]);
    expect(deck.sideboard).toEqual([{ quantity: 2, card_name: "Fatal Push" }]);
  });

  it("rejects ids that are not ids", async () => {
    await expect(getDecklist(db, { deck_id: "a/b" })).rejects.toMatchObject({ code: "invalid-argument" });
    await expect(getDecklist(db, { deck_id: "404" })).rejects.toMatchObject({ code: "not-found" });
  });
});

describe("getCardDetails", () => {
  it("finds a card by its exact name, ignoring case", async () => {
    expect((await getCardDetails(db, { card_name: "fury sliver" })).name).toBe("Fury Sliver");
  });

  it("finds a double-faced card by its front face", async () => {
    const card = await getCardDetails(db, { card_name: "Fable of the Mirror-Breaker" });
    expect(card.name).toBe("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki");
    expect(card.last_updated).toBe("2026-09-21T00:00:00.000Z");
  });

  it("reports unknown cards as not found", async () => {
    await expect(getCardDetails(db, { card_name: "Black Lotus II" })).rejects.toMatchObject({ code: "not-found" });
  });
});
