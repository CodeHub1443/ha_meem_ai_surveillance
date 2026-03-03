import numpy as np
from typing import List, Dict, Optional
from ..detection.face import Face

class EmbeddingAggregator:
    """Aggregates multiple face embeddings from a single track into a robust consensus embedding."""
    
    def __init__(self, buffer_size: int = 10, min_frames: int = 8):
        self.buffer_size = buffer_size
        self.min_frames = min_frames
        self.track_buffers: Dict[int, List[np.ndarray]] = {}

    def add_face(self, face: Face):
        """Adds a face to the track buffer for aggregation."""
        if face.track_id is None or face.embedding is None:
            return

        if face.track_id not in self.track_buffers:
            self.track_buffers[face.track_id] = []
        
        self.track_buffers[face.track_id].append(face.embedding)
        
        # Maintain buffer size
        if len(self.track_buffers[face.track_id]) > self.buffer_size:
            self.track_buffers[face.track_id].pop(0)

    def get_aggregated_embedding(self, track_id: int) -> Optional[np.ndarray]:
        """Returns the mean normalized embedding for the track."""
        if track_id not in self.track_buffers or len(self.track_buffers[track_id]) < self.min_frames:
            return None
        
        embeddings = np.stack(self.track_buffers[track_id])
        mean_embedding = np.mean(embeddings, axis=0)
        
        # Normalize to unit vector
        norm = np.linalg.norm(mean_embedding)
        if norm > 0:
            return mean_embedding / norm
        return mean_embedding

    def clear_track(self, track_id: int):
        """Removes track data from memory."""
        if track_id in self.track_buffers:
            del self.track_buffers[track_id]
