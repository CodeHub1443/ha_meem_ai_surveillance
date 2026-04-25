import numpy as np
from typing import List, Tuple, Optional
from scipy.optimize import linear_sum_assignment

from ..detection.face import Face
from ..utils.bbox import iou_matrix, bbox_to_xywh, xywh_to_bbox


class KalmanBoxTracker:
    """Kalman filter for a single bounding box.

    State vector:  [cx, cy, area, ratio, dcx, dcy, darea]  (7-dim)
    Measurement:   [cx, cy, area, ratio]                    (4-dim)
    Aspect ratio is treated as approximately constant (no velocity term).
    """

    def __init__(self, bbox: np.ndarray, track_id: int):
        # Constant-velocity transition matrix
        self.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
        ], dtype=np.float64)

        # Measurement matrix (observe position components only)
        self.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
        ], dtype=np.float64)

        # Process noise — low velocity noise relative to position noise
        self.Q = np.eye(7, dtype=np.float64)
        self.Q[4:, 4:] *= 0.01

        # Measurement noise — higher uncertainty on scale than on center
        self.R = np.eye(4, dtype=np.float64)
        self.R[2:, 2:] *= 10.0

        # Initial covariance — high uncertainty on velocity
        self.P = np.eye(7, dtype=np.float64)
        self.P[4:, 4:] *= 1000.0
        self.P *= 10.0

        # Initial state from first measurement
        z = bbox_to_xywh(bbox)
        self.x = np.zeros((7, 1), dtype=np.float64)
        self.x[:4, 0] = z

        self.track_id = track_id
        self.age = 0
        self.hits = 0
        self.time_since_update = 0
        self.last_face: Optional[Face] = None

    def predict(self) -> np.ndarray:
        """Advance state one step; returns predicted [x1, y1, x2, y2]."""
        # Clamp area velocity to prevent negative area
        if self.x[6, 0] + self.x[2, 0] <= 0:
            self.x[6, 0] = 0.0
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        self.time_since_update += 1
        return xywh_to_bbox(self.x[:4, 0])

    def update(self, bbox: np.ndarray, face: Face):
        """Update filter with a new matched detection."""
        self.time_since_update = 0
        self.hits += 1
        z = bbox_to_xywh(bbox).reshape(4, 1)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - self.H @ self.x)
        self.P = (np.eye(7) - K @ self.H) @ self.P
        self.last_face = face


class SORTTracker:
    """SORT: Simple Online and Realtime Tracking.

    Replaces IoU greedy matching with Kalman filter state prediction +
    Hungarian optimal assignment, giving stable tracks under occlusion
    and fast motion.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_age: int = 5,
        min_hits: int = 1,
    ):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        self.trackers: List[KalmanBoxTracker] = []
        self._next_id: int = 0

    def _new_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    def _hungarian_match(
        self,
        predicted: np.ndarray,
        detected: np.ndarray,
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        """Optimal assignment via Hungarian algorithm on IoU cost matrix."""
        if len(predicted) == 0:
            return [], [], list(range(len(detected)))
        if len(detected) == 0:
            return [], list(range(len(predicted))), []

        iou_mat = iou_matrix(predicted, detected)
        row_ind, col_ind = linear_sum_assignment(1.0 - iou_mat)

        matches: List[Tuple[int, int]] = []
        matched_pred: set = set()
        matched_det: set = set()

        for r, c in zip(row_ind, col_ind):
            if iou_mat[r, c] >= self.iou_threshold:
                matches.append((r, c))
                matched_pred.add(r)
                matched_det.add(c)

        unmatched_pred = [i for i in range(len(predicted)) if i not in matched_pred]
        unmatched_det = [j for j in range(len(detected)) if j not in matched_det]
        return matches, unmatched_pred, unmatched_det

    def update(self, detected_faces: List[Face]) -> List[Face]:
        """Update tracks with new detections; returns faces with track_id set."""
        # Step 1 — predict all existing trackers forward
        predicted_bboxes = (
            np.array([t.predict() for t in self.trackers])
            if self.trackers
            else np.empty((0, 4))
        )
        det_bboxes = (
            np.array([f.bbox[:4] for f in detected_faces])
            if detected_faces
            else np.empty((0, 4))
        )

        # Step 2 — optimal assignment
        matches, unmatched_preds, unmatched_dets = self._hungarian_match(
            predicted_bboxes, det_bboxes
        )

        # Step 3 — update matched trackers
        matched_pred_set = set()
        for pred_idx, det_idx in matches:
            face = detected_faces[det_idx]
            self.trackers[pred_idx].update(face.bbox[:4], face)
            matched_pred_set.add(pred_idx)

        # Step 4 — remove dead trackers
        self.trackers = [
            t for i, t in enumerate(self.trackers)
            if i in matched_pred_set or t.time_since_update <= self.max_age
        ]

        # Step 5 — spawn new trackers for unmatched detections
        for det_idx in unmatched_dets:
            face = detected_faces[det_idx]
            tracker = KalmanBoxTracker(face.bbox[:4], self._new_id())
            tracker.last_face = face
            self.trackers.append(tracker)

        # Step 6 — collect output (only confirmed tracks that matched this frame)
        result: List[Face] = []
        for t in self.trackers:
            if (
                t.time_since_update == 0
                and t.hits >= self.min_hits
                and t.last_face is not None
            ):
                t.last_face.track_id = t.track_id
                result.append(t.last_face)

        return result

    def get_active_track_ids(self) -> set:
        """All track IDs currently alive in the tracker (matched or coasting)."""
        return {t.track_id for t in self.trackers}
