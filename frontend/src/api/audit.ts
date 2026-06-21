import { API_BASE_URL } from "./config";

export interface AuditSighting {
  timestamp: string;
  camera_id: string;
  direction: "entry" | "exit";
}

export interface AuthorizedPersonAudit {
  identity: string;
  first_entry_camera: string | null;
  first_entry_time: string | null;
  last_exit_camera: string | null;
  last_exit_time: string | null;
  status: "inside" | "exited";
  all_sightings: AuditSighting[];
}

export interface AuditSummary {
  total_unique_persons: number;
  total_unique_authorized: number;
  total_unique_unauthorized: number;
  authorized_currently_inside: number;
  unknown_currently_inside: number;
}

export interface UnknownAuditSummary {
  entry_count: number;
  exit_count: number;
  net_inside: number;
  unique_clusters: number;
  entry_cameras: Record<string, number>;
  exit_cameras: Record<string, number>;
}

export interface AuditReport {
  generated_at: string;
  window: { since: string; until: string };
  summary: AuditSummary;
  authorized_persons: AuthorizedPersonAudit[];
  unknown_summary: UnknownAuditSummary;
}

export async function fetchAuditReport(since?: string, until?: string): Promise<AuditReport> {
  const p = new URLSearchParams();
  if (since) p.set("since", since);
  if (until) p.set("until", until);
  const qs = p.toString() ? `?${p}` : "";
  const res = await fetch(`${API_BASE_URL}/audit/report${qs}`);
  if (!res.ok) throw new Error("Failed to fetch audit report");
  return res.json();
}
