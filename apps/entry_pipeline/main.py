# Must be set before onnxruntime is imported (affects ALL ORT sessions including insightface)
import os
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("ORT_NUM_THREADS", "2")

import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core import frame_buffer as _fb

_STREAM_FPS = 15
_STREAM_INTERVAL = 1.0 / _STREAM_FPS
_STREAM_WIDTH = 960
_STREAM_HEIGHT = 540

import cv2
import numpy as np
import yaml

from core.database import FaceDatabase, EventStore
from core.detection import SCRFDDetector, Face
from core.events import EventEmitter, SnapshotWriter
from core.fusion import EmbeddingAggregator
from core.io_worker import AsyncIOWorker
from core.pipeline_state import PipelineState
from core.quality import calculate_blur_score, AdaptiveBlurThreshold
from core.recognition import AdaFaceRecognizer
from core.tracking import OCSORTTracker
from core.utils.config import load_config
from core.utils.image import align_face, pose_weight

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
        dataset_cfg = {}
        try:
            with open("configs/dataset.yaml") as f:
                dataset_cfg = yaml.safe_load(f) or {}
        except FileNotFoundError:
            pass
        gallery_path = dataset_cfg.get("dataset", {}).get(
            "gallery_embeddings", "dataset/gallery_embeddings.npy"
        )
        try:
            gallery = np.load(gallery_path, allow_pickle=True).item()
        except FileNotFoundError:
            raise RuntimeError(
                f"Gallery file not found: '{gallery_path}'. "
                "Build the gallery with the dataset tool before starting the pipeline."
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to load gallery from '{gallery_path}': {exc}") from exc
        if not gallery:
            raise RuntimeError(
                f"Gallery at '{gallery_path}' is empty — no identities enrolled. "
                "Enroll at least one person before starting the pipeline."
            )
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

        self.tracker = OCSORTTracker(
            iou_threshold=track_cfg.get("iou_threshold", 0.3),
            max_age=track_cfg.get("max_age", 10),
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
        self.upgrade_margin: float = rec_cfg.get("upgrade_margin", 0.05)
        self.match_margin: float = rec_cfg.get("match_margin", 0.05)
        self.match_top_k: int = rec_cfg.get("match_top_k", 10)
        # Seconds to wait before emitting an UNKNOWN event, giving the pipeline
        # time to collect a frontal frame and upgrade to AUTHORIZED first.
        self.unknown_hold_seconds: float = rec_cfg.get("unknown_hold_seconds", 3.0)

        roi = camera_cfg.get("roi")
        self.roi: Optional[tuple] = tuple(roi) if roi and len(roi) == 4 else None
        if self.roi:
            log.info(f"[{self.camera_id}] ROI active: x1={self.roi[0]} y1={self.roi[1]} x2={self.roi[2]} y2={self.roi[3]}")

        event_emitter = EventEmitter(
            camera_id=self.camera_id,
            log_file="logs/events.jsonl",
        )
        snapshot_writer = SnapshotWriter(
            base_dir="snapshots",
            camera_id=self.camera_id,
        )
        event_store = EventStore()
        self.io_worker = AsyncIOWorker(event_emitter, snapshot_writer, event_store=event_store)

        # Tracks that were logged as quality-rejected once (avoid per-frame spam)
        self._logged_size_reject: set = set()
        self._logged_blur_reject: set = set()

        self.running = False

        self._last_stream_ts: float = 0.0

    # ------------------------------------------------------------------
    # Per-frame processing
    # ------------------------------------------------------------------

    def _process_frame(self, frame: np.ndarray, frame_ts: datetime) -> np.ndarray:
        annotated = frame.copy()

        # ── 1. Detection ──────────────────────────────────────────────
        faces: List[Face] = self.models.detector.detect(frame)

        # ── 2. Tracking ───────────────────────────────────────────────
        tracked: List[Face] = self.tracker.update(faces)

        # ── 3. ROI filter — discard faces whose centre falls outside the gate zone ──
        if self.roi:
            rx1, ry1, rx2, ry2 = self.roi
            tracked = [
                f for f in tracked
                if rx1 <= (f.bbox[0] + f.bbox[2]) / 2 <= rx2
                and ry1 <= (f.bbox[1] + f.bbox[3]) / 2 <= ry2
            ]

        # ── 4. Self-expiry: clean aggregator + state ───────────────────
        expired_ids = self.aggregator.expire_stale_tracks()
        for tid in expired_ids:
            held = self.state.release_track(tid)
            if held is not None:
                # Person left frame without being recognised → emit now
                ts = datetime.fromisoformat(held["event_data"]["timestamp"])
                self.io_worker.submit(
                    held["frame"], held["event_data"], None, ts, held["embedding"]
                )
                log.info(
                    f"[{self.camera_id}] EMIT DEFERRED UNKNOWN track={tid} (track expired)"
                )
            self._logged_size_reject.discard(tid)
            self._logged_blur_reject.discard(tid)

        # Purge log-suppress sets for tracks OC-SORT dropped that never produced
        # embeddings (too small / too blurry throughout) — those IDs never appear
        # in expire_stale_tracks() because the aggregator has no entry for them.
        active_ids = self.tracker.get_active_track_ids()
        self._logged_size_reject &= active_ids
        self._logged_blur_reject &= active_ids

        # Flush held unknowns whose hold period elapsed (person still in frame)
        for tid, held in self.state.pop_overdue_unknowns(self.unknown_hold_seconds):
            ts = datetime.fromisoformat(held["event_data"]["timestamp"])
            self.io_worker.submit(
                held["frame"], held["event_data"], None, ts, held["embedding"]
            )
            log.info(
                f"[{self.camera_id}] EMIT DEFERRED UNKNOWN track={tid} (hold period elapsed)"
            )

        # ── 5. Quality gate + crop all valid faces ─────────────────────
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

            # Permanently decided tracks (AUTHORIZED, not upgradeable) need no
            # further processing — their snapshot was already saved at decision
            # time and re-running recognition on them wastes CPU and GPU cycles.
            # UNKNOWN upgradeable tracks are NOT skipped: they still need
            # embeddings so a later frontal frame can upgrade them to AUTHORIZED.
            if self.state.is_decided(tid) and not self.state.is_upgradeable(tid):
                continue

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
            pw = pose_weight(face.kps) if face.kps is not None else 1.0
            size_factor = min(face.width / 112.0, 1.0)
            face.quality_score = blur * face.confidence * pw * size_factor
            valid_faces.append(face)
            aligned = (
                align_face(frame, face.kps, crop=crop)
                if face.kps is not None
                else cv2.resize(crop, (112, 112))
            )
            valid_crops.append(aligned)

        # ── 6. Batched recognition ────────────────────────────────────
        if valid_crops:
            embeddings = self.models.recognizer.extract_embeddings_batch(valid_crops)
            for face, emb in zip(valid_faces, embeddings):
                face.embedding = emb

        # ── 7. Aggregation + matching ─────────────────────────────────
        for face in valid_faces:
            self.aggregator.add_face(face)

            upgradeable = self.state.is_upgradeable(face.track_id)

            # AUTHORIZED tracks are permanently closed; UNKNOWN tracks stay
            # in play so a later frontal frame can upgrade them.
            if self.state.is_decided(face.track_id) and not upgradeable:
                continue

            consensus = self.aggregator.get_aggregated_embedding(face.track_id)
            if consensus is None:
                continue

            identity, score = self.models.face_db.match(
                consensus, self.similarity_threshold,
                margin=self.match_margin, top_k=self.match_top_k,
            )

            # Always log at INFO so scores are visible for threshold tuning
            log.info(
                f"[{self.camera_id}] track={face.track_id} "
                f"→ best_match={identity or 'UNKNOWN'} score={score:.4f} "
                f"(threshold={self.similarity_threshold})"
            )

            if upgradeable:
                if identity is None or score < self.similarity_threshold + self.upgrade_margin:
                    log.debug(
                        f"[{self.camera_id}] UPGRADE skipped track={face.track_id}: "
                        f"score={score:.4f} below threshold={self.similarity_threshold + self.upgrade_margin:.4f}"
                    )
                    continue
                log.info(
                    f"[{self.camera_id}] UPGRADE track={face.track_id}: "
                    f"UNKNOWN → {identity} score={score:.4f}"
                )
                self.state.upgrade_track(face.track_id, identity)
                # Discard the held UNKNOWN — only the AUTHORIZED event is emitted
                self.state.discard_held_unknown(face.track_id)
                emit_identity, emit_event = identity, "AUTHORIZED"
            else:
                if not self.state.can_alert(identity, face.track_id):
                    log.debug(
                        f"[{self.camera_id}] COOLDOWN suppressed track={face.track_id} "
                        f"identity={identity or 'UNKNOWN'}"
                    )
                    continue
                self.state.mark_decided(face.track_id, identity)
                emit_identity = identity
                emit_event = "AUTHORIZED" if identity else "UNKNOWN"

            # ── 8. Emit event (async I/O) ──────────────────────────────
            event_data = {
                "timestamp": frame_ts.isoformat(),
                "camera_id": self.camera_id,
                "track_id": face.track_id,
                "identity": emit_identity,
                "score": round(float(score), 4),
                "event": emit_event,
            }

            # Always annotate the live display frame regardless of hold status
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                emit_identity or "UNKNOWN",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )

            # Resize to stream resolution once for snapshot/hold — avoids a ~6 MB
            # full-res copy on the hot path (io_worker copies again inside submit).
            snap_frame = cv2.resize(frame, (_STREAM_WIDTH, _STREAM_HEIGHT))

            if emit_event == "UNKNOWN":
                # Hold — wait to see if this track upgrades before emitting
                self.state.hold_unknown(
                    face.track_id, snap_frame, event_data, consensus
                )
                log.info(
                    f"[{self.camera_id}] HOLD UNKNOWN track={face.track_id} "
                    f"score={score:.3f} (waiting up to {self.unknown_hold_seconds:.0f}s)"
                )
            else:
                self.io_worker.submit(snap_frame, event_data, emit_identity, frame_ts, None)
                log.info(
                    f"[{self.camera_id}] {emit_event}: "
                    f"{emit_identity or 'Unknown'} score={score:.3f}"
                )

        # ── 9. Visualise all tracked faces ────────────────────────────
        for face in tracked:
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 255), 1)
            cv2.putText(
                annotated,
                f"ID:{face.track_id}",
                (x1, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1,
            )

        # ── 10. Draw ROI box on display ───────────────────────────────
        if self.roi:
            rx1, ry1, rx2, ry2 = (int(v) for v in self.roi)
            cv2.rectangle(annotated, (rx1, ry1), (rx2, ry2), (0, 255, 255), 2)
            cv2.putText(annotated, "Gate ROI", (rx1, ry1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        return annotated

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self):
        self.running = True
        _RECONNECT_DELAYS = [5, 10, 30]  # seconds between attempts

        if not self.url:
            log.warning(f"[{self.camera_id}] No URL configured — worker exiting.")
            return

        while self.running:
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                log.error(f"[{self.camera_id}] Cannot open stream: {self.url}")
                cap.release()
                self._reconnect_with_backoff(_RECONNECT_DELAYS)
                continue

            log.info(f"[{self.camera_id}] Stream started — {self.camera_name}")
            consecutive_failures = 0
            consecutive_proc_errors = 0
            _MAX_PROC_ERRORS = 10

            while self.running:
                try:
                    ret, frame = cap.read()
                    if not ret:
                        consecutive_failures += 1
                        if consecutive_failures >= 5:
                            log.warning(
                                f"[{self.camera_id}] {consecutive_failures} consecutive read "
                                "failures — reconnecting"
                            )
                            break
                        continue

                    consecutive_failures = 0
                    frame_ts = datetime.now()
                    t0 = time.perf_counter()

                    # Main processing step: detection, tracking, recognition, and event generation
                    annotated = self._process_frame(frame, frame_ts)
                    consecutive_proc_errors = 0

                    # Calculate FPS for display
                    fps = 1.0 / max(time.perf_counter() - t0, 1e-6)
                    cv2.putText(
                        annotated,
                        f"{self.camera_id}  FPS:{fps:.1f}",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 80, 0), 2,
                    )

                    # Throttled encode + push to in-memory frame buffer
                    now_s = time.perf_counter()
                    if now_s - self._last_stream_ts >= _STREAM_INTERVAL:
                        self._last_stream_ts = now_s
                        try:
                            small = cv2.resize(annotated, (_STREAM_WIDTH, _STREAM_HEIGHT))
                            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
                            if ok:
                                _fb.put(self.camera_id, buf.tobytes())
                        except Exception:
                            pass

                except Exception as e:
                    consecutive_proc_errors += 1
                    log.error(f"[{self.camera_id}] Frame processing error: {e}", exc_info=True)
                    if consecutive_proc_errors >= _MAX_PROC_ERRORS:
                        log.error(
                            f"[{self.camera_id}] {_MAX_PROC_ERRORS} consecutive processing "
                            "errors — reconnecting"
                        )
                        break

            cap.release()
            if self.running:
                self._reconnect_with_backoff(_RECONNECT_DELAYS)

        self.io_worker.stop()
        log.info(f"[{self.camera_id}] Worker stopped")

    def _reconnect_with_backoff(self, delays: list):
        """Wait with escalating delays before the next reconnect attempt."""
        for i, delay in enumerate(delays):
            log.info(
                f"[{self.camera_id}] Reconnecting in {delay}s "
                f"(attempt {i + 1}/{len(delays)})…"
            )
            for _ in range(delay):
                if not self.running:
                    return
                time.sleep(1)
        log.error(f"[{self.camera_id}] All reconnect attempts exhausted — worker exiting")

    def set_roi(self, roi: Optional[list]):
        self.roi = tuple(roi) if roi else None

    def stop(self):
        self.running = False


# ── Snapshot retention cleanup ────────────────────────────────────────────────

def _cleanup_old_snapshots(base_dir: str = "snapshots", keep_days: int = 30):
    """Delete snapshot date-folders older than keep_days. Safe to call at startup."""
    base = Path(base_dir)
    if not base.exists():
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    deleted = 0
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        try:
            if datetime.strptime(folder.name, "%Y-%m-%d") < cutoff:
                shutil.rmtree(folder)
                deleted += 1
        except ValueError:
            pass  # folder name doesn't match date pattern — leave it alone
    if deleted:
        log.info("Snapshot cleanup: removed %d folder(s) older than %d days", deleted, keep_days)


# ── Persist ROI back to cameras.yaml ──────────────────────────────────────────

def _save_roi(camera_id: str, roi: list, config_path: str = "configs/cameras.yaml"):
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    for cam in data.get("cameras", []):
        if cam["id"] == camera_id:
            cam["roi"] = [int(v) for v in roi] if roi else None
            break
    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=None, sort_keys=False)
    log.info(f"[{camera_id}] ROI {'cleared' if not roi else f'saved: {roi}'} → {config_path}")


# ── Pipeline entry point ───────────────────────────────────────────────────────

def run_pipeline():
    config = load_config(
        "configs/default.yaml",
        "configs/thresholds.yaml",
        "configs/tensorrt.yaml",
    )
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

    _cleanup_old_snapshots(
        base_dir="snapshots",
        keep_days=config.get("snapshots", {}).get("keep_days", 30),
    )

    models = SharedModels(config)

    workers = [CameraWorker(cam, models, config) for cam in cameras]
    threads = [
        threading.Thread(target=w.run, daemon=True, name=f"cam-{w.camera_id}")
        for w in workers
    ]

    log.info(f"Starting {len(workers)} camera worker(s)…")
    for t in threads:
        t.start()

    log.info("Pipeline running — frames shared via in-memory buffer. Press Ctrl+C to stop.")
    try:
        # Keep main thread alive while worker threads run; 1s timeout lets
        # KeyboardInterrupt be delivered promptly even inside join().
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=1.0)
    except KeyboardInterrupt:
        log.info("Interrupt received — shutting down…")
    finally:
        for w in workers:
            w.stop()
        for t in threads:
            t.join(timeout=5)
        log.info("Pipeline shut down cleanly")


if __name__ == "__main__":
    run_pipeline()
