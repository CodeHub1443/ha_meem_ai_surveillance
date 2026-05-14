import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { AppSettings } from "@/types/surveillance";

const STORAGE_KEY = "tdi_settings";

const DEFAULT_SETTINGS: AppSettings = {
  cameras: [
    {
      id: "camera_01",
      name: "Front Entrance",
      rtsp_url: "rtsp://admin:password@192.168.1.100:554/stream",
      roi: { x1: 0, y1: 0, x2: 1920, y2: 1080 },
      active: true,
    },
  ],
  recognition: {
    similarity_threshold: 0.6,
    min_face_size: 80,
    match_margin: 0.05,
    identity_cooldown: 6,
    adaptive_blur: true,
    blur_threshold: 30,
    min_decision_time: 0.3,
    recency_decay: 0.95,
  },
  whatsapp: {
    enabled: false,
    phone_number_id: "",
    access_token: "",
    api_version: "v19.0",
    recipients: [],
    template:
      "⚠️ ALERT: Unauthorized person detected\nCamera: {camera_id}\nTime: {timestamp}\nSimilarity Score: {score}%",
    include_snapshot: true,
  },
  system: {
    api_base_url: "http://localhost:8000",
    device: "CUDA",
    tensorrt: false,
    trt_cache: "./trt_cache",
    log_level: "INFO",
    snapshot_retention_days: 30,
  },
};

interface Ctx {
  settings: AppSettings;
  setSettings: (s: AppSettings) => void;
  resetRecognition: () => void;
}

const SettingsContext = createContext<Ctx | null>(null);

function loadSettings(): AppSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<AppSettings>;
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
      recognition: { ...DEFAULT_SETTINGS.recognition, ...(parsed.recognition || {}) },
      whatsapp: { ...DEFAULT_SETTINGS.whatsapp, ...(parsed.whatsapp || {}) },
      system: { ...DEFAULT_SETTINGS.system, ...(parsed.system || {}) },
      cameras: parsed.cameras || DEFAULT_SETTINGS.cameras,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettingsState] = useState<AppSettings>(DEFAULT_SETTINGS);

  useEffect(() => {
    setSettingsState(loadSettings());
  }, []);

  const setSettings = useCallback((s: AppSettings) => {
    setSettingsState(s);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {
      /* ignore */
    }
  }, []);

  const resetRecognition = useCallback(() => {
    setSettings({ ...settings, recognition: DEFAULT_SETTINGS.recognition });
  }, [settings, setSettings]);

  const value = useMemo(() => ({ settings, setSettings, resetRecognition }), [settings, setSettings, resetRecognition]);

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used within SettingsProvider");
  return ctx;
}

export function useCameraList() {
  const { settings } = useSettings();
  return settings.cameras;
}

export { DEFAULT_SETTINGS };
