import type { InboundEvent } from "../lib/types";

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * Parses only the stable envelope shared by every inbound WebSocket event.
 * Event-specific fields remain intentionally forward-compatible: unknown
 * event names are passed through so older clients can safely ignore them.
 */
export function parseInboundEvent(raw: unknown): InboundEvent | null {
  let value = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isRecord(value) || typeof value.event !== "string") return null;
  return value as InboundEvent;
}
