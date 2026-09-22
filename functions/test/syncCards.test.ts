import { describe, expect, it } from "vitest";
import type { NormalizedCard } from "../src/scryfall/normalizeCard.js";
import { syncCards, type CardSyncStore } from "../src/scryfall/syncCards.js";
import { uniqueCard } from "./cardFixtures.js";

class MemoryStore implements CardSyncStore {
  hashes = new Map<string, string>();
  cards = new Map<string, NormalizedCard>();
  batchSizes: number[] = [];

  async loadHashes() {
    return new Map(this.hashes);
  }
  async commit(upserts: NormalizedCard[], deletes: string[]) {
    this.batchSizes.push(upserts.length + deletes.length);
    await new Promise((resolve) => setTimeout(resolve, 1));
    for (const card of upserts) this.cards.set(card.oracle_id ?? card.id, card);
    for (const id of deletes) this.cards.delete(id);
  }
  async saveHashes(hashes: Map<string, string>) {
    this.hashes = new Map(hashes);
  }
}

async function* lines(items: unknown[]) {
  yield* items;
}

describe("syncCards", () => {
  it("writes batches of at most 500", async () => {
    const store = new MemoryStore();
    const cards = Array.from({ length: 1203 }, () => uniqueCard());
    const stats = await syncCards(lines(cards), store);
    expect(stats).toMatchObject({ read: 1203, upserted: 1203, unchanged: 0, batches: 3 });
    expect(store.batchSizes.sort((a, b) => b - a)).toEqual([500, 500, 203]);
    expect(store.cards.size).toBe(1203);
  });

  it("skips cards whose content did not change", async () => {
    const store = new MemoryStore();
    const cards = Array.from({ length: 10 }, () => uniqueCard());
    await syncCards(lines(cards), store);
    const changed = { ...cards[3], oracle_text: "New text", prices: { usd: "5" } };
    const repriced = { ...cards[4], prices: { usd: "100" } };
    const stats = await syncCards(lines([...cards.slice(0, 3), changed, repriced, ...cards.slice(5)]), store);
    expect(stats).toMatchObject({ upserted: 1, unchanged: 9, batches: 1 });
  });

  it("deletes cards that left the file once the file is large enough", async () => {
    const store = new MemoryStore();
    const cards = Array.from({ length: 5 }, () => uniqueCard());
    await syncCards(lines(cards), store, { minCardsForDeletion: 3 });
    const stats = await syncCards(lines(cards.slice(0, 4)), store, { minCardsForDeletion: 3 });
    expect(stats.deleted).toBe(1);
    expect(store.cards.size).toBe(4);
    expect(store.hashes.size).toBe(4);
  });

  it("never deletes after a suspiciously small file", async () => {
    const store = new MemoryStore();
    const cards = Array.from({ length: 5 }, () => uniqueCard());
    await syncCards(lines(cards), store);
    const stats = await syncCards(lines(cards.slice(0, 1)), store);
    expect(stats.deleted).toBe(0);
    expect(store.cards.size).toBe(5);
    expect(store.hashes.size).toBe(5);
  });

  it("ignores invalid lines and duplicate ids", async () => {
    const store = new MemoryStore();
    const card = uniqueCard();
    const stats = await syncCards(lines([card, { object: "error" }, card]), store);
    expect(stats).toMatchObject({ read: 3, skippedInvalid: 1, upserted: 1 });
  });

  it("fails when a batch fails", async () => {
    const store = new MemoryStore();
    store.commit = async () => {
      throw new Error("quota exceeded");
    };
    await expect(syncCards(lines([uniqueCard()]), store)).rejects.toThrow("quota exceeded");
  });
});
