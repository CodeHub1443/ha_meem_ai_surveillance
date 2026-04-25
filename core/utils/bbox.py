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
    """Compute IoU matrix between two sets of boxes. Returns shape (N, M)."""
    n, m = len(bboxes_a), len(bboxes_b)
    matrix = np.zeros((n, m), dtype=np.float32)
    for i in range(n):
        for j in range(m):
            matrix[i, j] = calculate_iou(bboxes_a[i], bboxes_b[j])
    return matrix


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
