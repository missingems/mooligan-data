import config from "./config.js";

const FIREBASE_SDK = "https://www.gstatic.com/firebasejs/12.19.0";

/** The four backend calls, served by Firebase or by the bundled sample data. */
export async function createApi() {
  return config.firebase.projectId ? firebaseApi() : sampleApi();
}

async function firebaseApi() {
  const [{ initializeApp }, { getFunctions, httpsCallable }] = await Promise.all([
    import(`${FIREBASE_SDK}/firebase-app.js`),
    import(`${FIREBASE_SDK}/firebase-functions.js`),
  ]);
  const functions = getFunctions(initializeApp(config.firebase), config.functionsRegion);
  const call = (name) => async (data) => {
    try {
      return (await httpsCallable(functions, name)(data)).data;
    } catch (error) {
      throw new ApiError(error.code?.replace("functions/", "") ?? "unknown", error.message);
    }
  };
  return {
    source: "firebase",
    getMeta: call("getMeta"),
    getEvents: call("getEvents"),
    getDecklist: call("getDecklist"),
    getCardDetails: call("getCardDetails"),
  };
}

async function sampleApi() {
  const response = await fetch(new URL("./sample/data.json", import.meta.url));
  const data = await response.json();
  const notFound = (what) => {
    throw new ApiError("not-found", `${what} is not in the sample data.`);
  };
  return {
    source: "sample",
    async getMeta({ format, timeframe }) {
      const id = `${format}_${timeframe}`;
      return data.meta[id] ? { id, ...data.meta[id] } : notFound(`${format} over ${timeframe}`);
    },
    async getEvents({ format, limit = 20 }) {
      const events = Object.entries(data.events)
        .map(([event_id, event]) => ({ event_id, ...event }))
        .filter((event) => event.format === format)
        .sort((a, b) => b.date.localeCompare(a.date))
        .slice(0, limit);
      return { events };
    },
    async getDecklist({ deck_id }) {
      return data.decks[deck_id] ? { deck_id, ...data.decks[deck_id] } : notFound(`Deck ${deck_id}`);
    },
    // The sample has no card database, so ask Scryfall directly.
    async getCardDetails({ card_name }) {
      const url = `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(card_name)}`;
      const response = await fetch(url);
      return response.ok ? response.json() : notFound(card_name);
    },
  };
}

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}
