import numpy as np
from typing import Dict, Optional, Tuple

class FaceDatabase:
    """In-memory database for matching face embeddings using cosine similarity."""

    def __init__(self, embeddings: Dict[str, np.ndarray]):
        """
        Initializes the database and normalizes all stored embeddings.
        
        Args:
            embeddings: Dictionary mapping identity IDs to their 512-d embeddings.
        """
        self.ids = []
        self.stored_embeddings = None
        
        if embeddings:
            self.ids = list(embeddings.keys())
            # Stack and normalize all embeddings at once for vectorization
            raw_embeddings = np.stack(list(embeddings.values()))
            norms = np.linalg.norm(raw_embeddings, axis=1, keepdims=True)
            self.stored_embeddings = raw_embeddings / (norms + 1e-6)

    def match(self, query_embedding: np.ndarray, threshold: float) -> Tuple[Optional[str], float]:
        """
        Finds the best matching identity for a query embedding.
        
        Args:
            query_embedding: The query 512-d embedding.
            threshold: Minimum cosine similarity score to qualify as a match.
            
        Returns:
            Tuple of (best_id, best_score). best_id is None if below threshold.
        """
        if self.stored_embeddings is None:
            return None, 0.0

        # Normalize query embedding
        norm = np.linalg.norm(query_embedding)
        if norm > 0:
            query_embedding = query_embedding / norm

        # Compute cosine similarity using dot product (since both are normalized)
        scores = np.dot(self.stored_embeddings, query_embedding)
        
        # Find best match
        best_idx = np.argmax(scores)
        best_score = float(scores[best_idx])
        
        if best_score >= threshold:
            return self.ids[best_idx], best_score
        
        return None, best_score
