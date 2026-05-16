import time
import threading
from typing import Dict, List, Optional, Tuple


class PipelineState:
    """Encapsulates all mutable per-camera state for the inference loop.

    Centralising decided_tracks, cooldown, and held-unknown state into one
    object makes the main loop readable and the state fully testable.

    Thread-safe: all public methods acquire an internal lock.

    Deferred UNKNOWN emission
    ─────────────────────────
    When the aggregator first decides a track is UNKNOWN, we do NOT emit
    immediately.  Instead we park the frame + event_data in _held_unknowns
    and keep the track upgradeable.

    The held UNKNOWN is eventually emitted in one of three ways:
      1. The track expires (person left frame) → released in release_track().
      2. The hold period elapses while the person is still in frame →
         popped by pop_overdue_unknowns() each pipeline tick.
      3. The track is upgraded to AUTHORIZED → discard_held_unknown() drops
         it silently, so only the AUTHORIZED event is written.

    This eliminates the false UNKNOWN → AUTHORIZED double-event caused by
    poor viewing angles on entry.
    """

    def __init__(self, camera_id: str, cooldown_seconds: float = 6.0):
        self.camera_id = camera_id
        self.cooldown_seconds = cooldown_seconds
        # track_id → identity: str = AUTHORIZED (closed), None = UNKNOWN (upgradeable)
        self.decided_tracks: Dict[int, Optional[str]] = {}
        # Keys: identity string for known persons, "__unknown_<track_id>" for unknowns.
        self._last_seen: Dict[str, float] = {}
        # Deferred UNKNOWN state: track_id → {frame, event_data, embedding, held_since}
        self._held_unknowns: Dict[int, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_decided(self, track_id: int) -> bool:
        """True if this track has already produced an alert this session."""
        with self._lock:
            return track_id in self.decided_tracks

    def is_upgradeable(self, track_id: int) -> bool:
        """True if track was decided as UNKNOWN and can still be upgraded."""
        with self._lock:
            return track_id in self.decided_tracks and self.decided_tracks[track_id] is None

    def can_alert(self, identity: Optional[str], track_id: int) -> bool:
        """True if an alert should be sent (cooldown not active)."""
        key = identity if identity is not None else f"__unknown_{track_id}"
        with self._lock:
            last = self._last_seen.get(key, 0.0)
        return (time.time() - last) >= self.cooldown_seconds

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def mark_decided(self, track_id: int, identity: Optional[str]):
        """Record that a decision was made for this track."""
        key = identity if identity is not None else f"__unknown_{track_id}"
        with self._lock:
            self.decided_tracks[track_id] = identity
            self._last_seen[key] = time.time()

    def upgrade_track(self, track_id: int, identity: str):
        """Upgrade a previously UNKNOWN track to AUTHORIZED."""
        with self._lock:
            self.decided_tracks[track_id] = identity
            self._last_seen[identity] = time.time()

    def release_track(self, track_id: int) -> Optional[dict]:
        """Remove a track when the tracker drops it.

        Returns the held UNKNOWN payload (frame, event_data, embedding) if
        this track was deferred, so the caller can emit it now. Returns None
        if there was no pending UNKNOWN.
        """
        with self._lock:
            self.decided_tracks.pop(track_id, None)
            return self._held_unknowns.pop(track_id, None)

    # ------------------------------------------------------------------
    # Deferred UNKNOWN helpers
    # ------------------------------------------------------------------

    def hold_unknown(
        self,
        track_id: int,
        annotated_frame,        # np.ndarray — snapshot of the decision frame
        event_data: dict,
        embedding,              # np.ndarray | None — aggregated face embedding
    ):
        """Park a deferred UNKNOWN emission instead of firing immediately."""
        with self._lock:
            self._held_unknowns[track_id] = {
                "frame": annotated_frame,
                "event_data": event_data.copy(),
                "embedding": embedding.copy() if embedding is not None else None,
                "held_since": time.time(),
            }

    def discard_held_unknown(self, track_id: int):
        """Silently drop a held UNKNOWN (called when track upgrades to AUTHORIZED)."""
        with self._lock:
            self._held_unknowns.pop(track_id, None)

    def pop_overdue_unknowns(self, hold_seconds: float) -> List[Tuple[int, dict]]:
        """Return and remove held unknowns that have exceeded the hold period.

        Called each pipeline tick to flush genuine unknowns who remain in
        frame longer than hold_seconds without being recognised.
        """
        now = time.time()
        overdue: List[Tuple[int, dict]] = []
        with self._lock:
            for tid in list(self._held_unknowns):
                if now - self._held_unknowns[tid]["held_since"] >= hold_seconds:
                    overdue.append((tid, self._held_unknowns.pop(tid)))
        return overdue
