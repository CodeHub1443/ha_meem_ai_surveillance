import numpy as np
from typing import List, Dict
from ..detection.face import Face

class IOUTracker:
    """Simple IOU-based tracker for face tracks."""
    
    def __init__(self, iou_threshold: float = 0.3, max_age: int = 5):
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.next_id = 0
        self.tracks: Dict[int, Dict] = {} # id -> {face, age}

    def _calculate_iou(self, bbox1, bbox2):
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])
        
        inter_area = max(0, x2 - x1) * max(0, y2 - y1)
        bbox1_area = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        bbox2_area = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        
        iou = inter_area / float(bbox1_area + bbox2_area - inter_area + 1e-6)
        return iou

    def update(self, detected_faces: List[Face]) -> List[Face]:
        """Updates tracks with new detections."""
        updated_faces = []
        matched_indices = set()
        
        # Match with existing tracks
        for track_id, track_data in list(self.tracks.items()):
            best_iou = -1
            best_idx = -1
            
            for i, face in enumerate(detected_faces):
                if i in matched_indices:
                    continue
                iou = self._calculate_iou(track_data["face"].bbox, face.bbox)
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

        # Create new tracks for unmatched detections
        for i, face in enumerate(detected_faces):
            if i not in matched_indices:
                face.track_id = self.next_id
                self.tracks[self.next_id] = {"face": face, "age": 0}
                self.next_id += 1
                updated_faces.append(face)
        
        return updated_faces
