from dataclasses import dataclass
from typing import Optional

@dataclass
class RecognitionEvent:
    """Dataclass representing a face recognition event at an entry zone."""
    timestamp: float
    camera_id: str
    track_id: int
    identity: Optional[str]
    confidence: float
    face_width: int
    blur_score: float
