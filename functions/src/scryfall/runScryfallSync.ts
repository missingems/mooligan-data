import type { Firestore } from "firebase-admin/firestore";
import { fetchOracleBulkInfo } from "./bulkData.js";
import { FirestoreCardStore } from "./firestoreCardStore.js";
import { downloadJsonLines } from "./jsonLines.js";
import { syncCards, type SyncStats } from "./syncCards.js";

export interface ScryfallSyncResult {
  bulkUpdatedAt: string;
  skipped: boolean;
  stats?: SyncStats;
}

/** Downloads Scryfall's Oracle Cards file and upserts what changed into `cards`. */
export async function runScryfallSync(
  db: Firestore,
  { force = false, fetchImpl = fetch }: { force?: boolean; fetchImpl?: typeof fetch } = {},
): Promise<ScryfallSyncResult> {
  const store = new FirestoreCardStore(db);
  const info = await fetchOracleBulkInfo(fetchImpl);
  if (!force && (await store.lastBulkUpdate()) === info.updatedAt) {
    return { bulkUpdatedAt: info.updatedAt, skipped: true };
  }
  const stats = await syncCards(downloadJsonLines(info.jsonlDownloadUri, fetchImpl), store);
  await store.recordSync(info.updatedAt, stats);
  return { bulkUpdatedAt: info.updatedAt, skipped: false, stats };
}
