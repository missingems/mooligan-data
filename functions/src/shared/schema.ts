// Firestore document shapes. The Python scraper writes `meta`, `events` and
// `decks` with the same field names (see scraper/mtgmeta/models.py).

export interface MetaArchetype {
  name: string;
  percentage: number;
  id: string;
  /** Number of decks behind the percentage, when MTGGoldfish shows it. */
  deck_count?: number;
  /** The archetype's featured deck on MTGGoldfish, stored in `decks`. */
  deck_id?: string;
}

export interface MetaDoc {
  format: string;
  timeframe: string;
  last_updated: FirebaseFirestore.Timestamp;
  archetypes: MetaArchetype[];
}

export interface EventResult {
  player: string;
  archetype: string;
  finish: string;
  deck_id: string;
}

export interface EventDoc {
  event_name: string;
  format: string;
  date: FirebaseFirestore.Timestamp;
  results: EventResult[];
  url?: string;
  last_updated?: FirebaseFirestore.Timestamp;
}

export interface DeckCard {
  quantity: number;
  card_name: string;
}

export interface DeckDoc {
  player: string;
  archetype: string;
  mainboard: DeckCard[];
  sideboard: DeckCard[];
  format?: string;
  /** Null for an archetype's featured deck, which is not from a scraped event. */
  event_id?: string | null;
  last_updated?: FirebaseFirestore.Timestamp;
}

/** The subset of a Scryfall card object kept in `cards`. */
export interface CardDoc {
  id: string;
  oracle_id: string | null;
  name: string;
  /** Lower-cased full name plus each face name, for `getCardDetails`. */
  search_names: string[];
  layout: string;
  mana_cost: string | null;
  cmc: number | null;
  type_line: string | null;
  oracle_text: string | null;
  colors: string[] | null;
  color_identity: string[];
  keywords: string[];
  power: string | null;
  toughness: string | null;
  loyalty: string | null;
  defense: string | null;
  legalities: Record<string, string>;
  image_uris: Record<string, string> | null;
  card_faces: CardFace[] | null;
  set: string;
  set_name: string;
  rarity: string;
  released_at: string;
  scryfall_uri: string;
  /** Hash of every field above, used to skip unchanged cards on sync. */
  content_hash: string;
  last_updated: FirebaseFirestore.Timestamp;
}

export interface CardFace {
  name: string;
  mana_cost: string | null;
  type_line: string | null;
  oracle_text: string | null;
  power: string | null;
  toughness: string | null;
  loyalty: string | null;
  defense: string | null;
  image_uris: Record<string, string> | null;
}

export const Collections = {
  meta: "meta",
  events: "events",
  decks: "decks",
  cards: "cards",
  syncState: "sync_state",
} as const;
