from dataclasses import dataclass
import numpy as np
from typing import Optional, List

@dataclass
class Face:
    """Dataclass to represent a detected face."""
    bbox: np.ndarray  # [x1, y1, x2, y2, confidence]
    kps: Optional[np.ndarray] = None  # [5, 2] landmarks
    embedding: Optional[np.ndarray] = None  # 512-d normalized embedding
    track_id: Optional[int] = None
    quality_score: float = 0.0
    blur_score: float = 0.0
    timestamp: float = 0.0

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def confidence(self) -> float:
        return self.bbox[4]
