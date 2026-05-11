"""
In-process frame buffer shared between the pipeline threads and the API server.

The pipeline's CameraWorker calls `put()` after every processed frame.
The API server's MJPEG generator calls `get()` to serve the browser.

Because both run in the same process (started via run.py), this plain
dict+lock is all the IPC we need — no files, no sockets, no race conditions.
"""
import threading
import time
from typing import Dict, Optional

_lock = threading.Lock()

# {camera_id: (jpeg_bytes, write_timestamp)}
_store: Dict[str, tuple] = {}

STALE_SECS = 10.0   # frames older than this are considered pipeline-offline


def put(camera_id: str, jpeg: bytes) -> None:
    with _lock:
        _store[camera_id] = (jpeg, time.monotonic())


def get(camera_id: str) -> Optional[bytes]:
    with _lock:
        entry = _store.get(camera_id)
    if entry is None:
        return None
    jpeg, ts = entry
    if time.monotonic() - ts > STALE_SECS:
        return None
    return jpeg


def age(camera_id: str) -> Optional[float]:
    with _lock:
        entry = _store.get(camera_id)
    if entry is None:
        return None
    _, ts = entry
    return time.monotonic() - ts
