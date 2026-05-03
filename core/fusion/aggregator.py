import time
import numpy as np
from typing import Dict, List, Optional, Tuple

from ..detection.face import Face


class EmbeddingAggregator:
    """Temporal consensus aggregator for face embeddings.

    Improvements over v1:
    - Recency weighting: recent, sharp frames dominate the consensus.
    - Time-based decision gate: requires ``min_decision_seconds`` of
      continuous observation before making a match, making behaviour
      consistent across different hardware FPS.
    - Self-expiring buffers: tracks not updated within
      ``expire_after_seconds`` are pruned automatically, eliminating the
      manual cleanup in the main loop and preventing memory leaks.
    """

    def __init__(
        self,
        buffer_size: int = 10,
        min_frames: int = 2,
        min_decision_seconds: float = 0.5,
        recency_decay: float = 0.95,
        expire_after_seconds: float = 3.0,
    ):
        """
        Args:
            buffer_size: Maximum frames kept per track (sliding window).
            min_frames: Minimum frame count required regardless of time.
            min_decision_seconds: Minimum wall-clock seconds since first
                observation before the consensus is returned.
            recency_decay: Per-frame exponential decay applied to quality
                weights so the most recent frame has the highest weight.
                Set to 1.0 to disable recency weighting.
            expire_after_seconds: Remove a track buffer if it has not
                received an update in this many seconds.
        """
        self.buffer_size = buffer_size
        self.min_frames = min_frames
        self.min_decision_seconds = min_decision_seconds
        self.recency_decay = recency_decay
        self.expire_after_seconds = expire_after_seconds

        # track_id → {entries, first_seen, last_updated}
        # entries: list of (embedding, blur_score, timestamp)
        self.track_buffers: Dict[int, Dict] = {}

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def add_face(self, face: Face):
        """Add an embedding+quality observation for a tracked face."""
        if face.track_id is None or face.embedding is None:
            return

        now = time.time()
        tid = face.track_id

        if tid not in self.track_buffers:
            self.track_buffers[tid] = {
                "entries": [],
                "first_seen": now,
                "last_updated": now,
            }

        buf = self.track_buffers[tid]
        buf["entries"].append((face.embedding, face.quality_score, now))
        buf["last_updated"] = now

        if len(buf["entries"]) > self.buffer_size:
            buf["entries"].pop(0)

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_aggregated_embedding(self, track_id: int) -> Optional[np.ndarray]:
        """Return quality- and recency-weighted consensus embedding.

        Returns None if the track has insufficient data or has not been
        observed long enough.
        """
        if track_id not in self.track_buffers:
            return None

        buf = self.track_buffers[track_id]
        entries: List[Tuple[np.ndarray, float, float]] = buf["entries"]

        # --- Decision gate ---
        elapsed = time.time() - buf["first_seen"]
        if elapsed < self.min_decision_seconds:
            return None
        if len(entries) < max(self.min_frames, 2):
            return None

        # --- Build combined weights (quality × recency) ---
        n = len(entries)
        embeddings = np.stack([e[0] for e in entries])          # (N, 512)
        quality_scores = np.array([e[1] for e in entries], dtype=np.float64)

        # Recency weights: oldest frame = decay^(n-1), newest = 1.0
        recency_weights = np.array(
            [self.recency_decay ** (n - 1 - i) for i in range(n)],
            dtype=np.float64,
        )

        combined = quality_scores * recency_weights
        total = combined.sum()
        weights = combined / total if total > 0 else np.ones(n) / n

        # --- Weighted mean + L2 normalise ---
        agg = np.sum(embeddings * weights[:, np.newaxis], axis=0)
        norm = np.linalg.norm(agg)
        return agg / norm if norm > 0 else agg

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def expire_stale_tracks(self) -> List[int]:
        """Remove tracks not updated within ``expire_after_seconds``.

        Returns the list of expired track IDs so the caller can clean up
        downstream state (e.g. ``PipelineState.decided_tracks``).
        """
        now = time.time()
        stale = [
            tid
            for tid, buf in self.track_buffers.items()
            if now - buf["last_updated"] > self.expire_after_seconds
        ]
        for tid in stale:
            del self.track_buffers[tid]
        return stale

    def clear_track(self, track_id: int):
        """Explicitly remove a single track's buffer."""
        self.track_buffers.pop(track_id, None)
