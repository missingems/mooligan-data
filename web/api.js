import config from "./config.js";

/**
 * Reads the published snapshots (see docs/data-format.md). A format's snapshot
 * holds its meta, events and archetype results; decklists are one file each;
 * card details come from Scryfall.
 */
export async function createApi() {
  const snapshots = new Map();
  const snapshot = (format) => {
    if (!snapshots.has(format)) {
      snapshots.set(format, getJson(`snapshots/${format}.json`).catch((error) => {
        snapshots.delete(format); // retry on the next call
        if (error.code === "not-found") throw new ApiError("not-found", `No ${format} data published yet.`);
        throw error;
      }));
    }
    return snapshots.get(format);
  };
  const notFound = (what) => {
    throw new ApiError("not-found", `${what} is not in the published data.`);
  };

  return {
    async getMeta({ format, timeframe }) {
      const { meta } = await snapshot(format);
      // Fall back to the widest window a format publishes.
      const entry = meta[timeframe] ?? meta[Object.keys(meta)[0]];
      return entry ? { format, windows: Object.keys(meta), ...entry } : notFound(`${format} over ${timeframe}`);
    },
    async getEvents({ format, limit = 20 }) {
      const events = (await snapshot(format)).events.slice(0, limit).map((event) => ({ format, ...event }));
      return { events };
    },
    async getEvent({ format, event_id }) {
      const event = (await snapshot(format)).events.find((candidate) => candidate.event_id === event_id);
      return event ? { format, ...event } : notFound(`Event ${event_id}`);
    },
    async getArchetype({ format, archetype_id }) {
      const archetype = (await snapshot(format)).archetypes[archetype_id];
      return archetype ? { format, ...archetype } : notFound(`Results for ${archetype_id}`);
    },
    async getDecklist({ deck_id }) {
      return getJson(`decks/${encodeURIComponent(deck_id)}.json`);
    },
    /** For decks stored before they carried an archetype id: find them in the snapshot. */
    async findArchetypeOfDeck({ format, deck_id }) {
      const { archetypes } = await snapshot(format);
      const match = Object.values(archetypes).find(
        (archetype) =>
          archetype.deck_id === deck_id || archetype.results.some((result) => result.deck_id === deck_id),
      );
      return match ? { archetype_id: match.archetype_id, name: match.name } : null;
    },
    /** Where a card is played, across every format. */
    async getCard({ slug }) {
      return getJson(`cards/${encodeURIComponent(slug)}.json`);
    },
    /** Upcoming in-store events near a published place, from Wizards' locator. */
    async getPlaces() {
      return getJson("locator/index.json").catch((error) => (error.code === "not-found" ? { places: {} } : Promise.reject(error)));
    },
    async getPlaceEvents({ slug }) {
      return getJson(`locator/${encodeURIComponent(slug)}.json`);
    },
    /** A commander's card inclusions and average decklist, from EDHREC. */
    async getCommander({ slug }) {
      return getJson(`edh/commanders/${encodeURIComponent(slug)}.json`);
    },
    async getCardDetails({ card_name }) {
      const url = `https://api.scryfall.com/cards/named?exact=${encodeURIComponent(card_name)}`;
      const response = await fetch(url);
      return response.ok ? response.json() : notFound(card_name);
    },
  };
}

async function getJson(path) {
  const response = await fetch(`${config.dataUrl}/${path}`);
  if (response.status === 404) throw new ApiError("not-found", `${path} is not published.`);
  if (!response.ok) throw new ApiError("unavailable", `Loading ${path} failed (${response.status}).`);
  return response.json();
}

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}
