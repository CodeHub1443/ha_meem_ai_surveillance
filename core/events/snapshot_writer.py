import os
import cv2
from datetime import datetime
from pathlib import Path

class SnapshotWriter:
    def __init__(self, base_dir: str, camera_id: str):
        self.base_dir = base_dir
        self.camera_id = camera_id

    def save(self, frame, identity: str = None, timestamp: datetime = None) -> str:
        # 1. Create folder structure: base_dir/YYYY-MM-DD/
        now = timestamp if timestamp else datetime.now()
        date_folder = now.strftime("%Y-%m-%d")
        
        target_dir = Path(self.base_dir) / date_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. Generate filename: YYYYMMDD_HHMMSS_cameraid_identity.jpg
        active_identity = identity if identity else "unknown"
        time_prefix = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{time_prefix}_{self.camera_id}_{active_identity}.jpg"
        
        # 3. Save the frame
        save_path = target_dir / filename
        cv2.imwrite(str(save_path), frame)
        
        # 4. Return the snapshot path using forward slashes
        return save_path.as_posix()

