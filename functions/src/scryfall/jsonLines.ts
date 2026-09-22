import { createInterface } from "node:readline";
import { PassThrough, Readable } from "node:stream";
import { createGunzip } from "node:zlib";
import { scryfallHeaders } from "./bulkData.js";

/**
 * Yields each parsed line of a (possibly gzipped) JSON Lines stream, holding
 * one line in memory at a time.
 */
export async function* parseJsonLines(source: Readable): AsyncGenerator<unknown> {
  const lines = createInterface({ input: await decompressIfGzipped(source), crlfDelay: Infinity });
  let lineNumber = 0;
  for await (const line of lines) {
    lineNumber += 1;
    const trimmed = line.trim();
    if (trimmed === "") continue;
    try {
      yield JSON.parse(trimmed);
    } catch (error) {
      throw new Error(`Invalid JSON on line ${lineNumber}: ${(error as Error).message}`);
    }
  }
}

/** Downloads a JSON Lines file and streams its parsed lines. */
export async function* downloadJsonLines(url: string, fetchImpl: typeof fetch = fetch): AsyncGenerator<unknown> {
  const response = await fetchImpl(url, { headers: scryfallHeaders });
  if (!response.ok || !response.body) {
    throw new Error(`Download of ${url} failed: ${response.status} ${response.statusText}`);
  }
  yield* parseJsonLines(Readable.fromWeb(response.body as import("node:stream/web").ReadableStream));
}

// fetch already inflates a body sent with `Content-Encoding: gzip`, so the
// .gz file may arrive either compressed or not; sniff the gzip magic number.
async function decompressIfGzipped(source: Readable): Promise<Readable> {
  const iterator = source[Symbol.asyncIterator]();
  const first = await iterator.next();
  const head: Buffer | undefined = first.done ? undefined : Buffer.from(first.value);
  const rest = new PassThrough();
  (async () => {
    try {
      if (head) rest.write(head);
      for (let next = await iterator.next(); !next.done; next = await iterator.next()) {
        if (!rest.write(next.value)) await new Promise((resolve) => rest.once("drain", resolve));
      }
      rest.end();
    } catch (error) {
      rest.destroy(error as Error);
    }
  })();
  const isGzip = head !== undefined && head.length >= 2 && head[0] === 0x1f && head[1] === 0x8b;
  if (!isGzip) return rest;
  const gunzip = createGunzip();
  rest.on("error", (error) => gunzip.destroy(error));
  return rest.pipe(gunzip);
}
