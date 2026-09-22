import { logger } from "firebase-functions";
import { onSchedule } from "firebase-functions/v2/scheduler";
import { firestore } from "../shared/firestore.js";
import { runScryfallSync } from "./runScryfallSync.js";

export const scheduledScryfallSync = onSchedule(
  {
    schedule: "0 3 * * *",
    timeZone: "UTC",
    // The file is streamed, so memory stays flat; the first full load of
    // ~35k cards is what needs the long timeout.
    memory: "1GiB",
    timeoutSeconds: 1800,
    retryCount: 1,
  },
  async () => {
    const result = await runScryfallSync(firestore());
    logger.info("Scryfall sync finished", result);
  },
);
