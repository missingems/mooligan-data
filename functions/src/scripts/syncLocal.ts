// Runs the Scryfall sync from a workstation, for the first load or a manual
// refresh. Uses Application Default Credentials:
//   gcloud auth application-default login
//   GCLOUD_PROJECT=<project-id> npm run sync:local -- [--force]
import { firestore } from "../shared/firestore.js";
import { runScryfallSync } from "../scryfall/runScryfallSync.js";

const result = await runScryfallSync(firestore(), { force: process.argv.includes("--force") });
console.log(JSON.stringify(result, null, 2));
