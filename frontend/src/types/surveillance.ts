export type EventType = "AUTHORIZED" | "UNKNOWN";

export interface SurveillanceEvent {
  timestamp: string;
  camera_id: string;
  track_id: number;
  identity: string | null;
  score: number;
  event: EventType;
  snapshot: string | null;
}

export interface Camera {
  id: string;
  name: string;
  rtsp_url: string;
  roi: { x1: number; y1: number; x2: number; y2: number };
  active: boolean;
}

export interface RecognitionSettings {
  similarity_threshold: number;
  min_face_size: number;
  match_margin: number;
  identity_cooldown: number;
  adaptive_blur: boolean;
  blur_threshold: number;
  min_decision_time: number;
  recency_decay: number;
}

export interface WhatsAppSettings {
  enabled: boolean;
  phone_number_id: string;
  access_token: string;
  api_version: string;
  recipients: string[];
  template: string;
  include_snapshot: boolean;
}

export interface SystemSettings {
  api_base_url: string;
  device: "CUDA" | "CPU";
  tensorrt: boolean;
  trt_cache: string;
  log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  snapshot_retention_days: number;
}

export interface AppSettings {
  cameras: Camera[];
  recognition: RecognitionSettings;
  whatsapp: WhatsAppSettings;
  system: SystemSettings;
}

export interface Person {
  id: string;
  name: string;
  sample_count: number;
  thumbnail_url: string | null;
  avg_accuracy: number | null;
}
