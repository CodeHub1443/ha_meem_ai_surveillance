// All functions in this file are STUBS that return mock data.
// TODO: Replace each with a real backend endpoint when implemented.

import { API_BASE_URL } from "./config";
import type { Person } from "@/types/surveillance";

const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms));

export async function requestSnapshot(cameraId: string): Promise<{ image_base64: string; timestamp: string }> {
  const res = await fetch(`${API_BASE_URL}/cameras/${cameraId}/snapshot`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Snapshot failed: ${res.status}`);
  }
  return res.json() as Promise<{ image_base64: string; timestamp: string }>;
}

// TODO: Replace with real backend endpoint when implemented.
export async function testCamera(cameraId: string): Promise<{ success: boolean; latency_ms: number }> {
  void cameraId;
  await delay(600);
  return { success: Math.random() > 0.2, latency_ms: Math.floor(50 + Math.random() * 200) };
}

// TODO: Replace with real backend endpoint when implemented.
export async function saveSettings(payload: unknown): Promise<{ success: boolean }> {
  void payload;
  await delay();
  return { success: true };
}

export async function fetchPersons(): Promise<Person[]> {
  const res = await fetch(`${API_BASE_URL}/persons`);
  if (!res.ok) throw new Error(`Failed to fetch persons: ${res.status}`);
  return res.json() as Promise<Person[]>;
}

// TODO: Replace with real backend endpoint when implemented.
export async function createPerson(name: string, files: File[]): Promise<{ id: string; name: string }> {
  void files;
  await delay(700);
  return { id: `p${Date.now()}`, name };
}

// TODO: Replace with real backend endpoint when implemented.
export async function deletePerson(id: string): Promise<{ success: boolean }> {
  void id;
  await delay();
  return { success: true };
}

// TODO: Replace with a real backend endpoint that runs extract_faces.py then
//       build_gallery.py sequentially and returns a job_id for status polling.
export async function buildGallery(): Promise<{ job_id: string }> {
  await delay();
  return { job_id: `job_${Date.now()}` };
}

let _buildProgress = 0;
// TODO: Replace with real backend endpoint when implemented.
// The backend runs two steps: (1) extract_faces.py  0-50%
//                             (2) build_gallery.py 50-100%
export async function fetchBuildStatus(): Promise<{
  status: "idle" | "running" | "done";
  progress: number;
  message: string;
}> {
  await delay(150);
  _buildProgress = Math.min(100, _buildProgress + 8);
  const status = _buildProgress >= 100 ? "done" : "running";
  let message = "Step 1/2: Extracting faces from raw frames…";
  if (_buildProgress > 45) message = "Step 2/2: Building gallery embeddings…";
  if (_buildProgress > 80) message = "Step 2/2: Clustering embedding prototypes…";
  if (_buildProgress >= 100) {
    message = "Gallery ready!";
    setTimeout(() => (_buildProgress = 0), 1500);
  }
  return { status, progress: _buildProgress, message };
}

// TODO: Replace with real backend endpoint when implemented.
// Should return relative paths to aligned face crops stored in
// data/aligned_faces/{person_id}/ on the server.
export async function fetchPersonSamples(personId: string): Promise<string[]> {
  void personId;
  await delay(400);
  // Return empty array until backend serves the actual aligned face images
  return [];
}

// TODO: Replace with real backend endpoint when implemented.
export async function fetchGalleryInfo(): Promise<{ person_count: number; embedding_count: number; last_built: string }> {
  await delay();
  return { person_count: 3, embedding_count: 35, last_built: new Date(Date.now() - 3600_000).toISOString() };
}

// TODO: Replace with real backend endpoint when implemented.
export async function fetchPipelineStatus(): Promise<{ running: boolean; cameras: { id: string; fps: number; active_tracks: number }[] }> {
  await delay();
  return {
    running: true,
    cameras: [{ id: "camera_01", fps: 22, active_tracks: 2 }],
  };
}

// TODO: Replace with real backend endpoint when implemented.
export async function fetchPipelineStats(): Promise<{ cameras: { id: string; fps: number; decisions_per_min: number; status: string; active_tracks: number }[] }> {
  await delay();
  return {
    cameras: [
      { id: "camera_01", fps: 22 + Math.random() * 4, decisions_per_min: 14, status: "running", active_tracks: 2 },
    ],
  };
}

// TODO: Replace with real backend endpoint when implemented.
export async function fetchSseSubscribers(): Promise<{ count: number }> {
  await delay();
  return { count: 1 };
}

// TODO: Replace with real backend endpoint when implemented.
export async function fetchLogs(type: "events" | "bot" | "system"): Promise<{ lines: string[] }> {
  await delay();
  const now = new Date().toISOString();
  return {
    lines: [
      `[${now}] INFO  ${type} log started`,
      `[${now}] INFO  pipeline initialized`,
      `[${now}] WARNING low light detected on camera_01`,
      `[${now}] INFO  recognition complete`,
    ],
  };
}

// TODO: Replace with real backend endpoint when implemented.
export async function sendWhatsAppTest(): Promise<{ success: boolean; message: string }> {
  await delay(900);
  return { success: true, message: "Test notification sent." };
}

export const _STUB_API_BASE = API_BASE_URL;
