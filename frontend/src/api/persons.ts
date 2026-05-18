import { API_BASE_URL } from "./config";
import type { Person, PersonStatus } from "@/types/surveillance";

export async function fetchPersons(status?: PersonStatus): Promise<Person[]> {
  const qs = status ? `?status=${status}` : "";
  const res = await fetch(`${API_BASE_URL}/persons${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch persons: ${res.status}`);
  return res.json() as Promise<Person[]>;
}

export async function getPerson(id: string): Promise<Person> {
  const res = await fetch(`${API_BASE_URL}/persons/${id}`);
  if (!res.ok) throw new Error(`Person not found: ${res.status}`);
  return res.json() as Promise<Person>;
}

export interface CreatePersonPayload {
  name: string;
  employee_id?: string;
  designation?: string;
  working_area?: string;
  images?: File[];
}

export async function createPerson(payload: CreatePersonPayload): Promise<Person> {
  const form = new FormData();
  form.append("name", payload.name);
  if (payload.employee_id) form.append("employee_id", payload.employee_id);
  if (payload.designation) form.append("designation", payload.designation);
  if (payload.working_area) form.append("working_area", payload.working_area);
  for (const file of payload.images ?? []) {
    form.append("images", file);
  }
  const res = await fetch(`${API_BASE_URL}/persons`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Failed to create person: ${res.status}`);
  }
  return res.json() as Promise<Person>;
}

export interface UpdatePersonPayload {
  employee_id?: string;
  designation?: string;
  working_area?: string;
}

export async function updatePerson(id: string, payload: UpdatePersonPayload): Promise<Person> {
  const res = await fetch(`${API_BASE_URL}/persons/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Failed to update person: ${res.status}`);
  }
  return res.json() as Promise<Person>;
}

export async function deletePerson(id: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/persons/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Failed to delete person: ${res.status}`);
  }
}

export async function fetchPersonSamples(personId: string): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/persons/${personId}/samples`);
  if (!res.ok) throw new Error(`Failed to fetch samples: ${res.status}`);
  const data = await res.json() as { urls?: unknown };
  return Array.isArray(data?.urls) ? (data.urls as string[]) : [];
}

// ── Gallery build ──────────────────────────────────────────────────────────────

export interface BuildStatus {
  running: boolean;
  last_result: {
    success: boolean;
    persons_enrolled?: number;
    error?: string;
  } | null;
}

export async function buildGallery(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE_URL}/gallery/build`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Build failed: ${res.status}`);
  }
  return res.json() as Promise<{ status: string }>;
}

export async function fetchBuildStatus(): Promise<BuildStatus> {
  const res = await fetch(`${API_BASE_URL}/gallery/build/status`);
  if (!res.ok) throw new Error("Failed to fetch build status");
  return res.json() as Promise<BuildStatus>;
}
