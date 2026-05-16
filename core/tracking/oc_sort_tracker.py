import numpy as np
from typing import List, Tuple, Optional
from scipy.optimize import linear_sum_assignment

from ..detection.face import Face
from ..utils.bbox import iou_matrix, bbox_to_xywh, xywh_to_bbox


class OCSortKalmanTracker:
    """Kalman filter for a single track, extended for OC-SORT.

    State:       [cx, cy, area, ratio, dcx, dcy, darea]  (7-dim)
    Measurement: [cx, cy, area, ratio]                    (4-dim)

    Adds:
      - last_observation: the last *actual* detected bbox (not predicted),
        used by OCM for IoU matching.
      - apply_oru(): corrects accumulated Kalman state drift after occlusion
        by replaying virtual intermediate observations (ORU).
    """

    def __init__(self, bbox: np.ndarray, track_id: int):
        self.F = np.array([
            [1, 0, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 1, 0],
            [0, 0, 1, 0, 0, 0, 1],
            [0, 0, 0, 1, 0, 0, 0],
            [0, 0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 0, 1],
        ], dtype=np.float64)

        self.H = np.array([
            [1, 0, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0, 0],
            [0, 0, 0, 1, 0, 0, 0],
        ], dtype=np.float64)

        self.Q = np.eye(7, dtype=np.float64)
        self.Q[4:, 4:] *= 0.01

        self.R = np.eye(4, dtype=np.float64)
        self.R[2:, 2:] *= 10.0

        self.P = np.eye(7, dtype=np.float64)
        self.P[4:, 4:] *= 1000.0
        self.P *= 10.0

        z = bbox_to_xywh(bbox[:4])
        self.x = np.zeros((7, 1), dtype=np.float64)
        self.x[:4, 0] = z

        # OCM: last actual detected position (not Kalman-predicted)
        self.last_observation: np.ndarray = bbox[:4].copy()

        self.track_id = track_id
        self.age = 0
        self.hits = 0
        self.time_since_update = 0
        self.last_face: Optional[Face] = None

    def predict(self) -> np.ndarray:
        """Advance Kalman state one step; returns predicted [x1, y1, x2, y2]."""
        if self.x[6, 0] + self.x[2, 0] <= 0:
            self.x[6, 0] = 0.0
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        self.time_since_update += 1
        return xywh_to_bbox(self.x[:4, 0])

    def update(self, bbox: np.ndarray, face: Face):
        """Standard Kalman correction with an actual detection."""
        self.time_since_update = 0
        self.hits += 1
        z = bbox_to_xywh(bbox[:4]).reshape(4, 1)
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - self.H @ self.x)
        self.P = (np.eye(7) - K @ self.H) @ self.P
        self.last_observation = bbox[:4].copy()
        self.last_face = face

    def apply_oru(self, current_bbox: np.ndarray):
        """Observation-Centric Re-Update (ORU).

        When a track is re-found after N frames of occlusion, the Kalman
        state has drifted under the constant-velocity assumption. ORU fixes
        this by simulating N-1 virtual correction steps linearly interpolated
        between last_observation and current_bbox, before the real update().

        Called immediately before update() on re-matched lost tracks.
        """
        n_lost = self.time_since_update  # N after predict() was already called
        if n_lost <= 1:
            return
        for i in range(1, n_lost):
            alpha = i / n_lost
            virtual = (1.0 - alpha) * self.last_observation + alpha * current_bbox[:4]
            z = bbox_to_xywh(virtual).reshape(4, 1)
            S = self.H @ self.P @ self.H.T + self.R
            K = self.P @ self.H.T @ np.linalg.inv(S)
            self.x = self.x + K @ (z - self.H @ self.x)
            self.P = (np.eye(7) - K @ self.H) @ self.P


class OCSORTTracker:
    """OC-SORT: Observation-Centric SORT (Cao et al., 2022).

    Drop-in replacement for SORTTracker with three improvements:

    1. OCM — IoU matching uses last actual observation, not the drifted
       Kalman prediction. Prevents incorrect associations after occlusion.

    2. ORU — Re-matched lost tracks are corrected via virtual observations
       before the normal Kalman update, eliminating state drift.

    3. Two-stage cascade — Active tracks matched first at full IoU threshold;
       lost tracks get a second chance at half the threshold, keeping
       long-occluded tracks alive without flooding with false matches.

    Interface is identical to SORTTracker.update() / get_active_track_ids().
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_age: int = 10,
        min_hits: int = 1,
    ):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.min_hits = min_hits
        self.trackers: List[OCSortKalmanTracker] = []
        self._next_id: int = 0

    def _new_id(self) -> int:
        tid = self._next_id
        self._next_id += 1
        return tid

    def _match(
        self,
        track_bboxes: List[np.ndarray],
        det_bboxes: List[np.ndarray],
        threshold: float,
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        """Hungarian matching on IoU; returns (matches, unmatched_tracks, unmatched_dets)."""
        if not track_bboxes:
            return [], [], list(range(len(det_bboxes)))
        if not det_bboxes:
            return [], list(range(len(track_bboxes))), []

        iou_mat = iou_matrix(
            np.array(track_bboxes, dtype=np.float32),
            np.array(det_bboxes, dtype=np.float32),
        )
        row_ind, col_ind = linear_sum_assignment(1.0 - iou_mat)

        matches: List[Tuple[int, int]] = []
        matched_t: set = set()
        matched_d: set = set()

        for r, c in zip(row_ind, col_ind):
            if iou_mat[r, c] >= threshold:
                matches.append((r, c))
                matched_t.add(r)
                matched_d.add(c)

        unmatched_t = [i for i in range(len(track_bboxes)) if i not in matched_t]
        unmatched_d = [j for j in range(len(det_bboxes)) if j not in matched_d]
        return matches, unmatched_t, unmatched_d

    def update(self, detected_faces: List[Face]) -> List[Face]:
        """Update tracks with new detections; returns faces with track_id set.

        Matching strategy:
          Stage 1 — Recently active tracks vs all detections, at iou_threshold.
                    Uses last_observation for IoU (OCM).
          Stage 2 — Lost/coasting tracks vs remaining detections, at
                    iou_threshold * 0.5. Applies ORU before Kalman update.
          Unmatched detections spawn new tracks.
        """
        # Predict all trackers forward (increments time_since_update for all)
        for t in self.trackers:
            t.predict()

        det_bboxes = [f.bbox[:4] for f in detected_faces]

        # After predict(): time_since_update==1 → was active last frame
        #                  time_since_update >1 → was already coasting
        active_idx = [i for i, t in enumerate(self.trackers) if t.time_since_update <= 1]
        lost_idx   = [i for i, t in enumerate(self.trackers) if t.time_since_update > 1]

        # ── Stage 1: active tracks vs all detections (OCM: last_observation) ──
        active_obs = [self.trackers[i].last_observation for i in active_idx]
        m1, _, unmatched_d1 = self._match(active_obs, det_bboxes, self.iou_threshold)

        matched_set: set = set()
        for ai, di in m1:
            t_idx = active_idx[ai]
            self.trackers[t_idx].update(detected_faces[di].bbox[:4], detected_faces[di])
            matched_set.add(t_idx)

        # ── Stage 2: lost tracks vs remaining detections (lower threshold + ORU) ──
        remaining_faces = [detected_faces[di] for di in unmatched_d1]
        remaining_bboxes = [f.bbox[:4] for f in remaining_faces]
        lost_obs = [self.trackers[i].last_observation for i in lost_idx]
        m2, _, unmatched_d2 = self._match(
            lost_obs, remaining_bboxes, self.iou_threshold * 0.5
        )

        for li, di in m2:
            t_idx = lost_idx[li]
            face = remaining_faces[di]
            self.trackers[t_idx].apply_oru(face.bbox[:4])
            self.trackers[t_idx].update(face.bbox[:4], face)
            matched_set.add(t_idx)

        # Remove tracks that have been lost longer than max_age
        self.trackers = [
            t for i, t in enumerate(self.trackers)
            if i in matched_set or t.time_since_update <= self.max_age
        ]

        # Spawn new trackers for detections unmatched by both stages
        for di in unmatched_d2:
            face = remaining_faces[di]
            new_tracker = OCSortKalmanTracker(face.bbox[:4], self._new_id())
            new_tracker.last_face = face
            self.trackers.append(new_tracker)

        # Collect output — only tracks confirmed this frame
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
        """All track IDs currently alive (matched or coasting)."""
        return {t.track_id for t in self.trackers}