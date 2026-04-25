import asyncio
import json
import os
import threading
from collections import deque
from typing import AsyncGenerator, List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Ha-Meem AI Surveillance API")

LOG_FILE = "logs/events.jsonl"
_CACHE_MAXLEN = 1000  # in-memory ring buffer size

# ── In-memory event cache ──────────────────────────────────────────────────────

_event_cache: deque = deque(maxlen=_CACHE_MAXLEN)
_cache_lock = threading.Lock()
# Subscribers waiting for SSE pushes: list of asyncio.Queue
_sse_subscribers: List[asyncio.Queue] = []
_sse_lock = threading.Lock()


def _load_existing_events():
    """Pre-populate the cache from the JSONL file at startup."""
    if not os.path.exists(LOG_FILE):
        return
    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    _event_cache.append(json.loads(line))
    except Exception as e:
        print(f"[api] Failed to pre-load events: {e}")


def _tail_log_file():
    """Background thread: tail the JSONL log and push new events to cache."""
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
                                with _cache_lock:
                                    _event_cache.append(event)
                                # Notify SSE subscribers
                                with _sse_lock:
                                    for q in _sse_subscribers:
                                        try:
                                            q.put_nowait(event)
                                        except asyncio.QueueFull:
                                            pass
                            except json.JSONDecodeError:
                                pass
                    last_size = size
                elif size < last_size:
                    # File was rotated/truncated
                    last_size = 0
        except Exception as e:
            print(f"[api] Log tail error: {e}")
        threading.Event().wait(timeout=1.0)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    _load_existing_events()
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _filtered_events(
    camera_id: Optional[str],
    identity: Optional[str],
    event_type: Optional[str],
    since: Optional[str],
) -> List[dict]:
    with _cache_lock:
        events = list(_event_cache)

    if camera_id:
        events = [e for e in events if e.get("camera_id") == camera_id]
    if identity:
        events = [e for e in events if e.get("identity") == identity]
    if event_type:
        events = [e for e in events if e.get("event") == event_type.upper()]
    if since:
        events = [e for e in events if e.get("timestamp", "") >= since]

    return events


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
    with _cache_lock:
        cached = len(_event_cache)
    return {"status": "ok", "cached_events": cached}


@app.get("/events/latest", response_model=List[SurveillanceEvent])
def get_latest_events(
    limit: int = Query(default=20, ge=1, le=500),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None, description="AUTHORIZED or UNKNOWN"),
):
    """Most recent N events, with optional filtering."""
    events = _filtered_events(camera_id, identity, event_type, None)
    return events[-limit:]


@app.get("/events", response_model=List[SurveillanceEvent])
def get_all_events(
    limit: int = Query(default=200, ge=1, le=_CACHE_MAXLEN),
    camera_id: Optional[str] = Query(default=None),
    identity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO timestamp lower bound"),
):
    """All cached events with optional filtering."""
    events = _filtered_events(camera_id, identity, event_type, since)
    return events[:limit]


@app.get("/events/stream")
async def stream_events():
    """Server-Sent Events stream — pushes new events in real time."""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    with _sse_lock:
        _sse_subscribers.append(q)

    async def generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"  # prevent proxy timeout
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
