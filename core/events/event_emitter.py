import json
import threading
from pathlib import Path


# Module-level lock so multiple camera threads can safely append to the same file.
_file_locks: dict = {}
_locks_mutex = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_mutex:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


class EventEmitter:
    """Emits structured recognition events to a shared JSONL log file.

    Thread-safe: multiple camera workers can append to the same file
    concurrently without interleaving partial JSON lines.
    """

    def __init__(self, camera_id: str, log_file: str):
        self.camera_id = camera_id
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _get_lock(str(self.log_file.resolve()))

    def emit(self, event_data: dict):
        """Append the event as a JSON line; safe for concurrent callers."""
        line = json.dumps(event_data) + "\n"
        with self._lock:
            with open(self.log_file, "a", buffering=1) as f:
                f.write(line)

