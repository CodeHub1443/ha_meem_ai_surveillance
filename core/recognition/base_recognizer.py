from abc import ABC, abstractmethod
import numpy as np
from typing import List


class BaseRecognizer(ABC):
    """Abstract base class for face recognition models."""

    def __init__(self, config: dict):
        self.config = config
        self.device = config.get("pipeline", {}).get("device", "cuda")

    @abstractmethod
    def extract_embedding(self, face_img: np.ndarray) -> np.ndarray:
        """Extract a normalised 512-d embedding from a single face crop."""
        pass

    @abstractmethod
    def extract_embeddings_batch(self, face_imgs: List[np.ndarray]) -> np.ndarray:
        """Extract normalised 512-d embeddings for a batch of face crops.

        Returns:
            np.ndarray of shape (N, 512), L2-normalised rows.
        """
        pass
