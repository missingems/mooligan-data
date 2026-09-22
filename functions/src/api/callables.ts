import { onCall } from "firebase-functions/v2/https";
import { firestore } from "../shared/firestore.js";
import * as handlers from "./handlers.js";

export const getMeta = onCall((request) => handlers.getMeta(firestore(), request.data));
export const getEvents = onCall((request) => handlers.getEvents(firestore(), request.data));
export const getDecklist = onCall((request) => handlers.getDecklist(firestore(), request.data));
export const getCardDetails = onCall((request) => handlers.getCardDetails(firestore(), request.data));
