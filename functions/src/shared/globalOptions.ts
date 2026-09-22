import { setGlobalOptions } from "firebase-functions/v2";

// Imported first by index.ts: ES modules evaluate imports in order, so this
// runs before any function is defined. Override the region in functions/.env.
setGlobalOptions({ region: process.env.FUNCTIONS_REGION ?? "us-central1", maxInstances: 10 });
