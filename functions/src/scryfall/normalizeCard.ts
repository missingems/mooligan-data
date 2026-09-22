import { createHash } from "node:crypto";
import type { CardDoc, CardFace } from "../shared/schema.js";

type RawCard = Record<string, any>;

export type NormalizedCard = Omit<CardDoc, "last_updated">;

/**
 * Keeps the gameplay fields of a Scryfall card. Prices and other daily-moving
 * values are dropped so an unchanged card hashes the same from day to day.
 */
export function normalizeCard(raw: RawCard): NormalizedCard | null {
  if (typeof raw?.id !== "string" || typeof raw?.name !== "string") return null;
  const faces: CardFace[] | null = Array.isArray(raw.card_faces)
    ? raw.card_faces.map((face: RawCard) => ({
        name: String(face.name ?? ""),
        mana_cost: face.mana_cost ?? null,
        type_line: face.type_line ?? null,
        oracle_text: face.oracle_text ?? null,
        power: face.power ?? null,
        toughness: face.toughness ?? null,
        loyalty: face.loyalty ?? null,
        defense: face.defense ?? null,
        image_uris: face.image_uris ?? null,
      }))
    : null;
  const card: Omit<NormalizedCard, "content_hash"> = {
    id: raw.id,
    // Reversible cards keep their oracle id on each face instead.
    oracle_id: raw.oracle_id ?? raw.card_faces?.[0]?.oracle_id ?? null,
    name: raw.name,
    search_names: searchNames(raw.name, faces),
    layout: raw.layout ?? "normal",
    mana_cost: raw.mana_cost ?? null,
    cmc: typeof raw.cmc === "number" ? raw.cmc : null,
    type_line: raw.type_line ?? null,
    oracle_text: raw.oracle_text ?? null,
    colors: raw.colors ?? null,
    color_identity: raw.color_identity ?? [],
    keywords: raw.keywords ?? [],
    power: raw.power ?? null,
    toughness: raw.toughness ?? null,
    loyalty: raw.loyalty ?? null,
    defense: raw.defense ?? null,
    legalities: raw.legalities ?? {},
    image_uris: raw.image_uris ?? null,
    card_faces: faces,
    set: raw.set ?? "",
    set_name: raw.set_name ?? "",
    rarity: raw.rarity ?? "",
    released_at: raw.released_at ?? "",
    scryfall_uri: raw.scryfall_uri ?? "",
  };
  return { ...card, content_hash: hashCard(card) };
}

/** The Firestore document id: the oracle id, or the Scryfall id for cards without one. */
export function cardDocumentId(card: NormalizedCard): string {
  return card.oracle_id ?? card.id;
}

/** Lower-cases and trims a card name the way `search_names` stores it. */
export function searchKey(name: string): string {
  return name.trim().toLowerCase();
}

// Decklists name a double-faced card by its front face ("Fable of the
// Mirror-Breaker"), while Scryfall's name joins both ("... // Reflection of Kiki-Jiki").
function searchNames(name: string, faces: CardFace[] | null): string[] {
  const names = new Set([searchKey(name)]);
  for (const part of name.split("//")) names.add(searchKey(part));
  for (const face of faces ?? []) if (face.name) names.add(searchKey(face.name));
  return [...names].filter((value) => value !== "");
}

function hashCard(card: object): string {
  return createHash("sha1").update(JSON.stringify(card)).digest("hex").slice(0, 16);
}
