import { getApps, initializeApp } from "firebase-admin/app";
import { getFirestore, type Firestore } from "firebase-admin/firestore";

let db: Firestore | undefined;

/** The default Firestore instance, initialising the Admin SDK on first use. */
export function firestore(): Firestore {
  if (!db) {
    if (getApps().length === 0) initializeApp();
    db = getFirestore();
    db.settings({ ignoreUndefinedProperties: true });
  }
  return db;
}
