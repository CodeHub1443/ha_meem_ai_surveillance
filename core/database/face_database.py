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
        self,
        query_embedding: np.ndarray,
        threshold: float,
        margin: float = 0.0,
        top_k: int = 10,
    ) -> Tuple[Optional[str], float]:
        """Find the best matching identity for a query embedding.

        Retrieves the top-K embedding matches, groups them by identity (taking
        the max score per identity), then applies both a threshold and a margin
        test against the second-best identity.  This prevents false accepts when
        two gallery identities score very close together — a near-tie means the
        top-1 pick is unreliable.

        Args:
            query_embedding: 512-d embedding (will be L2-normalised internally).
            threshold: Minimum cosine similarity to accept a match.
            margin: Minimum gap between top-1 and top-2 identity scores.
                    If the gap is smaller than this, the match is rejected.
                    Set to 0.0 to disable the margin test.
            top_k: Number of embedding candidates to retrieve before
                   identity-level aggregation.  Must be >= 2 to enable the
                   margin test; should comfortably exceed the max number of
                   prototypes per identity in the gallery.

        Returns:
            (best_id, best_score).  ``best_id`` is None if below threshold or
            margin test fails.  ``best_score`` is always the raw top-1 identity
            score so callers can log near-misses.
        """
        if self.stored_embeddings is None:
            return None, 0.0

        q = query_embedding.astype(np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        k = max(2, min(top_k, len(self.ids)))

        if self._use_faiss:
            raw_scores, raw_indices = self._faiss_index.search(q.reshape(1, -1), k)
            score_iter = zip(raw_scores[0], raw_indices[0])
        else:
            all_scores = np.dot(self.stored_embeddings, q)
            top_indices = np.argsort(all_scores)[::-1][:k]
            score_iter = ((float(all_scores[i]), i) for i in top_indices)

        # Group by identity — keep the highest prototype score per person
        identity_scores: dict = {}
        for s, idx in score_iter:
            identity = self.ids[int(idx)]
            if identity not in identity_scores or s > identity_scores[identity]:
                identity_scores[identity] = float(s)

        # Sort identities by score descending
        ranked = sorted(identity_scores.items(), key=lambda x: x[1], reverse=True)
        best_id, best_score = ranked[0]

        if best_score < threshold:
            return None, best_score

        # Margin test: reject if second-best identity is too close
        if margin > 0.0 and len(ranked) >= 2:
            second_score = ranked[1][1]
            if best_score - second_score < margin:
                return None, best_score

        return best_id, best_score

    def match_diagnostics(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
    ) -> list:
        """Return up to 3 (identity, score) pairs for diagnostic logging.

        No threshold or margin filtering — raw ranked identity scores only.
        """
        if self.stored_embeddings is None:
            return []

        q = query_embedding.astype(np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        k = max(2, min(top_k, len(self.ids)))

        if self._use_faiss:
            raw_scores, raw_indices = self._faiss_index.search(q.reshape(1, -1), k)
            score_iter = zip(raw_scores[0], raw_indices[0])
        else:
            all_scores = np.dot(self.stored_embeddings, q)
            top_indices = np.argsort(all_scores)[::-1][:k]
            score_iter = ((float(all_scores[i]), i) for i in top_indices)

        identity_scores: dict = {}
        for s, idx in score_iter:
            identity = self.ids[int(idx)]
            if identity not in identity_scores or s > identity_scores[identity]:
                identity_scores[identity] = float(s)

        ranked = sorted(identity_scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:3]
