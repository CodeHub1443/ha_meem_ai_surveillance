import logging
import numpy as np
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    log.info("faiss not installed — using linear cosine search. "
             "Install faiss-cpu or faiss-gpu for faster gallery matching.")


class FaceDatabase:
    """In-memory face gallery with cosine similarity matching.

    Uses FAISS IndexFlatIP when available (exact inner-product search on
    L2-normalised vectors = cosine similarity).  Falls back to a NumPy
    dot-product scan for environments without faiss.

    The ``match`` method *always* returns the best raw score even when the
    threshold is not met, so callers can log near-misses for threshold tuning.
    """

    def __init__(self, embeddings: Dict[str, list], use_faiss: bool = True):
        self.ids: list = []
        self.stored_embeddings: Optional[np.ndarray] = None
        self._faiss_index = None
        self._use_faiss = False

        if not embeddings:
            return

        all_embs, all_ids = [], []
        for person_id, emb_list in embeddings.items():
            for emb in emb_list:
                all_embs.append(emb)
                all_ids.append(person_id)

        raw = np.stack(all_embs).astype(np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        self.stored_embeddings = raw / np.where(norms > 0, norms, 1.0)
        self.ids = all_ids

        if use_faiss and _FAISS_AVAILABLE:
            dim = self.stored_embeddings.shape[1]
            self._faiss_index = faiss.IndexFlatIP(dim)
            self._faiss_index.add(self.stored_embeddings)
            self._use_faiss = True
            log.info(f"FAISS index built: {len(self.ids)} embeddings, dim={dim}")

    # ------------------------------------------------------------------

    def match(
        self, query_embedding: np.ndarray, threshold: float
    ) -> Tuple[Optional[str], float]:
        """Find the best matching identity for a query embedding.

        Args:
            query_embedding: 512-d embedding (will be L2-normalised internally).
            threshold: Minimum cosine similarity to accept a match.

        Returns:
            (best_id, best_score).  ``best_id`` is None if below threshold.
            ``best_score`` is always the raw top-1 cosine score — use it to
            log near-misses even when identity is None.
        """
        if self.stored_embeddings is None:
            return None, 0.0

        q = query_embedding.astype(np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        if self._use_faiss:
            scores, indices = self._faiss_index.search(
                q.reshape(1, -1), 1
            )
            best_score = float(scores[0][0])
            best_id = self.ids[int(indices[0][0])]
        else:
            scores = np.dot(self.stored_embeddings, q)
            best_idx = int(np.argmax(scores))
            best_score = float(scores[best_idx])
            best_id = self.ids[best_idx]

        if best_score >= threshold:
            return best_id, best_score
        return None, best_score
