import type { Firestore } from "firebase-admin/firestore";

type Data = Record<string, any>;
type Filter = (data: Data) => boolean;

/** Just enough of Firestore's query API for the callable handlers. */
export function fakeFirestore(collections: Record<string, Record<string, Data>>): Firestore {
  const query = (name: string, filters: Filter[] = [], order?: [string, "asc" | "desc"], max?: number): any => ({
    doc: (id: string) => ({
      get: async () => {
        const data = collections[name]?.[id];
        return { id, exists: data !== undefined, data: () => data };
      },
    }),
    where: (field: string, op: string, value: unknown) => {
      const filter: Filter =
        op === "==" ? (data) => data[field] === value : (data) => (data[field] ?? []).includes(value);
      return query(name, [...filters, filter], order, max);
    },
    orderBy: (field: string, direction: "asc" | "desc" = "asc") => query(name, filters, [field, direction], max),
    limit: (count: number) => query(name, filters, order, count),
    get: async () => {
      let docs = Object.entries(collections[name] ?? {})
        .filter(([, data]) => filters.every((filter) => filter(data)))
        .map(([id, data]) => ({ id, data: () => data }));
      if (order) {
        const [field, direction] = order;
        const value = (doc: { data: () => Data }) => doc.data()[field].toMillis();
        docs.sort((a, b) => (direction === "asc" ? value(a) - value(b) : value(b) - value(a)));
      }
      if (max !== undefined) docs = docs.slice(0, max);
      return { docs };
    },
  });
  return { collection: (name: string) => query(name) } as unknown as Firestore;
}
