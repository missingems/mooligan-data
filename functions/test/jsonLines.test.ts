import { Readable } from "node:stream";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { parseJsonLines } from "../src/scryfall/jsonLines.js";

async function collect(source: Readable): Promise<unknown[]> {
  const items: unknown[] = [];
  for await (const item of parseJsonLines(source)) items.push(item);
  return items;
}

// Splits the input into small chunks so lines straddle chunk boundaries.
function chunked(buffer: Buffer, size = 7): Readable {
  const chunks: Buffer[] = [];
  for (let offset = 0; offset < buffer.length; offset += size) chunks.push(buffer.subarray(offset, offset + size));
  return Readable.from(chunks);
}

const text = '{"a":1}\n\n{"a":2}\r\n{"a":3}';

describe("parseJsonLines", () => {
  it("parses plain JSON Lines, skipping blank lines", async () => {
    expect(await collect(chunked(Buffer.from(text)))).toEqual([{ a: 1 }, { a: 2 }, { a: 3 }]);
  });

  it("inflates gzipped input", async () => {
    expect(await collect(chunked(gzipSync(Buffer.from(text))))).toEqual([{ a: 1 }, { a: 2 }, { a: 3 }]);
  });

  it("handles an empty stream", async () => {
    expect(await collect(Readable.from([]))).toEqual([]);
  });

  it("reports the line of invalid JSON", async () => {
    await expect(collect(Readable.from([Buffer.from('{"a":1}\n{oops}\n')]))).rejects.toThrow("line 2");
  });
});
