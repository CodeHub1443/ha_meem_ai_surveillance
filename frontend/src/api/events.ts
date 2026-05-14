import { API_BASE_URL } from "./config";
import type { SurveillanceEvent, EventType } from "@/types/surveillance";

export interface EventsQuery {
  limit?: number;
  camera_id?: string;
  event_type?: EventType;
  identity?: string;
  since?: string;
}

function buildQuery(q: EventsQuery): string {
  const p = new URLSearchParams();
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.camera_id) p.set("camera_id", q.camera_id);
  if (q.event_type) p.set("event_type", q.event_type);
  if (q.identity) p.set("identity", q.identity);
  if (q.since) p.set("since", q.since);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function fetchHealth(): Promise<{ status: string; cached_events: number }> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function fetchEvents(query: EventsQuery = {}): Promise<SurveillanceEvent[]> {
  const res = await fetch(`${API_BASE_URL}/events${buildQuery({ limit: 500, ...query })}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function fetchLatestEvents(query: EventsQuery = {}): Promise<SurveillanceEvent[]> {
  const res = await fetch(`${API_BASE_URL}/events/latest${buildQuery({ limit: 20, ...query })}`);
  if (!res.ok) throw new Error("Failed to fetch latest events");
  return res.json();
}

export const SSE_EVENTS_URL = `${API_BASE_URL}/events/stream`;

/**
 * Converts a relative snapshot path (e.g. "snapshots/2025-01-15/file.jpg")
 * returned by the backend into a full URL the browser can load.
 * Returns null when the event has no snapshot.
 */
export function snapshotUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${API_BASE_URL}/${path}`;
}
