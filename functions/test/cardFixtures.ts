export function rawCard(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    object: "card",
    id: "0000579f-7b35-4ed3-b44c-db2a538066fe",
    oracle_id: "44623693-51d6-49ad-8cd7-140505caf02f",
    name: "Fury Sliver",
    layout: "normal",
    mana_cost: "{5}{R}",
    cmc: 6,
    type_line: "Creature — Sliver",
    oracle_text: "All Sliver creatures have double strike.",
    power: "3",
    toughness: "3",
    colors: ["R"],
    color_identity: ["R"],
    keywords: [],
    legalities: { modern: "legal", standard: "not_legal" },
    image_uris: { normal: "https://cards.scryfall.io/normal/front/0/0/fury.jpg" },
    set: "tsp",
    set_name: "Time Spiral",
    rarity: "uncommon",
    released_at: "2006-10-06",
    scryfall_uri: "https://scryfall.com/card/tsp/157/fury-sliver",
    prices: { usd: "0.25" },
    edhrec_rank: 5000,
    ...overrides,
  };
}

let counter = 0;

/** A card with a unique hexadecimal oracle id. */
export function uniqueCard(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  counter += 1;
  const hex = counter.toString(16).padStart(8, "0");
  return rawCard({
    id: `${hex}-0000-4000-8000-000000000000`,
    oracle_id: `${hex}-1111-4000-8000-000000000000`,
    name: `Card ${counter}`,
    ...overrides,
  });
}
