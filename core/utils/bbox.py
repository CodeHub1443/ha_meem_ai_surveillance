import numpy as np
from typing import Tuple


def calculate_iou(bbox1: np.ndarray, bbox2: np.ndarray) -> float:
    """IoU between two bounding boxes [x1, y1, x2, y2, ...]."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    return float(inter / (area1 + area2 - inter + 1e-6))


def iou_matrix(bboxes_a: np.ndarray, bboxes_b: np.ndarray) -> np.ndarray:
    """Compute IoU matrix between two sets of boxes. Returns shape (N, M).

    Fully vectorised with NumPy broadcasting — no Python loops.
    
    This implementation calculates the overlap between every box in set A and
    every box in set B simultaneously, significantly improving performance
    for high-density frames.
    """
    if len(bboxes_a) == 0 or len(bboxes_b) == 0:
        return np.zeros((len(bboxes_a), len(bboxes_b)), dtype=np.float32)

    a = np.asarray(bboxes_a, dtype=np.float32)  # (N, 4+)
    b = np.asarray(bboxes_b, dtype=np.float32)  # (M, 4+)

    # Intersection coordinates
    inter_x1 = np.maximum(a[:, 0:1], b[:, 0])  # (N, M)
    inter_y1 = np.maximum(a[:, 1:2], b[:, 1])
    inter_x2 = np.minimum(a[:, 2:3], b[:, 2])
    inter_y2 = np.minimum(a[:, 3:4], b[:, 3])
    
    # Intersection dimensions (clamp to 0 for non-overlapping boxes)
    inter_w = np.maximum(0.0, inter_x2 - inter_x1)
    inter_h = np.maximum(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h  # (N, M)

    # Union = AreaA + AreaB - Intersection
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])  # (N,)
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])  # (M,)
    union_area = area_a[:, np.newaxis] + area_b[np.newaxis, :] - inter_area

    # Avoid division by zero with small epsilon
    return (inter_area / (union_area + 1e-6)).astype(np.float32)


def clip_bbox(bbox: np.ndarray, image_shape: Tuple[int, int]) -> np.ndarray:
    """Clip [x1, y1, x2, y2, ...] to image boundaries."""
    h, w = image_shape[:2]
    clipped = bbox.copy()
    clipped[0] = max(0.0, min(float(w), bbox[0]))
    clipped[1] = max(0.0, min(float(h), bbox[1]))
    clipped[2] = max(0.0, min(float(w), bbox[2]))
    clipped[3] = max(0.0, min(float(h), bbox[3]))
    return clipped


def bbox_to_xywh(bbox: np.ndarray) -> np.ndarray:
    """Convert [x1, y1, x2, y2] → [cx, cy, area, aspect_ratio]."""
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    cx = bbox[0] + w / 2.0
    cy = bbox[1] + h / 2.0
    area = w * h
    ratio = w / float(h + 1e-6)
    return np.array([cx, cy, area, ratio], dtype=np.float64)


def xywh_to_bbox(state: np.ndarray) -> np.ndarray:
    """Convert [cx, cy, area, aspect_ratio] → [x1, y1, x2, y2]."""
    cx, cy, area, ratio = float(state[0]), float(state[1]), float(state[2]), float(state[3])
    area = max(area, 1.0)
    ratio = max(ratio, 1e-3)
    w = np.sqrt(area * ratio)
    h = area / (w + 1e-6)
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dtype=np.float64)
