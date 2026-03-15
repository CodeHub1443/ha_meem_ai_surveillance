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
        
    def emit(self, event_data: dict):
        """Append the event data as a JSON line to the log file."""
        with open(self.log_file, 'a', buffering=1) as f:
            f.write(json.dumps(event_data) + "\n")

