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
    appends the event JSON.  If the queue is full (burst of alerts) the
    submission is silently dropped to keep the main loop running.

    If snapshot writing fails, the event is still emitted with
    ``snapshot: null`` so the alert is never silently lost.
    """

    def __init__(self, event_emitter, snapshot_writer, queue_size: int = 64):
        self._event_emitter = event_emitter
        self._snapshot_writer = snapshot_writer
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(target=self._worker, daemon=True, name="io-worker")
        self._thread.start()

    def submit(
        self,
        frame: np.ndarray,
        event_data: dict,
        identity: Optional[str],
        timestamp: datetime,
    ):
        """Non-blocking enqueue. Drops silently when the queue is full."""
        if frame is None:
            log.warning("AsyncIOWorker.submit called with None frame — skipped")
            return
        try:
            self._queue.put_nowait((frame.copy(), event_data.copy(), identity, timestamp))
        except queue.Full:
            log.warning("AsyncIOWorker queue full — event dropped")

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            frame, event_data, identity, timestamp = item
            try:
                snapshot_path = self._snapshot_writer.save(
                    frame, identity, timestamp=timestamp
                )
                # snapshot_path is None if the write failed — emit event anyway
                event_data["snapshot"] = snapshot_path
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
