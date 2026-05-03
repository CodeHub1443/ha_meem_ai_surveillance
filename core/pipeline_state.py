import time
from typing import Dict, Optional


class PipelineState:
    """Encapsulates all mutable per-camera state for the inference loop.

    Centralising decided_tracks and cooldown into one object makes the main
    loop readable and the state fully testable in isolation.
    """

    def __init__(self, camera_id: str, cooldown_seconds: float = 6.0):
        self.camera_id = camera_id
        self.cooldown_seconds = cooldown_seconds
        # track_id → identity: str = AUTHORIZED (closed), None = UNKNOWN (upgradeable)
        self.decided_tracks: Dict[int, Optional[str]] = {}
        # Keys: identity string for known persons, "__unknown_<track_id>" for unknowns.
        self._last_seen: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_decided(self, track_id: int) -> bool:
        """True if this track has already produced an alert this session."""
        return track_id in self.decided_tracks

    def is_upgradeable(self, track_id: int) -> bool:
        """True if track was decided as UNKNOWN and can still be upgraded to AUTHORIZED."""
        return track_id in self.decided_tracks and self.decided_tracks[track_id] is None

    def can_alert(self, identity: Optional[str], track_id: int) -> bool:
        """True if an alert should be sent (cooldown not active)."""
        key = identity if identity is not None else f"__unknown_{track_id}"
        last = self._last_seen.get(key, 0.0)
        return (time.time() - last) >= self.cooldown_seconds

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def mark_decided(self, track_id: int, identity: Optional[str]):
        """Record that an alert was emitted for this track."""
        self.decided_tracks[track_id] = identity
        key = identity if identity is not None else f"__unknown_{track_id}"
        self._last_seen[key] = time.time()

    def upgrade_track(self, track_id: int, identity: str):
        """Upgrade a previously UNKNOWN track to AUTHORIZED."""
        self.decided_tracks[track_id] = identity
        self._last_seen[identity] = time.time()

    def release_track(self, track_id: int):
        """Remove a track when the tracker drops it (allows re-alerting if
        the same person re-enters)."""
        self.decided_tracks.pop(track_id, None)
