// Bundles src/ into dist/ next to the data `python -m mtglore publish` writes there.
import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("dist", { recursive: true });
await build({
  entryPoints: ["src/main.js"],
  bundle: true,
  format: "esm",
  minify: true,
  sourcemap: true,
  target: "es2022",
  outfile: "dist/app.js",
});
for (const file of ["index.html", "style.css"]) copyFileSync(`src/${file}`, `dist/${file}`);
