import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import cv2
import numpy as np
import yaml

from core import frame_buffer as _fb
from core import io_worker as _io_worker
from core import pipeline_metrics as _pipeline_metrics
from core.clustering import run_clustering
from core.database.event_store import EventStore
from core.database.person_store import PersonStore, make_person_id

# ── Gallery cache ──────────────────────────────────────────────────────────────
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


from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger(__name__)

app = FastAPI(title="Ha-Meem AI Surveillance API")

_snapshot_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snapshot")

CAMERAS_CONFIG = "configs/cameras.yaml"


def _load_aligned_faces_dir() -> str:
    try:
        with open("configs/dataset.yaml") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    # Mirror the path build_gallery.py reads so uploads land where the build expects them
    return cfg.get("dataset", {}).get("aligned_faces", "dataset/aligned_faces")


ALIGNED_FACES_DIR = _load_aligned_faces_dir()


def _load_cameras() -> List[Dict]:
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
    cap = cv2.VideoCapture()
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8_000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5_000)
    cap.open(rtsp_url)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(4):
        cap.grab()
    ret, frame = cap.read()
    cap.release()
    return ret, frame


# ── CORS ───────────────────────────────────────────────────────────────────────

_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ───────────────────────────────────────────────────────────────

os.makedirs("snapshots", exist_ok=True)
app.mount("/snapshots", StaticFiles(directory="snapshots"), name="snapshots")

os.makedirs(ALIGNED_FACES_DIR, exist_ok=True)
app.mount("/faces", StaticFiles(directory=ALIGNED_FACES_DIR), name="faces")

LOG_FILE = "logs/events.jsonl"

# ── Stores ─────────────────────────────────────────────────────────────────────

_event_store = EventStore()
_person_store = PersonStore()

# ── SSE subscriber queues ──────────────────────────────────────────────────────

_sse_subscribers: List[asyncio.Queue] = []
_sse_lock = threading.Lock()
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _sse_put_nowait(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def _tail_log_file():
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
                                if _event_loop and not _event_loop.is_closed():
                                    with _sse_lock:
                                        snapshot = list(_sse_subscribers)
                                    for q in snapshot:
                                        _event_loop.call_soon_threadsafe(
                                            _sse_put_nowait, q, event
                                        )
                            except json.JSONDecodeError:
                                pass
                    last_size = size
                elif size < last_size:
                    last_size = 0
        except Exception as e:
            log.error("Log tail error: %s", e)
        with _sse_lock:
            has_subs = bool(_sse_subscribers)
        time.sleep(0.1 if has_subs else 2.0)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    t = threading.Thread(target=_tail_log_file, daemon=True, name="log-tailer")
    t.start()


# ── Pydantic models ─────────────────────────────────────────────────────────────

class SurveillanceEvent(BaseModel):
    timestamp: str
    camera_id: str
    track_id: int
    identity: Optional[str] = None
    score: float
    event: str
    snapshot: Optional[str] = None
    employee_id: Optional[str] = None
    designation: Optional[str] = None
    working_area: Optional[str] = None


class PersonOut(BaseModel):
    id: str
    name: str
    employee_id: Optional[str] = None
    designation: Optional[str] = None
    working_area: Optional[str] = None
    status: str
    thumbnail_url: Optional[str] = None
    sample_count: int = 0
    avg_accuracy: Optional[float] = None
    created_at: str


class PersonCreate(BaseModel):
    name: str
    employee_id: Optional[str] = None
    designation: Optional[str] = None
    working_area: Optional[str] = None


class PersonUpdate(BaseModel):
    employee_id: Optional[str] = None
    designation: Optional[str] = None
    working_area: Optional[str] = None


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
    cam_liveness = []
    for cam in _load_cameras():
        cid = cam.get("id")
        age = _fb.age(cid)
        cam_liveness.append({
            "id": cid,
            "active": age is not None and age < _fb.STALE_SECS,
            "age_seconds": round(age, 2) if age is not None else None,
        })
    return {
        "status": "ok",
        "total_events": _event_store.count(),
        "dropped_events": _io_worker.get_dropped_count(),
        "cameras": cam_liveness,
    }


# ── Events ─────────────────────────────────────────────────────────────────────

def _events_with_person_data(
    camera_id: Optional[str] = None,
    identity: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    employee_id: Optional[str] = None,
    designation: Optional[str] = None,
    working_area: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict]:
    """Query events with a LEFT JOIN on persons for employee metadata.
    Employee filter params narrow results to only events with matching person records.
    """
    clauses: List[str] = []
    params: List = []

    if camera_id:
        clauses.append("e.camera_id = ?"); params.append(camera_id)
    if identity:
        clauses.append("e.identity LIKE ?"); params.append(f"%{identity}%")
    if event_type:
        clauses.append("e.event_type = ?"); params.append(event_type.upper())
    if since:
        clauses.append("e.timestamp >= ?"); params.append(since)
    if until:
        clauses.append("e.timestamp <= ?"); params.append(until)
    if employee_id:
        clauses.append("p.employee_id LIKE ?"); params.append(f"%{employee_id}%")
    if designation:
        clauses.append("p.designation LIKE ?"); params.append(f"%{designation}%")
    if working_area:
        clauses.append("p.working_area LIKE ?"); params.append(f"%{working_area}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])

    sql = f"""
        SELECT e.timestamp, e.camera_id, e.track_id, e.identity, e.score,
               e.event_type AS event, e.snapshot,
               p.employee_id, p.designation, p.working_area
        FROM events e
        LEFT JOIN persons p ON e.identity = p.id
        {where}
        ORDER BY e.timestamp DESC
        LIMIT ? OFFSET ?
    """
    rows = _person_store._conn().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _events_count_with_person_filters(
    camera_id=None, identity=None, event_type=None,
    since=None, until=None,
    employee_id=None, designation=None, working_area=None,
) -> int:
    clauses: List[str] = []
    params: List = []

    if camera_id:
        clauses.append("e.camera_id = ?"); params.append(camera_id)
    if identity:
        clauses.append("e.identity LIKE ?"); params.append(f"%{identity}%")
    if event_type:
        clauses.append("e.event_type = ?"); params.append(event_type.upper())
    if since:
        clauses.append("e.timestamp >= ?"); params.append(since)
    if until:
        clauses.append("e.timestamp <= ?"); params.append(until)
    if employee_id:
        clauses.append("p.employee_id LIKE ?"); params.append(f"%{employee_id}%")
    if designation:
        clauses.append("p.designation LIKE ?"); params.append(f"%{designation}%")
    if working_area:
        clauses.append("p.working_area LIKE ?"); params.append(f"%{working_area}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT COUNT(*) FROM events e LEFT JOIN persons p ON e.identity = p.id {where}"
    return _person_store._conn().execute(sql, params).fetchone()[0]


@app.get("/events/latest", response_model=List[SurveillanceEvent])
def get_latest_events(
    limit: int = Query(default=20, ge=1, le=500),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
):
    return _events_with_person_data(
        camera_id=camera_id, identity=identity, event_type=event_type, limit=limit
    )


@app.get("/events", response_model=List[SurveillanceEvent])
def get_all_events(
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    employee_id: Optional[str] = Query(default=None),
    designation: Optional[str] = Query(default=None),
    working_area: Optional[str] = Query(default=None),
):
    return _events_with_person_data(
        camera_id=camera_id, identity=identity, event_type=event_type,
        since=since, until=until,
        employee_id=employee_id, designation=designation, working_area=working_area,
        limit=limit, offset=offset,
    )


@app.get("/events/count")
def get_events_count(
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
    employee_id: Optional[str] = Query(default=None),
    designation: Optional[str] = Query(default=None),
    working_area: Optional[str] = Query(default=None),
):
    return {
        "count": _events_count_with_person_filters(
            camera_id=camera_id, identity=identity, event_type=event_type,
            since=since, until=until,
            employee_id=employee_id, designation=designation, working_area=working_area,
        )
    }


@app.get("/stats/summary")
def get_stats_summary(
    camera_id: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    until: Optional[str] = Query(default=None),
):
    authorized = _event_store.count(camera_id=camera_id, event_type="AUTHORIZED", since=since, until=until)
    unknown = _event_store.count(camera_id=camera_id, event_type="UNKNOWN", since=since, until=until)
    unique_persons = _event_store.count_unique_identities(camera_id=camera_id, since=since, until=until)
    unique_unauthorized = _event_store.count_unique_unauthorized(camera_id=camera_id, since=since, until=until)
    meta = _event_store.get_cluster_meta()
    return {
        "authorized": authorized,
        "unknown": unknown,
        "total": authorized + unknown,
        "unique_persons": unique_persons,
        "unique_unauthorized": unique_unauthorized,
        "last_clustered_at": meta["last_run_at"] if meta else None,
        "total_unknown_embeddings": _event_store.count_unknown_embeddings(),
    }



@app.get("/stats/pipeline")
def get_pipeline_metrics():
    """Per-camera pipeline health metrics for the Phase 0 baseline.

    Returns alignment fallback counts, track flip counts, decided-clobber
    counts, and events-per-track distribution for every active camera worker.
    All counters are since process start (reset on restart).
    """
    return {
        "cameras": _pipeline_metrics.all_snapshots(),
        "io_dropped_events": _io_worker.get_dropped_count(),
    }


# ── Clustering ─────────────────────────────────────────────────────────────────

_clustering_lock = threading.Lock()
_clustering_state: dict = {"status": "idle", "result": None, "error": None}


def _run_clustering_bg(min_cluster_size: int, distance_threshold: float) -> None:
    global _clustering_state
    try:
        result = run_clustering(
            min_cluster_size=min_cluster_size,
            distance_threshold=distance_threshold,
        )
        # Free embedding BLOBs for rows that now have a cluster label.
        # Rows are kept for audit; only the 2 KB BLOB per row is nulled out.
        try:
            pruned = _event_store.prune_clustered_embeddings()
            if pruned:
                log.info("Pruned %d embedding BLOBs after clustering", pruned)
        except Exception as prune_exc:
            log.warning("prune_clustered_embeddings failed: %s", prune_exc)
        _clustering_state = {"status": "done", "result": result, "error": None}
    except Exception as exc:
        _clustering_state = {"status": "error", "result": None, "error": str(exc)}
    finally:
        _clustering_lock.release()


@app.get("/cluster/unknowns/groups")
def get_cluster_groups(max_snapshots: int = Query(default=4, ge=1, le=10)):
    return _event_store.get_cluster_groups(max_snapshots=max_snapshots)


@app.get("/cluster/unknowns/status")
def get_clustering_status():
    return _clustering_state


@app.post("/cluster/unknowns")
def trigger_clustering(
    min_cluster_size: int = Query(default=2, ge=2, le=50),
    distance_threshold: float = Query(default=0.45, ge=0.1, le=1.0),
):
    global _clustering_state
    if not _clustering_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Clustering already in progress")
    _clustering_state = {"status": "running", "result": None, "error": None}
    t = threading.Thread(
        target=_run_clustering_bg,
        args=(min_cluster_size, distance_threshold),
        daemon=True,
        name="clustering",
    )
    t.start()
    return {"status": "started"}


# ── SSE ────────────────────────────────────────────────────────────────────────

@app.get("/events/stream")
async def stream_events():
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


# ── Persons (gallery metadata) ─────────────────────────────────────────────────

def _enrich_persons(persons: List[Dict]) -> List[PersonOut]:
    """Merge PersonStore records with live gallery stats (sample count, avg accuracy)."""
    gallery = _get_gallery()

    rows = _event_store._conn().execute("""
        SELECT identity,
               AVG(score)    AS avg_score,
               MAX(snapshot) AS latest_snapshot
        FROM events
        WHERE event_type = 'AUTHORIZED' AND identity IS NOT NULL
        GROUP BY identity
    """).fetchall()
    stats: Dict[str, dict] = {r["identity"]: dict(r) for r in rows}

    result = []
    for p in persons:
        pid = p["id"]
        name = p["name"]
        s = stats.get(pid, {})
        avg_score = s.get("avg_score")
        embeddings = gallery.get(pid, [])
        thumbnail = p.get("thumbnail_url") or s.get("latest_snapshot")
        result.append(PersonOut(
            id=p["id"],
            name=name,
            employee_id=p.get("employee_id"),
            designation=p.get("designation"),
            working_area=p.get("working_area"),
            status=p["status"],
            thumbnail_url=thumbnail,
            sample_count=len(embeddings),
            avg_accuracy=round(float(avg_score) * 100, 1) if avg_score is not None else None,
            created_at=p["created_at"],
        ))
    return result


@app.get("/persons", response_model=List[PersonOut])
def list_persons(status: Optional[str] = Query(default=None, description="'pending' or 'enrolled'")):
    """Return persons filtered by status. Enriched with gallery sample count and avg accuracy."""
    if status and status not in ("pending", "enrolled"):
        raise HTTPException(status_code=400, detail="status must be 'pending' or 'enrolled'")
    persons = _person_store.list(status=status)
    return _enrich_persons(persons)


@app.post("/persons", response_model=PersonOut, status_code=201)
def create_person(
    name: str = Form(...),
    employee_id: Optional[str] = Form(default=None),
    designation: Optional[str] = Form(default=None),
    working_area: Optional[str] = Form(default=None),
    images: List[UploadFile] = File(default=[]),
):
    """Create a new person (status=pending) and optionally upload face images."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Use the same ID derivation as PersonStore.create() so both sides agree.
    # The old re.sub(r"[^a-z0-9_]") stripped Unicode letters, turning Bengali
    # names like "রাহেলা" into "person" and causing silent ID collisions.
    person_id = make_person_id(name)
    if _person_store.exists(person_id):
        raise HTTPException(status_code=409, detail=f"Person '{name}' already exists")

    # Save uploaded face images to aligned_faces dir
    person_dir = Path(ALIGNED_FACES_DIR) / person_id
    person_dir.mkdir(parents=True, exist_ok=True)

    thumbnail_url = None
    for idx, img_file in enumerate(images):
        if not img_file.content_type or not img_file.content_type.startswith("image/"):
            continue
        ext = Path(img_file.filename or "frame.jpg").suffix or ".jpg"
        dest = person_dir / f"frame_{idx:03d}{ext}"
        with open(dest, "wb") as f:
            f.write(img_file.file.read())
        if thumbnail_url is None:
            thumbnail_url = f"/faces/{person_id}/{dest.name}"

    try:
        person_id = _person_store.create(
            name=name,
            employee_id=employee_id or None,
            designation=designation or None,
            working_area=working_area or None,
            thumbnail_url=thumbnail_url,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Person '{name}' already exists")

    p = _person_store.get(person_id)
    return _enrich_persons([p])[0]


@app.patch("/persons/{person_id}", response_model=PersonOut)
def update_person(person_id: str, body: PersonUpdate):
    """Update employee metadata for a person."""
    found = _person_store.update(
        person_id,
        employee_id=body.employee_id,
        designation=body.designation,
        working_area=body.working_area,
    )
    if not found:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")
    p = _person_store.get(person_id)
    return _enrich_persons([p])[0]


@app.delete("/persons/{person_id}", status_code=204)
def delete_person(person_id: str):
    """Delete a person record and their aligned face images."""
    found = _person_store.delete(person_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")
    person_dir = Path(ALIGNED_FACES_DIR) / person_id
    if person_dir.exists():
        shutil.rmtree(person_dir, ignore_errors=True)


@app.get("/persons/{person_id}", response_model=PersonOut)
def get_person(person_id: str):
    p = _person_store.get(person_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")
    return _enrich_persons([p])[0]


@app.get("/persons/{person_id}/samples")
def get_person_samples(person_id: str):
    """Return URLs for all aligned face crop images stored for a person."""
    if not _person_store.get(person_id):
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")
    person_dir = Path(ALIGNED_FACES_DIR) / person_id
    if not person_dir.exists():
        return {"urls": []}
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(f for f in person_dir.iterdir() if f.suffix.lower() in exts)
    urls = [f"/faces/{person_id}/{f.name}" for f in files]
    return {"urls": urls}


# ── Gallery build ──────────────────────────────────────────────────────────────

_build_status: Dict[str, Any] = {"running": False, "last_result": None}
_build_lock = threading.Lock()


def _run_build_gallery():
    """Blocking gallery build — called in a thread. Updates _build_status on completion."""
    global _build_status
    try:
        # Import here to avoid loading heavy CV deps at module level
        from apps.dataset_tools.build_gallery import main as _build_gallery_main
        built_ids = _build_gallery_main()  # returns set of person_id strings built
        built_ids = built_ids or set()
        n_enrolled = _person_store.enroll_by_ids(built_ids)
        with _build_lock:
            _build_status = {
                "running": False,
                "last_result": {"persons_enrolled": n_enrolled, "success": True},
            }
    except Exception as exc:
        log.error("Gallery build failed: %s", exc)
        with _build_lock:
            _build_status = {
                "running": False,
                "last_result": {"success": False, "error": str(exc)},
            }


@app.post("/gallery/build")
def build_gallery_endpoint():
    """Trigger a gallery rebuild in the background. Returns immediately."""
    with _build_lock:
        if _build_status["running"]:
            raise HTTPException(status_code=409, detail="Gallery build already in progress")
        _build_status["running"] = True

    t = threading.Thread(target=_run_build_gallery, daemon=True, name="gallery-build")
    t.start()
    return {"status": "started"}


@app.get("/gallery/build/status")
def gallery_build_status():
    """Poll the status of the most recent gallery build."""
    with _build_lock:
        return {
            "running": _build_status["running"],
            "last_result": _build_status["last_result"],
        }


# ── Cameras ────────────────────────────────────────────────────────────────────

@app.get("/cameras")
def list_cameras():
    cameras = _load_cameras()
    return [
        {
            "id": c.get("id"),
            "name": c.get("name"),
            # Map YAML `url` → frontend `rtsp_url`; derive active from explicit field or URL presence
            "rtsp_url": c.get("url") or "",
            "active": c.get("active", bool(c.get("url"))),
            "roi": c.get("roi"),
        }
        for c in cameras
    ]


class ROIUpdate(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class CameraPayload(BaseModel):
    id: str
    name: str
    rtsp_url: str = ""
    active: bool = True
    roi: Optional[ROIUpdate] = None


def _write_cameras_yaml(cameras: List[Dict]) -> None:
    with open(CAMERAS_CONFIG, "w") as f:
        yaml.safe_dump({"cameras": cameras}, f, default_flow_style=None, sort_keys=False)


def _save_camera_roi(camera_id: str, roi: list) -> bool:
    with open(CAMERAS_CONFIG) as f:
        data = yaml.safe_load(f) or {}
    for cam in data.get("cameras", []):
        if cam["id"] == camera_id:
            cam["roi"] = roi
            break
    else:
        return False
    _write_cameras_yaml(data.get("cameras", []))
    return True


@app.put("/cameras")
def replace_cameras(cameras: List[CameraPayload]):
    """Bulk-replace all cameras in cameras.yaml. Maps frontend fields to YAML format."""
    cam_list: List[Dict] = []
    for cam in cameras:
        cam_list.append({
            "id": cam.id,
            "name": cam.name,
            "url": cam.rtsp_url or None,   # frontend rtsp_url → YAML url
            "active": cam.active,
            "roi": [cam.roi.x1, cam.roi.y1, cam.roi.x2, cam.roi.y2] if cam.roi else None,
        })
    try:
        _write_cameras_yaml(cam_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save cameras.yaml: {e}")
    log.info("cameras.yaml replaced via API: %d camera(s)", len(cam_list))
    return {"saved": len(cam_list)}


@app.patch("/cameras/{camera_id}/roi")
def update_camera_roi(camera_id: str, body: ROIUpdate):
    roi = [body.x1, body.y1, body.x2, body.y2]
    try:
        found = _save_camera_roi(camera_id, roi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save ROI: {e}")
    if not found:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    log.info("[%s] ROI updated via API: %s", camera_id, roi)
    return {"camera_id": camera_id, "roi": roi}


@app.post("/cameras/{camera_id}/snapshot")
async def capture_snapshot(camera_id: str):
    cameras = _load_cameras()
    cam = next((c for c in cameras if c.get("id") == camera_id), None)

    if cam is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found in {CAMERAS_CONFIG}")

    rtsp_url = cam.get("url")
    if not rtsp_url:
        raise HTTPException(status_code=400, detail=f"Camera '{camera_id}' has no RTSP URL configured")

    loop = asyncio.get_running_loop()
    try:
        ret, frame = await asyncio.wait_for(
            loop.run_in_executor(_snapshot_executor, _capture_frame, rtsp_url),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Snapshot timed out — camera may be offline")

    if not ret or frame is None:
        raise HTTPException(status_code=503, detail="Could not read frame from camera stream")

    h, w = frame.shape[:2]
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    img_b64 = base64.b64encode(buf.tobytes()).decode()

    return {
        "image_base64": img_b64,
        "timestamp": datetime.utcnow().isoformat(),
        "width": w,
        "height": h,
    }


@app.get("/cameras/{camera_id}/stream-status")
def stream_status(camera_id: str):
    age = _fb.age(camera_id)
    if age is None:
        return {"active": False, "age_seconds": None, "reason": "no frames yet — pipeline may not be running"}
    active = age < _fb.STALE_SECS
    return {"active": active, "age_seconds": round(age, 2), "reason": "ok" if active else "frame too old"}


@app.get("/cameras/{camera_id}/stream")
async def stream_camera(camera_id: str):
    """MJPEG stream — serves annotated frames from the pipeline frame buffer."""
    cameras = _load_cameras()
    cam = next((c for c in cameras if c.get("id") == camera_id), None)
    if cam is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    if not cam.get("url"):
        raise HTTPException(status_code=503, detail=f"Camera '{camera_id}' has no RTSP URL configured")

    async def generate() -> AsyncGenerator[bytes, None]:
        last_jpeg: bytes = b""
        stale_since = time.monotonic()
        try:
            while True:
                jpeg = _fb.get(camera_id)
                if jpeg is None or jpeg is last_jpeg:
                    if time.monotonic() - stale_since > 15.0:
                        log.warning("MJPEG stream for %s: no new frames for 15s, closing", camera_id)
                        break
                    await asyncio.sleep(0.1)
                    continue
                stale_since = time.monotonic()
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
