from abc import ABC, abstractmethod
import numpy as np
from typing import List, Optional
from ..detection.face import Face

class BaseRecognizer(ABC):
    """Abstract base class for face recognition models."""
    
    def __init__(self, config: dict):
        self.config = config
        self.device = config.get("pipeline", {}).get("device", "cuda")

    @abstractmethod
    def extract_embedding(self, face_img: np.ndarray) -> np.ndarray:
        """Extracts a 512-d embedding from a face image.
        
        Args:
            face_img: Aligned/Cropped face image.
            
        Returns:
            normalized 512-d embedding.
        """
        pass
