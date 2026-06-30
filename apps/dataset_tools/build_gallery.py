import os
import sys
import cv2
import yaml
import numpy as np
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from core.recognition import AdaFaceRecognizer
from core.quality.blur import calculate_blur_score

# Maximum prototype embeddings kept per identity after k-means clustering.
MAX_PROTOTYPES = 10

# Aligned 112×112 crops below this blur score are skipped before embedding.
MIN_CROP_BLUR = 15.0

# Embeddings with cosine similarity to their cluster mean below this are
# treated as outliers (misaligned / occluded frames) and removed.
OUTLIER_SIM_THRESHOLD = 0.25

# Pairs of identities whose prototypes come within this cosine similarity
# are flagged — they are at risk of mutual confusion at runtime.
INTER_CLASS_WARNING_THRESHOLD = 0.50


def _load_config():
    def _read(path):
        if not os.path.exists(path):
            return {}
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}

    cfg = _read("configs/default.yaml")
    cfg.update(_read("configs/thresholds.yaml"))
    dataset = _read("configs/dataset.yaml")
    if dataset:
        cfg.setdefault("dataset", {}).update(dataset.get("dataset", {}))
    return cfg


def _kmeans_prototypes(embeddings: np.ndarray, k: int) -> np.ndarray:
    """Select up to k representative embeddings via k-means clustering.

    Uses scipy's kmeans on normalised float64 vectors.  If clustering fails
    for any reason (too few samples, convergence issues) falls back to
    returning the original embeddings unchanged.

    Returns L2-normalised prototype array of shape (min(k, N), 512).
    """
    n = len(embeddings)
    if n <= k:
        return embeddings  # Already few enough

    try:
        from scipy.cluster.vq import kmeans

        # scipy kmeans works best on float64
        vecs = embeddings.astype(np.float64)
        centroids, _ = kmeans(vecs, k)

        # Re-normalise centroids to unit sphere
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        return (centroids / np.where(norms > 0, norms, 1.0)).astype(np.float32)

    except Exception as e:
        print(f"  [warn] k-means failed ({e}), keeping first {k} embeddings")
        return embeddings[:k]


def main() -> set:
    """Build the gallery from aligned face crops. Returns the set of person_id strings enrolled."""
    config = _load_config()

    dataset_cfg = config.get("dataset", {})
    aligned_dir = Path(dataset_cfg.get("aligned_faces", "dataset/aligned_faces"))

    if not aligned_dir.exists():
        print(f"Error: '{aligned_dir}' does not exist.  Run extract_faces.py first.")
        return set()

    model_path = config.get("models", {}).get("adaface_onnx")
    if not model_path or not os.path.exists(model_path):
        print(f"Error: AdaFace model not found at '{model_path}'")
        return set()

    print("Initializing AdaFace Recognizer…")
    recognizer = AdaFaceRecognizer(config, model_path)

    gallery: dict = {}
    persons_processed = 0
    total_images = 0

    subdirs = sorted(d for d in aligned_dir.iterdir() if d.is_dir())
    if not subdirs:
        print(f"No identity folders found in {aligned_dir}")
        return set()

    print(f"Building gallery — input: {aligned_dir}")
    print("-" * 50)

    for person_path in subdirs:
        person_id = person_path.name
        raw_embeddings = []

        skipped_blur = 0
        for img_path in person_path.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            img = cv2.imread(str(img_path))
            if img is None:
                continue

            # Skip blurry aligned crops before embedding
            blur = calculate_blur_score(img)
            if blur < MIN_CROP_BLUR:
                skipped_blur += 1
                continue

            emb = recognizer.extract_embedding(img)
            raw_embeddings.append(emb)
            total_images += 1

        if not raw_embeddings:
            print(f"  {person_id:25s} | WARNING: no usable images (all blurry?)")
            continue

        # Stack and normalise
        stacked = np.stack(raw_embeddings).astype(np.float32)
        norms = np.linalg.norm(stacked, axis=1, keepdims=True)
        normalised = stacked / np.where(norms > 0, norms, 1.0)

        # Outlier removal: drop embeddings too far from the cluster mean
        removed_outliers = 0
        if len(normalised) > 2:
            mean_emb = normalised.mean(axis=0)
            mean_emb /= max(np.linalg.norm(mean_emb), 1e-6)
            sims = normalised @ mean_emb
            mask = sims >= OUTLIER_SIM_THRESHOLD
            if mask.sum() == 0:
                mask = sims >= sims.max() - 0.05
            removed_outliers = int((~mask).sum())
            normalised = normalised[mask]

        # Cluster into at most MAX_PROTOTYPES representative prototypes
        prototypes = _kmeans_prototypes(normalised, MAX_PROTOTYPES)

        gallery[person_id] = [prototypes[i] for i in range(len(prototypes))]
        persons_processed += 1

        notes = []
        if skipped_blur:
            notes.append(f"blur_skip={skipped_blur}")
        if removed_outliers:
            notes.append(f"outliers_removed={removed_outliers}")
        note_str = f"  [{', '.join(notes)}]" if notes else ""

        print(
            f"  {person_id:25s} | raw images: {len(raw_embeddings):4d} "
            f"-> prototypes: {len(gallery[person_id])}{note_str}"
        )

    output_path = Path(
        dataset_cfg.get("gallery_embeddings", "dataset/gallery_embeddings.npy")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(output_path), gallery)

    print("-" * 50)
    print(f"Persons processed : {persons_processed}")
    print(f"Total images used : {total_images}")
    print(f"Identities saved  : {len(gallery)}")
    print(f"Output            : {output_path}")

    # Inter-class proximity check — flag identity pairs at risk of confusion
    ids = list(gallery.keys())
    warnings = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            pa = np.stack(gallery[a])
            pb = np.stack(gallery[b])
            max_sim = float((pa @ pb.T).max())
            if max_sim >= INTER_CLASS_WARNING_THRESHOLD:
                warnings.append((max_sim, a, b))

    if warnings:
        print("\nInter-class proximity warnings (risk of confusion):")
        for sim, a, b in sorted(warnings, reverse=True):
            print(f"  {a} ↔ {b}  max_sim={sim:.3f}")
    else:
        print("\nNo inter-class proximity issues found.")
    print("-" * 50)

    return set(gallery.keys())


if __name__ == "__main__":
    main()
