import os
import sys
import cv2
import yaml
import numpy as np
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from core.recognition import AdaFaceRecognizer

# Maximum prototype embeddings kept per identity after k-means clustering.
MAX_PROTOTYPES = 10


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


def main():
    config = _load_config()

    dataset_cfg = config.get("dataset", {})
    aligned_dir = Path(dataset_cfg.get("aligned_faces", "dataset/aligned_faces"))

    if not aligned_dir.exists():
        print(f"Error: '{aligned_dir}' does not exist.  Run extract_faces.py first.")
        return

    model_path = config.get("models", {}).get("adaface_onnx")
    if not model_path or not os.path.exists(model_path):
        print(f"Error: AdaFace model not found at '{model_path}'")
        return

    print("Initializing AdaFace Recognizer…")
    recognizer = AdaFaceRecognizer(config, model_path)

    gallery: dict = {}
    persons_processed = 0
    total_images = 0

    subdirs = sorted(d for d in aligned_dir.iterdir() if d.is_dir())
    if not subdirs:
        print(f"No identity folders found in {aligned_dir}")
        return

    print(f"Building gallery — input: {aligned_dir}")
    print("-" * 50)

    for person_path in subdirs:
        person_id = person_path.name
        raw_embeddings = []

        for img_path in person_path.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            emb = recognizer.extract_embedding(img)
            raw_embeddings.append(emb)
            total_images += 1

        if not raw_embeddings:
            continue

        # Stack and normalise
        stacked = np.stack(raw_embeddings).astype(np.float32)
        norms = np.linalg.norm(stacked, axis=1, keepdims=True)
        normalised = stacked / np.where(norms > 0, norms, 1.0)

        # Cluster into at most MAX_PROTOTYPES representative prototypes
        prototypes = _kmeans_prototypes(normalised, MAX_PROTOTYPES)

        gallery[person_id] = [prototypes[i] for i in range(len(prototypes))]
        persons_processed += 1

        print(
            f"  {person_id:25s} | raw images: {len(raw_embeddings):4d} "
            f"→ prototypes: {len(gallery[person_id])}"
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
    print("-" * 50)


if __name__ == "__main__":
    main()
