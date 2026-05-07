import cv2
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class SnapshotWriter:
    def __init__(self, base_dir: str, camera_id: str):
        self.base_dir = base_dir
        self.camera_id = camera_id

    def save(self, frame, identity: Optional[str] = None, timestamp: datetime = None) -> Optional[str]:
        """Save a JPEG snapshot. Returns the path on success, None on failure."""
        now = timestamp if timestamp else datetime.now()
        date_folder = now.strftime("%Y-%m-%d")

        target_dir = Path(self.base_dir) / date_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        active_identity = identity if identity else "unknown"
        time_prefix = now.strftime("%Y%m%d_%H%M%S")
        filename = f"{time_prefix}_{self.camera_id}_{active_identity}.jpg"
        save_path = target_dir / filename

        try:
            ok = cv2.imwrite(str(save_path), frame)
            if not ok:
                log.error(
                    "[%s] cv2.imwrite returned False for %s — disk full or bad path?",
                    self.camera_id, save_path,
                )
                return None
        except Exception as exc:
            log.error("[%s] Snapshot write exception for %s: %s", self.camera_id, save_path, exc)
            return None

        return save_path.as_posix()
