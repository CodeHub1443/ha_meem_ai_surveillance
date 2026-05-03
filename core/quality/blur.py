import cv2
import numpy as np
from collections import deque


def calculate_blur_score(image: np.ndarray) -> float:
    """Focus measure via Variance of Laplacian (higher = sharper)."""
    if image is None or image.size == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class AdaptiveBlurThreshold:
    """Rolling-percentile blur threshold that adapts to each camera's quality.

    Maintains a sliding window of non-trivial blur scores and sets the
    threshold at a configurable percentile (default 20th).  This means:
    - Poor-quality / low-light streams → lower threshold, fewer rejections.
    - High-quality streams → higher threshold, stricter filtering.

    Falls back to ``fallback`` until enough samples are collected.
    """

    def __init__(
        self,
        window_size: int = 500,
        percentile: float = 20.0,
        fallback: float = 100.0,
        min_samples: int = 10,
    ):
        self.percentile = percentile
        self.fallback = fallback
        self.min_samples = min_samples
        self._scores: deque = deque(maxlen=window_size)

    def update(self, score: float):
        """Feed a new blur score into the rolling window."""
        if score > 0:
            self._scores.append(score)

    def threshold(self) -> float:
        """Current adaptive threshold; returns fallback if too few samples.

        The adaptive value is capped at ``fallback`` so it can only relax
        the threshold for poor-quality streams — never tighten it above the
        configured baseline for high-quality streams.
        """
        if len(self._scores) < self.min_samples:
            return self.fallback
        adaptive = float(np.percentile(list(self._scores), self.percentile))
        return min(adaptive, self.fallback)
