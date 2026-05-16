"""Offline clustering of unknown face embeddings.

Algorithm
---------
1. Load every row from unknown_embeddings.
2. Group by track_id and average all embeddings per track → one L2-normalised
   representative vector per track visit.
3. Run AgglomerativeClustering(metric='cosine', linkage='complete',
   distance_threshold=<threshold>).
   - Complete linkage: ALL pairwise cosine distances within a cluster must be
     below the threshold.  This prevents the single-linkage chaining problem
     where HDBSCAN(min_samples=1) would bridge different people through
     intermediate embeddings.
4. Post-process: clusters smaller than min_cluster_size → singleton (-1).
   Renumber remaining clusters 0, 1, 2, ...
5. Write cluster labels back to unknown_embeddings and record run metadata.

Unique unauthorized count = n_distinct_clusters + n_singleton_tracks.

Tuning distance_threshold (cosine distance = 1 − cosine_similarity):
  0.3  → only very confident same-person pairs (similarity > 0.7) — strict
  0.45 → same-person at moderate angles (similarity > 0.55) — default
  0.6  → looser; may merge lookalike strangers
"""

import logging
from collections import Counter
from typing import Dict, Optional

import numpy as np

from core.database.event_store import EventStore

log = logging.getLogger(__name__)


def run_clustering(
    db_path: Optional[str] = None,
    min_cluster_size: int = 2,
    distance_threshold: float = 0.45,
) -> Dict:
    """Run the full clustering pipeline. Returns a result summary dict.

    Args:
        db_path:            Path to the SQLite DB. Uses the default if None.
        min_cluster_size:   Minimum tracks to form a named cluster.
                            Smaller groups are labelled -1 (singletons).
        distance_threshold: Cosine distance ceiling for merging two tracks
                            into the same cluster. Lower = stricter.

    Returns:
        {n_embeddings, n_tracks, n_clusters, n_noise, unique_unauthorized}
    """
    try:
        from sklearn.cluster import AgglomerativeClustering
    except ImportError:
        raise RuntimeError(
            "scikit-learn >= 0.21 is required for clustering. "
            "Run: pip install 'scikit-learn>=1.3'"
        )

    store = EventStore(db_path) if db_path else EventStore()

    rows = store.get_all_unknown_embeddings()
    if not rows:
        log.info("No unknown embeddings found — skipping clustering.")
        return {
            "n_embeddings": 0,
            "n_tracks": 0,
            "n_clusters": 0,
            "n_noise": 0,
            "unique_unauthorized": 0,
        }

    n_embeddings = len(rows)
    log.info("Loaded %d unknown embeddings from DB.", n_embeddings)

    # ── Track-level aggregation ──────────────────────────────────────────────
    track_groups: Dict[int, Dict] = {}
    for row in rows:
        tid = row["track_id"]
        emb = np.frombuffer(row["embedding"], dtype=np.float32).copy()
        if tid not in track_groups:
            track_groups[tid] = {"db_ids": [], "embeddings": []}
        track_groups[tid]["db_ids"].append(row["id"])
        track_groups[tid]["embeddings"].append(emb)

    track_ids = list(track_groups.keys())
    track_reps = []
    for tid in track_ids:
        mean_emb = np.mean(track_groups[tid]["embeddings"], axis=0)
        norm = np.linalg.norm(mean_emb)
        track_reps.append(mean_emb / norm if norm > 1e-9 else mean_emb)

    n_tracks = len(track_ids)
    log.info(
        "Track representatives: %d (from %d raw embeddings).", n_tracks, n_embeddings
    )

    # ── Clustering ───────────────────────────────────────────────────────────
    rep_matrix = np.stack(track_reps).astype(np.float64)  # (n_tracks, 512)

    if n_tracks < 2:
        raw_labels = np.full(n_tracks, -1, dtype=int)
    else:
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="complete",          # all-pairs constraint — no chaining
            distance_threshold=distance_threshold,
        )
        raw_labels = clusterer.fit_predict(rep_matrix).astype(int)

    # Post-process: clusters smaller than min_cluster_size → singleton (-1)
    label_counts = Counter(int(l) for l in raw_labels)
    labels_list = [
        int(l) if label_counts[int(l)] >= min_cluster_size else -1
        for l in raw_labels
    ]

    # Renumber named clusters contiguously: 0, 1, 2, ...
    unique_clusters = sorted(set(l for l in labels_list if l >= 0))
    remap = {old: new for new, old in enumerate(unique_clusters)}
    labels = np.array(
        [remap[l] if l >= 0 else -1 for l in labels_list],
        dtype=int,
    )

    n_clusters = len(unique_clusters)
    n_noise = int(np.sum(labels == -1))

    log.info(
        "Result: %d clusters, %d singletons → %d unique unauthorized.",
        n_clusters,
        n_noise,
        n_clusters + n_noise,
    )

    # ── Write results back ───────────────────────────────────────────────────
    updates = []
    for tid, label in zip(track_ids, labels.tolist()):
        for db_id in track_groups[tid]["db_ids"]:
            updates.append((db_id, int(label)))

    store.update_cluster_results(
        updates,
        n_embeddings=n_embeddings,
        n_clusters=n_clusters,
        n_noise=n_noise,
    )

    return {
        "n_embeddings": n_embeddings,
        "n_tracks": n_tracks,
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "unique_unauthorized": n_clusters + n_noise,
    }
