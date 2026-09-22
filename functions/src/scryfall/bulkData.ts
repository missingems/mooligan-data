const BULK_DATA_URL = "https://api.scryfall.com/bulk-data/oracle-cards";

// Scryfall asks every client for a descriptive User-Agent and an Accept header.
export const scryfallHeaders = {
  "User-Agent": "mtg-meta-pipeline/1.0 (+https://github.com/)",
  Accept: "application/json;q=0.9,*/*;q=0.8",
};

export interface BulkDataInfo {
  jsonlDownloadUri: string;
  updatedAt: string;
}

export async function fetchOracleBulkInfo(fetchImpl: typeof fetch = fetch): Promise<BulkDataInfo> {
  const response = await fetchImpl(BULK_DATA_URL, { headers: scryfallHeaders });
  if (!response.ok) {
    throw new Error(`Scryfall bulk-data request failed: ${response.status} ${response.statusText}`);
  }
  const body = (await response.json()) as { jsonl_download_uri?: string; updated_at?: string };
  if (!body.jsonl_download_uri || !body.updated_at) {
    throw new Error("Scryfall bulk-data response has no jsonl_download_uri");
  }
  return { jsonlDownloadUri: body.jsonl_download_uri, updatedAt: body.updated_at };
}
