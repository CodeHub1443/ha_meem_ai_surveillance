import cv2
import numpy as np
from typing import Tuple

# ArcFace canonical 5-point reference (for 112×112 output)
_ARCFACE_REF_KEYPOINTS = np.array([
    [38.2946, 51.6963],  # left eye
    [73.5318, 51.5014],  # right eye
    [56.0252, 71.7366],  # nose tip
    [41.5493, 92.3655],  # left mouth corner
    [70.7299, 92.2041],  # right mouth corner
], dtype=np.float32)


def resize_image(image: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    """Resize image to (width, height)."""
    return cv2.resize(image, size)


def normalize_image(image: np.ndarray) -> np.ndarray:
    """Normalize pixel values [0, 255] → [-1, 1] (AdaFace/ArcFace convention)."""
    return (image.astype(np.float32) - 127.5) / 128.0


def align_face(image: np.ndarray, kps: np.ndarray, image_size: int = 112) -> np.ndarray:
    """Affine-warp a face crop to the ArcFace canonical 112×112 pose.

    Uses SCRFD's 5-point landmarks (left eye, right eye, nose, left mouth,
    right mouth) to estimate a similarity transform and warp the face into the
    standard frontal position expected by AdaFace/ArcFace models.

    Falls back to a plain resize when landmarks are unavailable or the transform
    cannot be estimated (degenerate geometry).
    """
    ref = _ARCFACE_REF_KEYPOINTS * (image_size / 112.0)
    M, _ = cv2.estimateAffinePartial2D(
        kps.astype(np.float32), ref, method=cv2.LMEDS
    )
    if M is None:
        return cv2.resize(image, (image_size, image_size))
    return cv2.warpAffine(
        image, M, (image_size, image_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
