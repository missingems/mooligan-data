import { Timestamp } from "firebase-admin/firestore";

/** Callable responses are JSON; Firestore timestamps become ISO 8601 strings. */
export type Serialized<T> = T extends Timestamp
  ? string
  : T extends (infer U)[]
    ? Serialized<U>[]
    : T extends object
      ? { [K in keyof T]: Serialized<T[K]> }
      : T;

export function serialize<T>(value: T): Serialized<T> {
  if (value instanceof Timestamp) return value.toDate().toISOString() as Serialized<T>;
  if (Array.isArray(value)) return value.map(serialize) as Serialized<T>;
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, serialize(inner)])) as Serialized<T>;
  }
  return value as Serialized<T>;
}
