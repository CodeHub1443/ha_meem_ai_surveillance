import logging
import queue
import threading
from datetime import datetime
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class AsyncIOWorker:
    """Handles snapshot saving and event logging in a background thread.

    The main inference loop calls ``submit()`` which is non-blocking.  A
    single daemon thread drains the queue, writes the JPEG to disk, then
    appends the event JSON and persists to SQLite.  If the queue is full
    (burst of alerts) the submission is silently dropped to keep the main
    loop running.

    If snapshot writing fails, the event is still emitted with
    ``snapshot: null`` so the alert is never silently lost.
    """

    def __init__(self, event_emitter, snapshot_writer, event_store=None, queue_size: int = 64):
        self._event_emitter = event_emitter
        self._snapshot_writer = snapshot_writer
        self._event_store = event_store
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(target=self._worker, daemon=True, name="io-worker")
        self._thread.start()

    def submit(
        self,
        frame: np.ndarray,
        event_data: dict,
        identity: Optional[str],
        timestamp: datetime,
        embedding: Optional[np.ndarray] = None,
    ):
        """Non-blocking enqueue. Drops silently when the queue is full."""
        if frame is None:
            log.warning("AsyncIOWorker.submit called with None frame — skipped")
            return
        emb_copy = embedding.copy() if embedding is not None else None
        try:
            self._queue.put_nowait((frame.copy(), event_data.copy(), identity, timestamp, emb_copy))
        except queue.Full:
            log.warning("AsyncIOWorker queue full — event dropped")

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            frame, event_data, identity, timestamp, embedding = item
            try:
                snapshot_path = self._snapshot_writer.save(
                    frame, identity, timestamp=timestamp
                )
                # snapshot_path is None if the write failed — emit event anyway
                event_data["snapshot"] = snapshot_path
                # SQLite first so the row is committed before JSONL triggers SSE.
                # If the frontend refetches immediately on SSE, the row is already there.
                if self._event_store is not None:
                    try:
                        self._event_store.insert(event_data)
                        if embedding is not None and event_data.get("event") == "UNKNOWN":
                            self._event_store.insert_unknown_embedding(
                                track_id=event_data["track_id"],
                                camera_id=event_data["camera_id"],
                                timestamp=event_data["timestamp"],
                                embedding=embedding,
                                snapshot=snapshot_path,
                            )
                    except Exception as db_exc:
                        log.error("EventStore insert failed: %s", db_exc)
                self._event_emitter.emit(event_data)
            except Exception as e:
                log.error("AsyncIOWorker error: %s", e, exc_info=True)
            finally:
                self._queue.task_done()

    def stop(self, timeout: float = 5.0):
        """Gracefully drain the queue and stop the worker thread."""
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("AsyncIOWorker did not stop within %.1fs — events may be incomplete", timeout)
