import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_MB = 1024 * 1024

# Module-level per-file locks — setdefault is atomic so no secondary mutex needed.
_file_locks: dict = {}
_locks_mutex = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_mutex:
        return _file_locks.setdefault(path, threading.Lock())


class EventEmitter:
    """Emits structured recognition events to a shared JSONL log file.

    Thread-safe: multiple camera workers can append to the same file
    concurrently without interleaving partial JSON lines.

    Rotation: when the file exceeds ``max_bytes`` it is renamed to
    ``<name>.1.jsonl``, older backups shift up, and the oldest is deleted.
    This keeps total disk use bounded to roughly ``(backup_count+1) * max_bytes``.

    On write failure (disk full, permission error) the event is appended to a
    dead-letter file so no alert is silently lost.
    """

    def __init__(
        self,
        camera_id: str,
        log_file: str,
        max_bytes: int = 50 * _MB,
        backup_count: int = 5,
    ):
        self.camera_id = camera_id
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._dead_letter = self.log_file.with_name(self.log_file.stem + ".dead.jsonl")
        self._lock = _get_lock(str(self.log_file.resolve()))

    # ------------------------------------------------------------------

    def _rotate(self):
        """Rotate log files. Must be called with self._lock held."""
        if self.max_bytes <= 0 or not self.log_file.exists():
            return
        try:
            if self.log_file.stat().st_size <= self.max_bytes:
                return
        except OSError:
            return

        stem = self.log_file.stem
        suffix = self.log_file.suffix
        parent = self.log_file.parent

        # Shift existing backups: .4 → .5, .3 → .4, ..., .1 → .2
        for i in range(self.backup_count - 1, 0, -1):
            src = parent / f"{stem}.{i}{suffix}"
            dst = parent / f"{stem}.{i + 1}{suffix}"
            if src.exists():
                try:
                    src.rename(dst)
                except OSError as exc:
                    log.warning("Log rotation rename %s → %s failed: %s", src, dst, exc)

        # Current file → .1
        try:
            self.log_file.rename(parent / f"{stem}.1{suffix}")
        except OSError as exc:
            log.warning("Log rotation failed for %s: %s", self.log_file, exc)

    # ------------------------------------------------------------------

    def emit(self, event_data: dict):
        """Append the event as a JSON line; safe for concurrent callers."""
        line = json.dumps(event_data) + "\n"
        with self._lock:
            self._rotate()
            try:
                with open(self.log_file, "a", buffering=1) as f:
                    f.write(line)
            except OSError as exc:
                log.error(
                    "[%s] Failed to write event to %s: %s — writing to dead-letter %s",
                    self.camera_id, self.log_file, exc, self._dead_letter,
                )
                try:
                    with open(self._dead_letter, "a", buffering=1) as f:
                        f.write(line)
                except OSError:
                    log.critical(
                        "[%s] Dead-letter write also failed. Lost event: %s",
                        self.camera_id, line.rstrip(),
                    )
