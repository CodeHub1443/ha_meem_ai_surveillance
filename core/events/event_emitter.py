import json
import os
from datetime import datetime
from pathlib import Path

class EventEmitter:
    """Emits structured recognition events to a log file."""
    
    def __init__(self, camera_id: str, log_file: str):
        self.camera_id = camera_id
        self.log_file = Path(log_file)
        
        # Ensure log directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
    def _emit(self, track_id: int, identity: str, score: float, event_type: str, snapshot: str = None):
        """Helper to construct and append the event JSON."""
        event = {
            "timestamp": datetime.now().isoformat(), # Local time (ISO8601)
            "camera_id": self.camera_id,
            "track_id": track_id,
            "identity": identity,
            "score": float(score), # Ensure score is JSON serializable
            "event": event_type,
            "snapshot": snapshot
        }
        
        # Append as JSON line
        with open(self.log_file, 'a', buffering=1) as f:
            f.write(json.dumps(event) + "\n")

    def emit_authorized(self, track_id: int, identity: str, score: float, snapshot: str = None):
        """Emits an AUTHORIZED event."""
        self._emit(track_id, identity, score, "AUTHORIZED", snapshot)

    def emit_unknown(self, track_id: int, score: float, snapshot: str = None):
        """Emits an UNKNOWN event."""
        self._emit(track_id, None, score, "UNKNOWN", snapshot)
