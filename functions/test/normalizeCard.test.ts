import { describe, expect, it } from "vitest";
import { cardDocumentId, normalizeCard } from "../src/scryfall/normalizeCard.js";
import { rawCard } from "./cardFixtures.js";

describe("normalizeCard", () => {
  it("keeps gameplay fields and drops prices", () => {
    const card = normalizeCard(rawCard())!;
    expect(card.name).toBe("Fury Sliver");
    expect(card.mana_cost).toBe("{5}{R}");
    expect(card.image_uris?.normal).toContain("fury.jpg");
    expect(card).not.toHaveProperty("prices");
    expect(card).not.toHaveProperty("edhrec_rank");
    expect(cardDocumentId(card)).toBe("44623693-51d6-49ad-8cd7-140505caf02f");
  });

  it("hashes the same card identically despite a price change", () => {
    const before = normalizeCard(rawCard())!;
    const after = normalizeCard(rawCard({ prices: { usd: "9.99" }, edhrec_rank: 1 }))!;
    expect(after.content_hash).toBe(before.content_hash);
  });

  it("changes the hash when the rules text changes", () => {
    const before = normalizeCard(rawCard())!;
    const after = normalizeCard(rawCard({ oracle_text: "All Slivers have first strike." }))!;
    expect(after.content_hash).not.toBe(before.content_hash);
  });

  it("indexes each face of a double-faced card", () => {
    const card = normalizeCard(
      rawCard({
        name: "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
        layout: "transform",
        image_uris: undefined,
        card_faces: [
          { name: "Fable of the Mirror-Breaker", mana_cost: "{2}{R}", image_uris: { normal: "front.jpg" } },
          { name: "Reflection of Kiki-Jiki", mana_cost: "", image_uris: { normal: "back.jpg" } },
        ],
      }),
    )!;
    expect(card.search_names).toEqual([
      "fable of the mirror-breaker // reflection of kiki-jiki",
      "fable of the mirror-breaker",
      "reflection of kiki-jiki",
    ]);
    expect(card.image_uris).toBeNull();
    expect(card.card_faces?.[1]?.image_uris?.normal).toBe("back.jpg");
  });

  it("takes a reversible card's oracle id from its first face", () => {
    const card = normalizeCard(
      rawCard({ oracle_id: undefined, layout: "reversible_card", card_faces: [{ name: "A", oracle_id: "face-oracle" }] }),
    )!;
    expect(card.oracle_id).toBe("face-oracle");
  });

  it("rejects objects that are not cards", () => {
    expect(normalizeCard({ object: "error" })).toBeNull();
  });
});
