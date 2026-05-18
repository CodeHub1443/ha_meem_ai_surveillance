import { API_BASE_URL } from "./config";
import type { SurveillanceEvent, EventType } from "@/types/surveillance";

export interface EventsQuery {
  limit?: number;
  offset?: number;
  camera_id?: string;
  event_type?: EventType;
  identity?: string;
  since?: string;
  until?: string;
  employee_id?: string;
  designation?: string;
  working_area?: string;
}

export interface StatsSummary {
  authorized: number;
  unknown: number;
  total: number;
  unique_persons: number;
  unique_unauthorized: number | null;
  last_clustered_at: string | null;
  total_unknown_embeddings: number;
}

function buildQuery(q: EventsQuery): string {
  const p = new URLSearchParams();
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.offset != null && q.offset > 0) p.set("offset", String(q.offset));
  if (q.camera_id) p.set("camera_id", q.camera_id);
  if (q.event_type) p.set("event_type", q.event_type);
  if (q.identity) p.set("identity", q.identity);
  if (q.since) p.set("since", q.since);
  if (q.until) p.set("until", q.until);
  if (q.employee_id) p.set("employee_id", q.employee_id);
  if (q.designation) p.set("designation", q.designation);
  if (q.working_area) p.set("working_area", q.working_area);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export interface CameraLiveness {
  id: string;
  active: boolean;
  age_seconds: number | null;
}

export interface HealthResponse {
  status: string;
  total_events: number;
  dropped_events: number;
  cameras: CameraLiveness[];
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`);
  if (!res.ok) throw new Error("Health check failed");
  return res.json();
}

export async function fetchEvents(query: EventsQuery = {}): Promise<SurveillanceEvent[]> {
  const res = await fetch(`${API_BASE_URL}/events${buildQuery({ limit: 50, ...query })}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function fetchEventsCount(query: Omit<EventsQuery, "limit" | "offset"> = {}): Promise<number> {
  const p = new URLSearchParams();
  if (query.camera_id) p.set("camera_id", query.camera_id);
  if (query.event_type) p.set("event_type", query.event_type);
  if (query.identity) p.set("identity", query.identity);
  if (query.since) p.set("since", query.since);
  if (query.until) p.set("until", query.until);
  if (query.employee_id) p.set("employee_id", query.employee_id);
  if (query.designation) p.set("designation", query.designation);
  if (query.working_area) p.set("working_area", query.working_area);
  const qs = p.toString() ? `?${p}` : "";
  const res = await fetch(`${API_BASE_URL}/events/count${qs}`);
  if (!res.ok) throw new Error("Failed to fetch event count");
  const data = await res.json();
  const count = data?.count;
  if (typeof count !== "number") throw new Error(`Unexpected count response: ${JSON.stringify(data)}`);
  return count;
}

export async function fetchLatestEvents(query: EventsQuery = {}): Promise<SurveillanceEvent[]> {
  const res = await fetch(`${API_BASE_URL}/events/latest${buildQuery({ limit: 20, ...query })}`);
  if (!res.ok) throw new Error("Failed to fetch latest events");
  return res.json();
}

export async function fetchStatsSummary(query: {
  camera_id?: string;
  since?: string;
  until?: string;
} = {}): Promise<StatsSummary> {
  const p = new URLSearchParams();
  if (query.camera_id) p.set("camera_id", query.camera_id);
  if (query.since) p.set("since", query.since);
  if (query.until) p.set("until", query.until);
  const qs = p.toString() ? `?${p}` : "";
  const res = await fetch(`${API_BASE_URL}/stats/summary${qs}`);
  if (!res.ok) throw new Error("Failed to fetch stats summary");
  return res.json();
}

export interface ClusterGroup {
  cluster_id: number;
  track_count: number;
  first_seen: string;
  last_seen: string;
  cameras: string[];
  snapshots: string[];
}

export interface ClusterSingleton {
  track_id: number;
  first_seen: string;
  camera_id: string;
  snapshot: string | null;
}

export interface ClusterGroups {
  clusters: ClusterGroup[];
  singletons: ClusterSingleton[];
}

export async function fetchClusterGroups(maxSnapshots = 4): Promise<ClusterGroups> {
  const res = await fetch(
    `${API_BASE_URL}/cluster/unknowns/groups?max_snapshots=${maxSnapshots}`,
  );
  if (!res.ok) throw new Error("Failed to fetch cluster groups");
  return res.json();
}

export interface ClusteringResult {
  n_embeddings: number;
  n_tracks: number;
  n_clusters: number;
  n_noise: number;
  unique_unauthorized: number;
}

export interface ClusteringStatus {
  status: "idle" | "running" | "done" | "error";
  result: ClusteringResult | null;
  error: string | null;
}

export async function triggerClustering(
  minClusterSize = 2,
  distanceThreshold = 0.45,
): Promise<{ status: string }> {
  const res = await fetch(
    `${API_BASE_URL}/cluster/unknowns?min_cluster_size=${minClusterSize}&distance_threshold=${distanceThreshold}`,
    { method: "POST" },
  );
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? "Clustering failed");
  }
  return res.json();
}

export async function fetchClusteringStatus(): Promise<ClusteringStatus> {
  const res = await fetch(`${API_BASE_URL}/cluster/unknowns/status`);
  if (!res.ok) throw new Error("Failed to fetch clustering status");
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
