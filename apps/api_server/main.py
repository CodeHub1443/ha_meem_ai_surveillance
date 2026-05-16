import asyncio
import base64
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import cv2
import numpy as np
import yaml

from core import frame_buffer as _fb
from core.database.event_store import EventStore

# ── Gallery cache ──────────────────────────────────────────────────────────────
# Loaded once on first /persons request; reloaded if the file changes.
_gallery_cache: Optional[Dict[str, Any]] = None
_gallery_mtime: float = 0.0
_gallery_lock = threading.Lock()


def _load_gallery_path() -> str:
    try:
        with open("configs/dataset.yaml") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    return cfg.get("dataset", {}).get("gallery_embeddings", "dataset/gallery_embeddings.npy")


def _get_gallery() -> Dict[str, Any]:
    global _gallery_cache, _gallery_mtime
    path = _load_gallery_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _gallery_lock:
        if _gallery_cache is None or mtime != _gallery_mtime:
            try:
                _gallery_cache = np.load(path, allow_pickle=True).item()
                _gallery_mtime = mtime
            except Exception as exc:
                log.warning("Failed to load gallery for /persons: %s", exc)
                return {}
        return _gallery_cache

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="Ha-Meem AI Surveillance API")

# Thread pool for blocking OpenCV operations (snapshot endpoint only)
_snapshot_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot")

CAMERAS_CONFIG = "configs/cameras.yaml"


def _load_cameras() -> List[Dict]:
    """Read cameras list from cameras.yaml. Returns empty list on any error."""
    try:
        with open(CAMERAS_CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("cameras", [])
    except FileNotFoundError:
        log.warning("cameras.yaml not found at %s", CAMERAS_CONFIG)
        return []
    except Exception as e:
        log.error("Failed to load cameras config: %s", e)
        return []


def _capture_frame(rtsp_url: str):
    """Open RTSP stream, grab a fresh frame, return (success, frame)."""
    cap = cv2.VideoCapture(rtsp_url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # Drain stale buffered frames so we get the most current image
    for _ in range(4):
        cap.grab()
    ret, frame = cap.read()
    cap.release()
    return ret, frame

# ── CORS ───────────────────────────────────────────────────────────────────────
# Allow the Vite dev server (and any local origin) to call this API.
# In production, replace ["*"] with your actual frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ───────────────────────────────────────────────────────────────
# Serve captured snapshots so the frontend can display them by URL.
# The pipeline writes to snapshots/YYYY-MM-DD/filename.jpg
# Frontend accesses them as: http://localhost:8000/snapshots/2025-01-15/file.jpg
os.makedirs("snapshots", exist_ok=True)
app.mount("/snapshots", StaticFiles(directory="snapshots"), name="snapshots")

# Serve aligned face crops for the gallery enrolled-persons view.
# Frontend accesses them as: http://localhost:8000/faces/person_name/frame_001.jpg
_aligned_faces_dir = os.path.join("data", "aligned_faces")
os.makedirs(_aligned_faces_dir, exist_ok=True)
app.mount("/faces", StaticFiles(directory=_aligned_faces_dir), name="faces")

LOG_FILE = "logs/events.jsonl"

# ── SQLite event store (authoritative for all queries) ─────────────────────────

_event_store = EventStore()

# ── SSE subscriber queues ──────────────────────────────────────────────────────

_sse_subscribers: List[asyncio.Queue] = []
_sse_lock = threading.Lock()


def _tail_log_file():
    """Background thread: tail the JSONL log and push new events to SSE subscribers."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    last_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

    while True:
        try:
            if os.path.exists(LOG_FILE):
                size = os.path.getsize(LOG_FILE)
                if size > last_size:
                    with open(LOG_FILE, "r") as f:
                        f.seek(last_size)
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                with _sse_lock:
                                    for q in list(_sse_subscribers):
                                        try:
                                            q.put_nowait(event)
                                        except asyncio.QueueFull:
                                            pass
                            except json.JSONDecodeError:
                                pass
                    last_size = size
                elif size < last_size:
                    last_size = 0
        except Exception as e:
            log.error("Log tail error: %s", e)
        time.sleep(1.0)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    t = threading.Thread(target=_tail_log_file, daemon=True, name="log-tailer")
    t.start()


# ── Models ─────────────────────────────────────────────────────────────────────

class SurveillanceEvent(BaseModel):
    timestamp: str
    camera_id: str
    track_id: int
    identity: Optional[str] = None
    score: float
    event: str
    snapshot: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "message": "Ha-Meem AI Surveillance API",
        "endpoints": {
            "health": "/health",
            "latest": "/events/latest",
            "all": "/events",
            "stream": "/events/stream  (SSE)",
            "docs": "/docs",
        },
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "total_events": _event_store.count()}


@app.get("/events/latest", response_model=List[SurveillanceEvent])
def get_latest_events(
    limit: int = Query(default=20, ge=1, le=500),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None, description="AUTHORIZED or UNKNOWN"),
):
    """Most recent N events from the database, newest first."""
    return _event_store.query(
        camera_id=camera_id,
        identity=identity,
        event_type=event_type,
        limit=limit,
    )


@app.get("/events", response_model=List[SurveillanceEvent])
def get_all_events(
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO timestamp lower bound"),
    until: Optional[str] = Query(default=None, description="ISO timestamp upper bound"),
):
    """Paginated events from the database, newest first."""
    return _event_store.query(
        camera_id=camera_id,
        identity=identity,
        event_type=event_type,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@app.get("/events/count")
def get_events_count(
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
):
    """Total row count matching the given filters (for pagination UIs)."""
    return {
        "count": _event_store.count(
            camera_id=camera_id,
            identity=identity,
            event_type=event_type,
            since=since,
            until=until,
        )
    }


@app.get("/stats/summary")
def get_stats_summary(
    camera_id: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO timestamp lower bound"),
    until: Optional[str] = Query(default=None, description="ISO timestamp upper bound"),
):
    """Authorized vs unknown counts and unique known persons for a given period."""
    authorized = _event_store.count(camera_id=camera_id, event_type="AUTHORIZED", since=since, until=until)
    unknown = _event_store.count(camera_id=camera_id, event_type="UNKNOWN", since=since, until=until)
    unique_persons = _event_store.count_unique_identities(camera_id=camera_id, since=since, until=until)
    return {
        "authorized": authorized,
        "unknown": unknown,
        "total": authorized + unknown,
        "unique_persons": unique_persons,
    }


@app.get("/events/stream")
async def stream_events():
    """Server-Sent Events stream — pushes new events in real time."""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    with _sse_lock:
        _sse_subscribers.append(q)

    async def generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send a keepalive comment every 30 s to prevent proxy/browser
                    # from closing the connection during quiet periods.
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with _sse_lock:
                try:
                    _sse_subscribers.remove(q)
                except ValueError:
                    pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Persons (gallery) routes ───────────────────────────────────────────────────

@app.get("/persons")
def list_persons():
    """Return enrolled persons from the gallery with sample counts and avg recognition accuracy."""
    gallery = _get_gallery()
    if not gallery:
        return []

    # Per-identity avg score and most-recent snapshot from AUTHORIZED events
    rows = _event_store._conn().execute("""
        SELECT identity,
               AVG(score)       AS avg_score,
               MAX(snapshot)    AS latest_snapshot
        FROM events
        WHERE event_type = 'AUTHORIZED' AND identity IS NOT NULL
        GROUP BY identity
    """).fetchall()
    stats: Dict[str, dict] = {r["identity"]: dict(r) for r in rows}

    result = []
    for name, embeddings in gallery.items():
        s = stats.get(name, {})
        avg_score = s.get("avg_score")
        avg_accuracy = round(float(avg_score) * 100, 1) if avg_score is not None else None
        result.append({
            "id": name.lower().replace(" ", "_"),
            "name": name,
            "sample_count": len(embeddings),
            "thumbnail_url": s.get("latest_snapshot"),
            "avg_accuracy": avg_accuracy,
        })

    return sorted(result, key=lambda x: x["name"].lower())


# ── Camera routes ──────────────────────────────────────────────────────────────

@app.get("/cameras")
def list_cameras():
    """Return all cameras from cameras.yaml (id, name, active status, roi)."""
    cameras = _load_cameras()
    return [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            "active": bool(c.get("url")),
            "roi": c.get("roi"),
        }
        for c in cameras
    ]


@app.post("/cameras/{camera_id}/snapshot")
async def capture_snapshot(camera_id: str):
    """
    Capture a single JPEG frame from the camera's RTSP stream.
    Returns { image_base64: str, timestamp: str }.
    Runs the blocking OpenCV grab in a thread pool so the async loop stays free.
    """
    cameras = _load_cameras()
    cam = next((c for c in cameras if c.get("id") == camera_id), None)

    if cam is None:
        raise HTTPException(
            status_code=404,
            detail=f"Camera '{camera_id}' not found in {CAMERAS_CONFIG}",
        )

    rtsp_url = cam.get("url")
    if not rtsp_url:
        raise HTTPException(
            status_code=400,
            detail=f"Camera '{camera_id}' has no RTSP URL configured",
        )

    loop = asyncio.get_event_loop()
    try:
        ret, frame = await asyncio.wait_for(
            loop.run_in_executor(_snapshot_executor, _capture_frame, rtsp_url),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Snapshot timed out — camera may be offline or unreachable",
        )

    if not ret or frame is None:
        raise HTTPException(
            status_code=503,
            detail="Could not read frame from camera stream",
        )

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    img_b64 = base64.b64encode(buf.tobytes()).decode()

    return {
        "image_base64": img_b64,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/cameras/{camera_id}/stream-status")
def stream_status(camera_id: str):
    """Quick check: is the pipeline pushing fresh frames for this camera?"""
    age = _fb.age(camera_id)
    if age is None:
        return {"active": False, "age_seconds": None, "reason": "no frames yet — pipeline may not be running"}
    active = age < _fb.STALE_SECS
    return {"active": active, "age_seconds": round(age, 2), "reason": "ok" if active else "frame too old"}


@app.get("/cameras/{camera_id}/stream")
async def stream_camera(camera_id: str):
    """MJPEG stream for the browser. Reads annotated frames from the in-memory frame buffer."""
    cameras = _load_cameras()
    cam = next((c for c in cameras if c.get("id") == camera_id), None)
    if cam is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    async def generate() -> AsyncGenerator[bytes, None]:
        last_jpeg: bytes = b""
        try:
            while True:
                jpeg = _fb.get(camera_id)
                if jpeg is None:
                    await asyncio.sleep(0.5)
                    continue
                if jpeg is not last_jpeg:
                    last_jpeg = jpeg
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
                await asyncio.sleep(0.066)  # ~15 fps
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
