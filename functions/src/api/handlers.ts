import type { Firestore } from "firebase-admin/firestore";
import { HttpsError } from "firebase-functions/v2/https";
import { searchKey } from "../scryfall/normalizeCard.js";
import { Collections, type CardDoc, type DeckDoc, type EventDoc, type MetaDoc } from "../shared/schema.js";
import { serialize, type Serialized } from "../shared/serialize.js";
import { asPayload, optionalInteger, requireSlug, requireText } from "../shared/validation.js";

// Handlers take the database so tests can pass a fake; index.ts wraps them in onCall.

export const DEFAULT_TIMEFRAME = "30d";

export type MetaResponse = Serialized<MetaDoc> & { id: string };
export type EventSummary = Serialized<EventDoc> & { event_id: string };
export type DecklistResponse = Serialized<DeckDoc> & { deck_id: string };
export type CardResponse = Serialized<CardDoc>;

export async function getMeta(db: Firestore, data: unknown): Promise<MetaResponse> {
  const payload = asPayload(data);
  const format = requireSlug(payload, "format");
  const timeframe = requireSlug(payload, "timeframe", DEFAULT_TIMEFRAME);
  const id = `${format}_${timeframe}`;
  const snapshot = await db.collection(Collections.meta).doc(id).get();
  if (!snapshot.exists) throw new HttpsError("not-found", `No meta for ${format} over ${timeframe}.`);
  return { id, ...serialize(snapshot.data() as MetaDoc) };
}

export async function getEvents(db: Firestore, data: unknown): Promise<{ events: EventSummary[] }> {
  const payload = asPayload(data);
  const format = requireSlug(payload, "format");
  const limit = optionalInteger(payload, "limit", 20, 1, 100);
  const snapshot = await db
    .collection(Collections.events)
    .where("format", "==", format)
    .orderBy("date", "desc")
    .limit(limit)
    .get();
  return {
    events: snapshot.docs.map((doc) => ({ event_id: doc.id, ...serialize(doc.data() as EventDoc) })),
  };
}

export async function getDecklist(db: Firestore, data: unknown): Promise<DecklistResponse> {
  const deckId = requireText(asPayload(data), "deck_id", 64, /^[A-Za-z0-9_-]+$/);
  const snapshot = await db.collection(Collections.decks).doc(deckId).get();
  if (!snapshot.exists) throw new HttpsError("not-found", `No deck ${deckId}.`);
  return { deck_id: deckId, ...serialize(snapshot.data() as DeckDoc) };
}

export async function getCardDetails(db: Firestore, data: unknown): Promise<CardResponse> {
  const name = requireText(asPayload(data), "card_name", 200);
  const key = searchKey(name);
  const snapshot = await db
    .collection(Collections.cards)
    .where("search_names", "array-contains", key)
    .limit(10)
    .get();
  const cards = snapshot.docs.map((doc) => doc.data() as CardDoc);
  // A front-face lookup can also match another card's face; prefer the exact full name.
  const card = cards.find((candidate) => searchKey(candidate.name) === key) ?? cards[0];
  if (!card) throw new HttpsError("not-found", `No card named "${name}".`);
  return serialize(card);
}
