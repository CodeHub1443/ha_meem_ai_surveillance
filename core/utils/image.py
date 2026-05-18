import cv2
import numpy as np
from typing import Optional, Tuple

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


def pose_weight(kps: np.ndarray) -> float:
    """Weight in [0.1, 1.0] reflecting how frontal the face is.

    Uses the horizontal offset of the nose tip from the eye midpoint,
    normalised by the inter-eye distance.  A perfectly frontal face scores
    1.0; a ~60° profile scores ~0.1.  The face is never discarded — the
    weight just reduces the profile frame's contribution to the temporal
    consensus so sharper, frontal frames dominate.
    """
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_dist = abs(float(right_eye[0]) - float(left_eye[0]))
    if eye_dist < 1.0:
        return 0.5
    eye_center_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
    nose_offset = abs(float(nose[0]) - eye_center_x) / eye_dist
    # 0.0 offset (frontal) → 1.0 weight; 0.5+ offset (profile) → 0.1 weight
    return float(max(0.1, 1.0 - nose_offset * 1.8))


def align_face(
    image: np.ndarray,
    kps: np.ndarray,
    crop: Optional[np.ndarray] = None,
    image_size: int = 112,
) -> np.ndarray:
    """Affine-warp a face crop to the ArcFace canonical 112×112 pose.

    Uses SCRFD's 5-point landmarks (left eye, right eye, nose, left mouth,
    right mouth) to estimate a similarity transform and warp the face into the
    standard frontal position expected by AdaFace/ArcFace models.

    Falls back to resizing ``crop`` when the transform cannot be estimated
    (degenerate geometry — extreme profile, edge-of-frame landmarks).
    ``image`` is used as a last resort only when no crop is provided.
    """
    ref = _ARCFACE_REF_KEYPOINTS * (image_size / 112.0)
    M, _ = cv2.estimateAffinePartial2D(
        kps.astype(np.float32), ref, method=cv2.LMEDS
    )
    if M is None:
        fallback = crop if crop is not None else image
        return cv2.resize(fallback, (image_size, image_size))
    return cv2.warpAffine(
        image, M, (image_size, image_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
