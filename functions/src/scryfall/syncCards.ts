import { cardDocumentId, normalizeCard, type NormalizedCard } from "./normalizeCard.js";

/** Where the sync reads its previous state and writes cards. */
export interface CardSyncStore {
  /** Content hash of every stored card, keyed by document id. */
  loadHashes(): Promise<Map<string, string>>;
  /** Writes one batch of at most `batchSize` operations. */
  commit(upserts: NormalizedCard[], deletes: string[]): Promise<void>;
  saveHashes(hashes: Map<string, string>): Promise<void>;
}

export interface SyncOptions {
  /** Firestore allows 500 writes per batch. */
  batchSize?: number;
  /** Batches committed at once. */
  concurrency?: number;
  /**
   * Cards missing from the bulk file are deleted only when the file held at
   * least this many cards, so a truncated download never empties the collection.
   */
  minCardsForDeletion?: number;
}

export interface SyncStats {
  read: number;
  skippedInvalid: number;
  unchanged: number;
  upserted: number;
  deleted: number;
  batches: number;
}

export async function syncCards(
  rawCards: AsyncIterable<unknown>,
  store: CardSyncStore,
  { batchSize = 500, concurrency = 4, minCardsForDeletion = 10_000 }: SyncOptions = {},
): Promise<SyncStats> {
  const previous = await store.loadHashes();
  const next = new Map<string, string>();
  const stats: SyncStats = { read: 0, skippedInvalid: 0, unchanged: 0, upserted: 0, deleted: 0, batches: 0 };
  const inFlight = new Set<Promise<void>>();
  let failure: { error: unknown } | undefined;
  let upserts: NormalizedCard[] = [];
  let deletes: string[] = [];

  // Stop at the first failed batch rather than after the whole file.
  const throwIfFailed = () => {
    if (failure) throw failure.error;
  };

  const flush = async () => {
    if (upserts.length > 0 || deletes.length > 0) {
      stats.batches += 1;
      const tracked: Promise<void> = store.commit(upserts, deletes).then(
        () => void inFlight.delete(tracked),
        (error: unknown) => {
          failure ??= { error };
          inFlight.delete(tracked);
        },
      );
      inFlight.add(tracked);
      upserts = [];
      deletes = [];
    }
    if (inFlight.size >= concurrency) await Promise.race(inFlight);
    throwIfFailed();
  };

  for await (const raw of rawCards) {
    stats.read += 1;
    const card = normalizeCard(raw as Record<string, unknown>);
    if (!card) {
      stats.skippedInvalid += 1;
      continue;
    }
    const id = cardDocumentId(card);
    if (next.has(id)) continue;
    next.set(id, card.content_hash);
    if (previous.get(id) === card.content_hash) {
      stats.unchanged += 1;
      continue;
    }
    upserts.push(card);
    stats.upserted += 1;
    if (upserts.length >= batchSize) await flush();
  }

  if (next.size >= minCardsForDeletion) {
    for (const id of previous.keys()) {
      if (next.has(id)) continue;
      deletes.push(id);
      stats.deleted += 1;
      if (deletes.length >= batchSize) await flush();
    }
  } else {
    // Keep the old hashes of cards we could not confirm, so they are not rewritten later.
    for (const [id, hash] of previous) if (!next.has(id)) next.set(id, hash);
  }
  await flush();
  await Promise.all(inFlight);
  throwIfFailed();
  await store.saveHashes(next);
  return stats;
}
