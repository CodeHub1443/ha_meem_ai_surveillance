import logging
import queue
import threading
from datetime import datetime
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Module-level counter so the API server can expose it without holding a reference
# to a specific AsyncIOWorker instance.
_dropped_lock = threading.Lock()
_dropped_events: int = 0


def get_dropped_count() -> int:
    """Return the total number of events dropped due to a full I/O queue."""
    with _dropped_lock:
        return _dropped_events


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
            global _dropped_events
            with _dropped_lock:
                _dropped_events += 1
            log.warning("AsyncIOWorker queue full — event dropped (total dropped: %d)", _dropped_events)

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
                        if embedding is not None and event_data.get("event") == "UNKNOWN":
                            # Atomic write: event row + embedding blob in one transaction.
                            # A crash between two separate commits would leave an orphaned
                            # event row with no embedding; the combined method prevents that.
                            self._event_store.insert_with_embedding(event_data, embedding)
                        else:
                            self._event_store.insert(event_data)
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
