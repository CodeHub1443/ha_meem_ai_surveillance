# HA-MEEM AI Surveillance — Claude Code Context

> Design principles, operational constraints, and code rules are in AGENT_CONTEXT.md. This file is a navigational and architectural reference for Claude Code sessions.

---

## Quick Orientation

This is a **real-time multi-camera face recognition surveillance system** for a factory entry gate. The pipeline runs continuously, classifying every tracked face as AUTHORIZED (known person) or UNKNOWN. Single-frame decisions are forbidden — all decisions require multi-frame embedding fusion.

Current deployment: Windows + CUDA 12.1. Future target: NVIDIA Jetson via DeepStream.

---

## Repository Layout

```
core/           # Pure CV logic — no FastAPI, no DB, no I/O
  detection/    # SCRFD face detector (ONNX/TensorRT)
  recognition/  # AdaFace 512-d embeddings (ONNX/TensorRT)
  tracking/     # OC-SORT multi-object tracker (per-camera instance)
  fusion/       # Multi-frame embedding aggregator
  quality/      # Adaptive blur thresholding
  clustering/   # Agglomerative clustering of unknown embeddings
  events/       # Event emission + snapshot writing (async)
  database/     # FaceDatabase (FAISS gallery) + SQLiteEventStore
  frame_buffer.py    # Thread-safe in-process JPEG frame sharing
  pipeline_state.py  # Per-track decision state machine
  io_worker.py       # Async I/O thread for events/snapshots

apps/
  entry_pipeline/main.py   # Orchestrator: spawns per-camera threads
  api_server/main.py       # FastAPI: REST + SSE + MJPEG endpoints
  alert_bot/               # WhatsApp alerting
  dataset_tools/           # Gallery building, face extraction

frontend/src/
  routes/       # dashboard, live, events, gallery, reports, settings, debug, index (lock)
  api/          # Typed API client functions (TanStack Query)
  context/      # SettingsContext, SSEContext (global real-time stream)
  hooks/        # useSSEStream, useHealthCheck, useMobile
  components/   # Shared UI components
  types/        # TypeScript interfaces
  i18n/         # English + Bengali translations

configs/
  default.yaml      # Pipeline defaults (thresholds, timers, quality gates)
  thresholds.yaml   # Similarity threshold, upgrade_margin, blur cutoffs
  cameras.yaml      # RTSP URLs, ROI coordinates, active flags
  tensorrt.yaml     # TensorRT FP16 engine cache settings
  dataset.yaml      # Gallery embedding file path

logs/           # JSONL event logs + events.db (SQLite WAL)
snapshots/      # Daily annotated frame saves (YYYY-MM-DD/)
data/           # Aligned face crops, gallery embeddings (.npy)
models/         # ONNX weights, TensorRT engines (never commit)
tests/          # pytest suite
```

---

## Tech Stack

| Layer | Stack |
|---|---|
| Detection | SCRFD via InsightFace + ONNX Runtime (TensorRT FP16) |
| Recognition | AdaFace 512-d embeddings via ONNX Runtime |
| Tracking | OC-SORT (one instance per camera thread) |
| Gallery matching | FAISS cosine similarity (CPU or GPU) |
| API | FastAPI + Uvicorn, sync + async mixed |
| Realtime streaming | SSE (`/events/stream`), MJPEG (`/cameras/{id}/stream`) |
| Database | SQLite WAL mode (`logs/events.db`) |
| Frontend | React 19 + TypeScript + TanStack Start/Router/Query |
| Styling | Tailwind CSS + Radix UI (shadcn components) |
| i18n | i18next (EN + BN) |
| Config | PyYAML, loaded once at startup via `core/utils/config.py` |

---

## Pipeline Data Flow

```
RTSP stream
  └─ per-camera thread
       ├─ SCRFD detector (shared, thread-safe)  →  face bboxes + landmarks
       ├─ OC-SORT tracker (per-camera)          →  stable track IDs
       ├─ ROI filter                             →  drop out-of-zone faces
       ├─ Quality gate (blur + size ≥140px)     →  drop bad frames
       ├─ AdaFace recognizer (shared)           →  512-d embeddings
       ├─ EmbeddingAggregator (per-track)       →  fused embedding
       ├─ FaceDatabase.match() (FAISS)          →  cosine similarity score
       ├─ PipelineState decision                →  AUTHORIZED / UNKNOWN
       └─ io_worker (async thread)              →  SQLite + snapshot write
```

---

## Key Invariants (Do Not Break)

- `core/` has zero imports from `apps/` or `frontend/` — it is framework-agnostic
- The SCRFD detector and AdaFace recognizer are **shared across camera threads** — they must be thread-safe (ONNX Runtime sessions are, by default)
- OC-SORT tracker instances are **per-camera** — never share tracker state across cameras
- EmbeddingAggregator is **per-track** — cleared when a track is lost
- All thresholds live in `configs/` YAML — never hardcode a float threshold in Python
- SQLite is opened with WAL mode — the pipeline writes, the API reads concurrently
- `frame_buffer.py` is the only mechanism for sharing frames between the pipeline thread and the API MJPEG endpoint — no inter-process communication

---

## Decision State Machine

Each track goes through:
```
PENDING → (enough frames + quality) → CANDIDATE
CANDIDATE → (score ≥ threshold) → AUTHORIZED
CANDIDATE → (score < threshold, held 3s) → UNKNOWN
AUTHORIZED / UNKNOWN → (track lost) → cleared
```

An UNKNOWN decision can be **upgraded** to AUTHORIZED if a later frame from the same track yields a high-confidence match (upgrade_margin configured in thresholds.yaml).

---

## API Surface

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Pipeline + API status |
| `/events` | GET | Filtered event query (camera, identity, time) |
| `/events/latest` | GET | Most recent N events |
| `/events/stream` | GET | SSE real-time event stream |
| `/stats/summary` | GET | Authorized vs unknown counts |
| `/persons` | GET | Enrolled gallery with stats |
| `/cameras` | GET | Configured cameras |
| `/cameras/{id}/snapshot` | GET | Single RTSP frame |
| `/cameras/{id}/stream` | GET | MJPEG stream (15fps, 960x540) |
| `/cluster/unknowns` | POST | Trigger agglomerative clustering |
| `/cluster/unknowns/groups` | GET | Current clustering result |

---

## Frontend Routes

| Route | Purpose |
|---|---|
| `/` | PIN lock screen |
| `/dashboard` | Live stats, pie chart, latest events |
| `/live` | MJPEG stream + real-time event overlay |
| `/events` | Filterable event table + CSV export |
| `/gallery` | Enrolled persons + thumbnails |
| `/reports` | Advanced analytics |
| `/settings` | Camera config, ROI drawing, thresholds |
| `/debug` | System diagnostics, log viewer |

---

## Development Conventions

- All Python classes use type hints; no `Any` unless unavoidable
- Config loaded once at startup and passed down — no `yaml.load()` inside hot paths
- Logging: use Python `logging` module with per-module loggers, not `print()`
- Tests in `tests/` use pytest; mock `cv2.VideoCapture` for unit tests
- Never commit model weights (`models/`) or `logs/events.db`
- Frontend API calls go through `frontend/src/api/` typed functions only — no raw `fetch()` in components
- SSE is consumed globally via `SSEContext` — do not open duplicate streams in components

---

## Current Branch: `withFrontEnd`

Active development area: frontend dashboard + backend API integration. Core CV pipeline is stable. Clustering feature recently added. OC-SORT upgrade from SORT is complete.

---

## Future: Jetson / DeepStream Migration

The `core/` directory is intentionally framework-agnostic to support future migration to NVIDIA DeepStream on Jetson. When that migration begins:
- SCRFD → NvInfer plugin with SCRFD engine
- AdaFace → NvInfer plugin with AdaFace engine  
- RTSP decoding → GStreamer `rtspsrc` + `nvv4l2decoder` (zero-copy NVMM)
- FAISS → FAISS-GPU with CUDA-managed memory
- Python orchestration → GStreamer pipeline with Python probes or C++ plugins
- The `core/` API contracts (detector, recognizer, tracker interfaces) should guide the DeepStream element design