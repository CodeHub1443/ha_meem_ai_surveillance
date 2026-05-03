from typing import List, Dict
from ..detection.face import Face
from ..utils.bbox import calculate_iou


class IOUTracker:
    """Simple IoU-based greedy tracker (kept as lightweight fallback).

    For production use, prefer SORTTracker which handles occlusion and
    fast motion via Kalman filter + Hungarian optimal assignment.
    """

    def __init__(self, iou_threshold: float = 0.3, max_age: int = 5):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.next_id = 0
        self.tracks: Dict[int, Dict] = {}

    def update(self, detected_faces: List[Face]) -> List[Face]:
        updated_faces = []
        matched_indices = set()

        for track_id, track_data in list(self.tracks.items()):
            best_iou = -1
            best_idx = -1

            for i, face in enumerate(detected_faces):
                if i in matched_indices:
                    continue
                iou = calculate_iou(track_data["face"].bbox, face.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_idx = i

            if best_iou > self.iou_threshold:
                self.tracks[track_id] = {"face": detected_faces[best_idx], "age": 0}
                detected_faces[best_idx].track_id = track_id
                updated_faces.append(detected_faces[best_idx])
                matched_indices.add(best_idx)
            else:
                track_data["age"] += 1
                if track_data["age"] > self.max_age:
                    del self.tracks[track_id]

        for i, face in enumerate(detected_faces):
            if i not in matched_indices:
                face.track_id = self.next_id
                self.tracks[self.next_id] = {"face": face, "age": 0}
                self.next_id += 1
                updated_faces.append(face)

        return updated_faces

    def get_active_track_ids(self) -> set:
        return set(self.tracks.keys())
