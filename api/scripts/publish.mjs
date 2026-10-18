import { readFile } from "node:fs/promises";

const [baseURL, archetype, markdownPath, documentPath] = process.argv.slice(2);
const token = process.env.ADMIN_TOKEN;
const author = process.env.PRIMER_AUTHOR ?? "greg";
const note = process.env.PRIMER_NOTE;

if (!baseURL || !archetype || !markdownPath || !documentPath) {
  console.error("Usage: ADMIN_TOKEN=... node scripts/publish.mjs <base-url> <archetype> <markdown.md> <document.json>");
  process.exit(2);
}
if (!token) {
  console.error("ADMIN_TOKEN is not set");
  process.exit(2);
}

const markdown = await readFile(markdownPath, "utf8");
const document = JSON.parse(await readFile(documentPath, "utf8"));

const response = await fetch(`${baseURL.replace(/\/+$/, "")}/v1/primers/${archetype}`, {
  method: "PUT",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({ author, markdown, document, ...(note ? { note } : {}) }),
});

const text = await response.text();
console.log(`${response.status} ${text}`);
if (!response.ok) process.exit(1);
