"""Offline clustering of unknown face embeddings using HDBSCAN.

Algorithm
---------
1. Load every row from unknown_embeddings.
2. Group by track_id and average all embeddings per track into one
   representative vector (track-level aggregation).  This collapses the
   many raw frames from one visit into a single clean descriptor and
   dramatically reduces the number of vectors fed to HDBSCAN.
3. L2-normalise each representative so Euclidean distance equals cosine
   distance — HDBSCAN then effectively clusters by face similarity.
4. Run HDBSCAN(min_cluster_size=2, metric='euclidean').
   - Cluster label ≥ 0  → person appeared in ≥ 2 distinct tracks.
   - Cluster label  = -1 → singleton (appeared in exactly 1 track).
5. Write cluster labels back to unknown_embeddings and record run metadata
   in cluster_meta.

Unique unauthorized count = n_distinct_clusters + n_singleton_tracks.
"""

import logging
from typing import Dict, Optional

import numpy as np

from core.database.event_store import EventStore

log = logging.getLogger(__name__)


def run_clustering(
    db_path: Optional[str] = None,
    min_cluster_size: int = 2,
) -> Dict:
    """Run the full clustering pipeline. Returns a result summary dict.

    Args:
        db_path:          Path to the SQLite DB.  Uses the default if None.
        min_cluster_size: Minimum number of track representatives to form a
                          cluster.  Tracks below this size are labelled noise
                          (-1) and counted as singletons.

    Returns:
        {
            "n_embeddings": int,   # raw rows in unknown_embeddings
            "n_tracks":     int,   # unique tracks (vectors fed to HDBSCAN)
            "n_clusters":   int,   # HDBSCAN clusters found (label >= 0)
            "n_noise":      int,   # singleton tracks (label == -1)
            "unique_unauthorized": int,  # n_clusters + n_noise
        }
    """
    try:
        from sklearn.cluster import HDBSCAN
    except ImportError:
        raise RuntimeError(
            "scikit-learn >= 1.3 is required for clustering. "
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

    # ── Step 2: track-level aggregation ───────────────────────────────────────
    track_groups: Dict[int, Dict] = {}
    for row in rows:
        tid = row["track_id"]
        emb = np.frombuffer(row["embedding"], dtype=np.float32).copy()
        if tid not in track_groups:
            track_groups[tid] = {"db_ids": [], "embeddings": []}
        track_groups[tid]["db_ids"].append(row["id"])
        track_groups[tid]["embeddings"].append(emb)

    # One representative per track (mean → L2-normalise)
    track_ids = list(track_groups.keys())
    track_reps = []
    for tid in track_ids:
        mean_emb = np.mean(track_groups[tid]["embeddings"], axis=0)
        norm = np.linalg.norm(mean_emb)
        track_reps.append(mean_emb / norm if norm > 1e-9 else mean_emb)

    n_tracks = len(track_ids)
    log.info("Track representatives: %d (from %d embeddings).", n_tracks, n_embeddings)

    # ── Step 3 & 4: HDBSCAN ───────────────────────────────────────────────────
    rep_matrix = np.stack(track_reps).astype(np.float32)  # (n_tracks, 512)

    if n_tracks < 2:
        # Only one track — call it a singleton, nothing to cluster
        labels = np.array([-1] * n_tracks, dtype=int)
    else:
        effective_min = min(min_cluster_size, n_tracks)
        clusterer = HDBSCAN(
            min_cluster_size=effective_min,
            min_samples=1,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(rep_matrix)

    n_clusters = len(set(int(l) for l in labels if l >= 0))
    n_noise = int(np.sum(labels == -1))

    log.info(
        "HDBSCAN: %d clusters, %d singletons (noise). Unique unauthorized: %d.",
        n_clusters, n_noise, n_clusters + n_noise,
    )

    # ── Step 5: write results back ─────────────────────────────────────────────
    # Assign the track-level label to every embedding row that belongs to that track
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
