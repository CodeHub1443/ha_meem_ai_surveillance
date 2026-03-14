import os
import cv2
from datetime import datetime

class SnapshotWriter:
    def __init__(self, base_dir: str, camera_id: str):
        self.base_dir = base_dir
        self.camera_id = camera_id

    def save(self, frame, identity: str = None) -> str:
        # 1. Create folder structure: base_dir/snapshots/YYYY-MM-DD/
        now = datetime.now()
        date_folder = now.strftime("%Y-%m-%d")
        
        target_dir = os.path.join(self.base_dir, "snapshots", date_folder)
        os.makedirs(target_dir, exist_ok=True)
        
        # 2. Generate filename: HH-MM-SS_cameraid_identity.jpg
        active_identity = identity if identity else "unknown"
        time_prefix = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{time_prefix}_{self.camera_id}_{active_identity}.jpg"
        
        # 3. Save the frame
        save_path = os.path.join(target_dir, filename)
        cv2.imwrite(save_path, frame)
        
        # 4. Return the snapshot path
        return save_path
