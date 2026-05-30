"""
Per-camera pipeline health metrics — thread-safe, zero external dependencies.

Phase 0 baseline: counters only, no pipeline behaviour is changed.
Exposes data for the /stats/pipeline API endpoint and daily log summaries.

Tracked metrics
───────────────
alignment_fallbacks   — frames where estimateAffinePartial2D failed and the
                        pipeline fell back to a raw crop resize. These frames
                        produce garbage embeddings. Phase 2 will skip them;
                        Phase 0 only counts them.

track_flips           — same track_id emitted AUTHORIZED then later UNKNOWN.
                        Direct symptom of RC3 (state clobbered by aggregator
                        expiry). Phase 1 will eliminate these.

decided_clobbers      — times release_track() was called on an already-decided
                        track due to aggregator expiry (not OC-SORT drop).
                        This is RC3 firing — one clobber can produce one flip.

events_per_track      — how many events each track_id emits in total.
                        Healthy: median ~1, max ~2.
                        Broken (RC3): max can exceed 10.
"""

import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List


class PipelineMetrics:
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._lock = threading.Lock()
        self._reset_time = datetime.now(timezone.utc)

        self._alignment_fallbacks: int = 0
        self._track_flips: int = 0
        self._decided_clobbers: int = 0
        self._per_track_events: Counter = Counter()

    # ── Write path ────────────────────────────────────────────────────────

    def record_alignment_fallback(self) -> None:
        with self._lock:
            self._alignment_fallbacks += 1

    def record_track_flip(self) -> None:
        with self._lock:
            self._track_flips += 1

    def record_decided_clobber(self) -> None:
        with self._lock:
            self._decided_clobbers += 1

    def record_event(self, track_id: int) -> None:
        with self._lock:
            self._per_track_events[track_id] += 1

    # ── Read path ─────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a serialisable summary — safe to call from any thread."""
        with self._lock:
            counts: List[int] = list(self._per_track_events.values())
            total = sum(counts)
            unique = len(counts)
            if counts:
                sorted_c = sorted(counts)
                p95_idx = max(0, int(0.95 * unique) - 1)
                p95 = sorted_c[p95_idx]
                mean = round(total / unique, 2)
                maximum = sorted_c[-1]
            else:
                p95 = mean = maximum = 0

            return {
                "camera_id": self.camera_id,
                "since": self._reset_time.isoformat(),
                "alignment_fallbacks": self._alignment_fallbacks,
                "track_flips": self._track_flips,
                "decided_clobbers": self._decided_clobbers,
                "total_events": total,
                "unique_tracks": unique,
                "events_per_track": {
                    "max": maximum,
                    "p95": p95,
                    "mean": mean,
                },
            }

    def log_summary(self, logger) -> None:
        """Write a one-line daily summary to the supplied logger."""
        s = self.snapshot()
        logger.info(
            "[%s] daily metrics | alignment_fallbacks=%d track_flips=%d "
            "decided_clobbers=%d events/track(max=%d p95=%d mean=%s) "
            "total_events=%d unique_tracks=%d | since=%s",
            self.camera_id,
            s["alignment_fallbacks"],
            s["track_flips"],
            s["decided_clobbers"],
            s["events_per_track"]["max"],
            s["events_per_track"]["p95"],
            s["events_per_track"]["mean"],
            s["total_events"],
            s["unique_tracks"],
            s["since"],
        )


# ── Module-level registry ──────────────────────────────────────────────────────
# Mirrors the pattern used by core/frame_buffer.py so the API server can read
# metrics without holding a reference to any specific CameraWorker instance.

_registry: Dict[str, PipelineMetrics] = {}
_registry_lock = threading.Lock()


def get_or_create(camera_id: str) -> PipelineMetrics:
    with _registry_lock:
        if camera_id not in _registry:
            _registry[camera_id] = PipelineMetrics(camera_id)
        return _registry[camera_id]


def all_snapshots() -> List[dict]:
    """Return snapshots for every registered camera — used by the API."""
    with _registry_lock:
        cameras = list(_registry.values())
    return [m.snapshot() for m in cameras]