import { HttpsError } from "firebase-functions/v2/https";

type Payload = Record<string, unknown>;

const SLUG = /^[a-z0-9][a-z0-9_-]{0,39}$/;

export function asPayload(data: unknown): Payload {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new HttpsError("invalid-argument", "Expected an object payload.");
  }
  return data as Payload;
}

/** A lower-case identifier such as a format ("modern") or timeframe ("30d"). */
export function requireSlug(payload: Payload, key: string, fallback?: string): string {
  const raw = payload[key] ?? fallback;
  if (typeof raw !== "string") throw new HttpsError("invalid-argument", `"${key}" must be a string.`);
  const value = raw.trim().toLowerCase();
  if (!SLUG.test(value)) throw new HttpsError("invalid-argument", `"${key}" is not a valid identifier.`);
  return value;
}

export function requireText(payload: Payload, key: string, maxLength: number, pattern?: RegExp): string {
  const raw = payload[key];
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new HttpsError("invalid-argument", `"${key}" must be a non-empty string.`);
  }
  const value = raw.trim();
  if (value.length > maxLength) throw new HttpsError("invalid-argument", `"${key}" is too long.`);
  if (pattern && !pattern.test(value)) throw new HttpsError("invalid-argument", `"${key}" has an invalid format.`);
  return value;
}

export function optionalInteger(payload: Payload, key: string, fallback: number, min: number, max: number): number {
  const raw = payload[key];
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== "number" || !Number.isInteger(raw) || raw < min || raw > max) {
    throw new HttpsError("invalid-argument", `"${key}" must be an integer from ${min} to ${max}.`);
  }
  return raw;
}
