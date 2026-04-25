import logging
import threading
import time
from datetime import datetime
from typing import List, Optional

import cv2
import numpy as np

from core.database import FaceDatabase
from core.detection import SCRFDDetector, Face
from core.events import EventEmitter, SnapshotWriter
from core.fusion import EmbeddingAggregator
from core.io_worker import AsyncIOWorker
from core.pipeline_state import PipelineState
from core.quality import calculate_blur_score, AdaptiveBlurThreshold
from core.recognition import AdaFaceRecognizer
from core.tracking import SORTTracker
from core.utils.config import load_config
from core.utils.image import align_face

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("pipeline")


# ── Shared models container ────────────────────────────────────────────────────

class SharedModels:
    """Models shared (thread-safely) across all camera workers."""

    def __init__(self, config: dict):
        log.info("Loading SCRFD detector…")
        self.detector = SCRFDDetector(config, config["models"]["scrfd_onnx"])

        log.info("Loading AdaFace recognizer…")
        self.recognizer = AdaFaceRecognizer(config, config["models"]["adaface_onnx"])

        log.info("Loading face gallery…")
        import yaml
        dataset_cfg = {}
        try:
            with open("configs/dataset.yaml") as f:
                dataset_cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        gallery_path = dataset_cfg.get("dataset", {}).get(
            "gallery_embeddings", "dataset/gallery_embeddings.npy"
        )
        gallery = np.load(gallery_path, allow_pickle=True).item()
        self.face_db = FaceDatabase(gallery)
        log.info(f"Gallery loaded: {len(gallery)} identities")


# ── Per-camera worker ──────────────────────────────────────────────────────────

class CameraWorker:
    """Runs the full inference pipeline for a single camera in a thread.

    Each worker owns:
      - SORTTracker        (per-camera track IDs)
      - EmbeddingAggregator (per-camera temporal buffers)
      - AdaptiveBlurThreshold (adapts to the camera's image quality)
      - PipelineState      (decided_tracks, cooldown)
      - AsyncIOWorker      (snapshot + event log off the hot path)

    Shared read-only across all workers:
      - SCRFDDetector, AdaFaceRecognizer, FaceDatabase
    """

    def __init__(self, camera_cfg: dict, models: SharedModels, config: dict):
        self.camera_id: str = camera_cfg["id"]
        self.camera_name: str = camera_cfg.get("name", self.camera_id)
        self.url = camera_cfg["url"]
        self.config = config

        rec_cfg = config.get("recognition", {})
        fusion_cfg = config.get("fusion", {})
        track_cfg = config.get("tracking", {})

        self.tracker = SORTTracker(
            iou_threshold=track_cfg.get("iou_threshold", 0.3),
            max_age=track_cfg.get("max_age", 5),
        )
        self.aggregator = EmbeddingAggregator(
            buffer_size=fusion_cfg.get("buffer_size", 10),
            min_frames=2,
            min_decision_seconds=fusion_cfg.get("min_decision_seconds", 0.5),
            recency_decay=fusion_cfg.get("recency_decay", 0.95),
            expire_after_seconds=fusion_cfg.get("expire_after_seconds", 3.0),
        )
        self.blur_threshold = AdaptiveBlurThreshold(
            window_size=config.get("quality", {}).get("adaptive_window", 500),
            percentile=config.get("quality", {}).get("adaptive_percentile", 20.0),
            fallback=rec_cfg.get("blur_threshold", 100.0),
            min_samples=10,
        )
        self.state = PipelineState(
            camera_id=self.camera_id,
            cooldown_seconds=config.get("identity_cooldown_seconds", 6.0),
        )

        self.models = models
        self.min_face_size: int = rec_cfg.get("min_face_size", 140)
        self.similarity_threshold: float = rec_cfg.get("similarity_threshold", 0.55)

        event_emitter = EventEmitter(
            camera_id=self.camera_id,
            log_file="logs/events.jsonl",
        )
        snapshot_writer = SnapshotWriter(
            base_dir="snapshots",
            camera_id=self.camera_id,
        )
        self.io_worker = AsyncIOWorker(event_emitter, snapshot_writer)

        # Tracks that were logged as quality-rejected once (avoid per-frame spam)
        self._logged_size_reject: set = set()
        self._logged_blur_reject: set = set()

        # Latest annotated frame — read by the main display thread
        self._display_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self.running = False

    # ------------------------------------------------------------------
    # Per-frame processing
    # ------------------------------------------------------------------

    def _process_frame(self, frame: np.ndarray, frame_ts: datetime) -> np.ndarray:
        annotated = frame.copy()

        # ── 1. Detection ──────────────────────────────────────────────
        faces: List[Face] = self.models.detector.detect(frame)

        # ── 2. Tracking ───────────────────────────────────────────────
        tracked: List[Face] = self.tracker.update(faces)

        # ── 3. Self-expiry: clean aggregator + state ───────────────────
        expired_ids = self.aggregator.expire_stale_tracks()
        for tid in expired_ids:
            self.state.release_track(tid)
            self._logged_size_reject.discard(tid)
            self._logged_blur_reject.discard(tid)

        # ── 4. Quality gate + crop all valid faces ─────────────────────
        valid_faces: List[Face] = []
        valid_crops: List[np.ndarray] = []

        for face in tracked:
            tid = face.track_id
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            crop = frame[max(0, y1):y2, max(0, x1):x2]
            if crop.size == 0:
                continue

            # Feed blur score for ALL detected faces so the adaptive threshold
            # warms up quickly regardless of whether the face is large enough.
            blur = calculate_blur_score(crop)
            self.blur_threshold.update(blur)

            if face.width < self.min_face_size:
                if tid not in self._logged_size_reject:
                    log.info(
                        f"[{self.camera_id}] track={tid} SKIP: face too small "
                        f"(width={face.width:.0f}px < {self.min_face_size}px)"
                    )
                    self._logged_size_reject.add(tid)
                continue
            self._logged_size_reject.discard(tid)

            blur_thr = self.blur_threshold.threshold()

            if blur < blur_thr:
                if tid not in self._logged_blur_reject:
                    log.info(
                        f"[{self.camera_id}] track={tid} SKIP: too blurry "
                        f"(score={blur:.1f} < threshold={blur_thr:.1f})"
                    )
                    self._logged_blur_reject.add(tid)
                continue
            self._logged_blur_reject.discard(tid)

            face.blur_score = blur
            valid_faces.append(face)
            aligned = (
                align_face(frame, face.kps)
                if face.kps is not None
                else cv2.resize(crop, (112, 112))
            )
            valid_crops.append(aligned)

        # ── 5. Batched recognition ────────────────────────────────────
        if valid_crops:
            embeddings = self.models.recognizer.extract_embeddings_batch(valid_crops)
            for face, emb in zip(valid_faces, embeddings):
                face.embedding = emb

        # ── 6. Aggregation + matching ─────────────────────────────────
        for face in valid_faces:
            self.aggregator.add_face(face)

            if self.state.is_decided(face.track_id):
                continue

            consensus = self.aggregator.get_aggregated_embedding(face.track_id)
            if consensus is None:
                continue

            identity, score = self.models.face_db.match(
                consensus, self.similarity_threshold
            )

            # Always log at INFO so scores are visible for threshold tuning
            log.info(
                f"[{self.camera_id}] track={face.track_id} "
                f"→ best_match={identity or 'UNKNOWN'} score={score:.4f} "
                f"(threshold={self.similarity_threshold})"
            )

            if not self.state.can_alert(identity, face.track_id):
                continue

            # ── 7. Emit event (async I/O) ──────────────────────────────
            event_data = {
                "timestamp": frame_ts.isoformat(),
                "camera_id": self.camera_id,
                "track_id": face.track_id,
                "identity": identity,
                "score": round(float(score), 4),
                "event": "AUTHORIZED" if identity else "UNKNOWN",
            }
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                identity or "UNKNOWN",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )
            self.io_worker.submit(annotated, event_data, identity, frame_ts)
            self.state.mark_decided(face.track_id, identity)

            log.info(
                f"[{self.camera_id}] {event_data['event']}: "
                f"{identity or 'Unknown'} score={score:.3f}"
            )

        # ── 8. Visualise all tracked faces ────────────────────────────
        for face in tracked:
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 1)
            cv2.putText(
                annotated,
                f"ID:{face.track_id}",
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1,
            )

        return annotated

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self):
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            log.error(f"[{self.camera_id}] Cannot open stream: {self.url}")
            return

        self.running = True
        log.info(f"[{self.camera_id}] Stream started — {self.camera_name}")

        while self.running:
            try:
                ret, frame = cap.read()
                if not ret:
                    log.warning(f"[{self.camera_id}] Frame read failed — stream ended")
                    break

                frame_ts = datetime.now()
                t0 = time.perf_counter()

                annotated = self._process_frame(frame, frame_ts)

                fps = 1.0 / max(time.perf_counter() - t0, 1e-6)
                cv2.putText(
                    annotated,
                    f"{self.camera_id}  FPS:{fps:.1f}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 80, 0), 2,
                )

                with self._frame_lock:
                    self._display_frame = annotated

            except Exception as e:
                log.error(f"[{self.camera_id}] Frame processing error: {e}", exc_info=True)

        cap.release()
        self.io_worker.stop()
        self.running = False
        log.info(f"[{self.camera_id}] Worker stopped")

    def get_display_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._display_frame.copy() if self._display_frame is not None else None

    def stop(self):
        self.running = False


# ── Pipeline entry point ───────────────────────────────────────────────────────

def run_pipeline():
    config = load_config(
        "configs/default.yaml",
        "configs/thresholds.yaml",
    )
    import yaml
    try:
        with open("configs/cameras.yaml") as f:
            camera_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error("configs/cameras.yaml not found")
        return

    cameras = camera_cfg.get("cameras", [])
    if not cameras:
        log.error("No cameras defined in cameras.yaml")
        return

    # Shared models (one load, all cameras)
    models = SharedModels(config)

    workers = [CameraWorker(cam, models, config) for cam in cameras]
    threads = [
        threading.Thread(target=w.run, daemon=True, name=f"cam-{w.camera_id}")
        for w in workers
    ]

    log.info(f"Starting {len(workers)} camera worker(s)…")
    for t in threads:
        t.start()

    # Main thread owns all cv2.imshow calls (required on Windows)
    try:
        while any(w.running or not t.is_alive() is False for w, t in zip(workers, threads)):
            any_alive = False
            for w in workers:
                frame = w.get_display_frame()
                if frame is not None:
                    cv2.imshow(f"Ha-Meem — {w.camera_name}", frame)
                    any_alive = True
            if not any_alive and not any(t.is_alive() for t in threads):
                break
            if cv2.waitKey(1) & 0xFF == ord("q"):
                log.info("Quit signal received")
                break
    finally:
        for w in workers:
            w.stop()
        for t in threads:
            t.join(timeout=5)
        cv2.destroyAllWindows()
        log.info("Pipeline shut down cleanly")


if __name__ == "__main__":
    run_pipeline()
