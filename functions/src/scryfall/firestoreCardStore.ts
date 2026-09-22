import { FieldValue, type Firestore } from "firebase-admin/firestore";
import { Collections } from "../shared/schema.js";
import { cardDocumentId, type NormalizedCard } from "./normalizeCard.js";
import type { CardSyncStore } from "./syncCards.js";

// ~35k hashes split by the id's first hex digit: 16 documents of ~120 KB each,
// well under Firestore's 1 MiB limit, so a sync starts with 16 reads rather
// than reading every card.
const HASH_SHARDS = "0123456789abcdef".split("");

export class FirestoreCardStore implements CardSyncStore {
  constructor(private readonly db: Firestore) {}

  private hashDoc(shard: string) {
    return this.db.collection(Collections.syncState).doc("scryfall").collection("hashes").doc(shard);
  }

  async loadHashes(): Promise<Map<string, string>> {
    const snapshots = await this.db.getAll(...HASH_SHARDS.map((shard) => this.hashDoc(shard)));
    const hashes = new Map<string, string>();
    for (const snapshot of snapshots) {
      const entries = (snapshot.data()?.hashes ?? {}) as Record<string, string>;
      for (const [id, hash] of Object.entries(entries)) hashes.set(id, hash);
    }
    return hashes;
  }

  async commit(upserts: NormalizedCard[], deletes: string[]): Promise<void> {
    const batch = this.db.batch();
    const cards = this.db.collection(Collections.cards);
    for (const card of upserts) {
      batch.set(cards.doc(cardDocumentId(card)), { ...card, last_updated: FieldValue.serverTimestamp() });
    }
    for (const id of deletes) batch.delete(cards.doc(id));
    await batch.commit();
  }

  async saveHashes(hashes: Map<string, string>): Promise<void> {
    const shards = new Map(HASH_SHARDS.map((shard) => [shard, {} as Record<string, string>]));
    for (const [id, hash] of hashes) {
      const shard = shards.get(id[0]?.toLowerCase() ?? "") ?? shards.get("0")!;
      shard[id] = hash;
    }
    const batch = this.db.batch();
    for (const [shard, entries] of shards) batch.set(this.hashDoc(shard), { hashes: entries });
    await batch.commit();
  }

  async lastBulkUpdate(): Promise<string | undefined> {
    const snapshot = await this.db.collection(Collections.syncState).doc("scryfall").get();
    return snapshot.data()?.bulk_updated_at;
  }

  async recordSync(bulkUpdatedAt: string, stats: object): Promise<void> {
    await this.db.collection(Collections.syncState).doc("scryfall").set({
      bulk_updated_at: bulkUpdatedAt,
      last_synced: FieldValue.serverTimestamp(),
      stats,
    });
  }
}
