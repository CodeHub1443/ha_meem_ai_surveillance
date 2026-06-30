// All functions in this file are STUBS that return mock data.
// TODO: Replace each with a real backend endpoint when implemented.

import { API_BASE_URL } from "./config";
import type { AppSettings } from "@/types/surveillance";

const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms));

export async function requestSnapshot(cameraId: string): Promise<{ image_base64: string; timestamp: string; width: number; height: number }> {
  const res = await fetch(`${API_BASE_URL}/cameras/${cameraId}/snapshot`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Snapshot failed: ${res.status}`);
  }
  return res.json() as Promise<{ image_base64: string; timestamp: string; width: number; height: number }>;
}

// TODO: Replace with real backend endpoint when implemented.
export async function testCamera(cameraId: string): Promise<{ success: boolean; latency_ms: number }> {
  void cameraId;
  await delay(600);
  return { success: Math.random() > 0.2, latency_ms: Math.floor(50 + Math.random() * 200) };
}

export async function saveSettings(payload: AppSettings): Promise<{ success: boolean }> {
  // Persist all camera fields (name, id, rtsp_url, active, roi) to cameras.yaml via PUT /cameras
  const res = await fetch(`${API_BASE_URL}/cameras`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload.cameras),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `Camera save failed: ${res.status}`);
  }
  return { success: true };
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
