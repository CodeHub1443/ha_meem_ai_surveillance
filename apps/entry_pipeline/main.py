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
from core import pipeline_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
_log_dir = Path("logs")
_log_dir.mkdir(parents=True, exist_ok=True)
_fh = logging.FileHandler(_log_dir / "pipeline.log", encoding="utf-8")
_fh.setLevel(logging.INFO)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
logging.getLogger().addHandler(_fh)
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
            min_frames=fusion_cfg.get("min_frames", 5),
            min_decision_seconds=fusion_cfg.get("min_decision_seconds", 2.0),
            recency_decay=fusion_cfg.get("recency_decay", 0.95),
            expire_after_seconds=fusion_cfg.get("expire_after_seconds", 5.0),
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

        diag_cfg = config.get("diagnostic", {})
        self._diag_enabled: bool = diag_cfg.get("per_frame_logging", False)
        self._prev_embeddings: dict = {}   # track_id → last L2-normalized embedding (gate passes only)
        self._frame_diag: dict = {}        # track_id → {"scores": list[float], "first_ts": float}

        _quality_cfg = config.get("quality", {})
        self._min_pose_w: float = _quality_cfg.get("min_pose_weight", 0.0)
        self._min_stab: float = _quality_cfg.get("min_stab", 0.0)

        # Baseline metrics — Phase 0 instrumentation (no behaviour change)
        self.metrics = pipeline_metrics.get_or_create(self.camera_id)
        # Maps track_id → last emitted event type for flip detection
        self._track_last_event: dict = {}
        # Timestamp of last daily metric summary log
        self._last_metric_log_day: int = -1

        # Best-frame buffer: track_id → (quality_score, full_res_frame)
        # Updated every frame that passes all quality gates; saved to raw_frames
        # at decision time so gallery can be rebuilt from real runtime frames.
        self._best_frames: dict = {}
        dataset_cfg = config.get("dataset", {})
        self._raw_frames_root = Path(
            dataset_cfg.get("raw_frames", "dataset/raw_frames")
        )

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
        # Phase 1 (RC3 fix): snapshot active OC-SORT tracks BEFORE expiry.
        # A track absent from OC-SORT is truly gone; one still present just
        # had a SCRFD detection gap (face turned away) and must keep its
        # identity state intact.
        active_ids = self.tracker.get_active_track_ids()

        expired_ids = self.aggregator.expire_stale_tracks()
        for tid in expired_ids:
            if self.state.is_decided(tid):
                self.metrics.record_decided_clobber()
            if tid not in active_ids:
                # OC-SORT also dropped this track — person truly left the frame.
                held = self.state.release_track(tid)
                if held is not None:
                    ts = datetime.fromisoformat(held["event_data"]["timestamp"])
                    self.io_worker.submit(
                        held["frame"], held["event_data"], None, ts, held["embedding"]
                    )
                    log.info(
                        f"[{self.camera_id}] EMIT DEFERRED UNKNOWN track={tid} (track lost)"
                    )
            self._logged_size_reject.discard(tid)
            self._logged_blur_reject.discard(tid)
            self._prev_embeddings.pop(tid, None)
            self._frame_diag.pop(tid, None)
            self._best_frames.pop(tid, None)

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

            if self._min_pose_w > 0.0 and pw < self._min_pose_w:
                log.debug(
                    "[%s] track=%d SKIP: pose_w=%.2f < %.2f",
                    self.camera_id, tid, pw, self._min_pose_w,
                )
                continue

            size_factor = min(face.width / 112.0, 1.0)
            face.quality_score = blur * face.confidence * pw * size_factor

            if face.kps is not None:
                aligned, align_ok = align_face(frame, face.kps, crop=crop)
            else:
                aligned, align_ok = cv2.resize(crop, (112, 112)), False

            if not align_ok:
                # Phase 2 (RC2 fix): degenerate geometry — extreme profile or
                # edge-of-frame landmarks.  Raw-crop resize produces a garbage
                # embedding that dilutes the consensus.  Skip the frame entirely
                # rather than feeding noise into the aggregator.
                self.metrics.record_alignment_fallback()
                log.debug(
                    f"[{self.camera_id}] track={tid} alignment failed — frame skipped"
                )
                continue

            valid_faces.append(face)
            valid_crops.append(aligned)

            # Keep the sharpest/most-frontal frame seen for this track.
            # Saved to raw_frames at decision time instead of the decision frame
            # (by which point the person may have already walked past the camera).
            prev_best, _ = self._best_frames.get(tid, (-1.0, None))
            if face.quality_score > prev_best:
                self._best_frames[tid] = (face.quality_score, frame.copy())

        # ── 6. Batched recognition ────────────────────────────────────
        if valid_crops:
            embeddings = self.models.recognizer.extract_embeddings_batch(valid_crops)
            for face, emb in zip(valid_faces, embeddings):
                tid = face.track_id
                prev_emb = self._prev_embeddings.get(tid)
                cur_stab = float(np.dot(emb, prev_emb)) if prev_emb is not None else None

                # Stability gate — skip tracking-contamination frames.
                # Do NOT update _prev_embeddings on skip; next frame compares against
                # the last clean embedding, not the contaminated one.
                if cur_stab is not None and self._min_stab > 0.0 and cur_stab < self._min_stab:
                    log.debug(
                        "[%s] track=%d SKIP: stab=%.3f < %.2f (embedding jump)",
                        self.camera_id, tid, cur_stab, self._min_stab,
                    )
                    continue  # face.embedding stays None → aggregator ignores it

                face.embedding = emb
                self._prev_embeddings[tid] = emb.copy()

                if self._diag_enabled:
                    top3 = self.models.face_db.match_diagnostics(emb, top_k=self.match_top_k)
                    frame_margin = top3[0][1] - top3[1][1] if len(top3) >= 2 else 0.0
                    diag_entry = self._frame_diag.setdefault(
                        tid, {"scores": [], "identities": [], "first_ts": time.time()}
                    )
                    frame_num = len(diag_entry["scores"]) + 1
                    diag_entry["scores"].append(top3[0][1] if top3 else 0.0)
                    diag_entry["identities"].append(top3[0][0] if top3 else None)
                    pw_val = pose_weight(face.kps) if face.kps is not None else 1.0
                    top_str = "  ".join(
                        f"{pid}:{sc:.3f}" for pid, sc in top3
                    ) if top3 else "no_gallery"
                    stab_str = f"{cur_stab:.3f}" if cur_stab is not None else "n/a"
                    log.info(
                        "[DIAG] cam=%s track=%d frame=%d"
                        " face=%dx%d blur=%.1f quality=%.3f pose_w=%.2f"
                        " | %s | margin=%.3f stab=%s",
                        self.camera_id, tid, frame_num,
                        int(face.width), int(face.height),
                        face.blur_score, face.quality_score, pw_val,
                        top_str, frame_margin, stab_str,
                    )

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

            if self._diag_enabled:
                diag = self._frame_diag.get(face.track_id, {})
                frame_scores = diag.get("scores", [])
                elapsed = time.time() - diag.get("first_ts", time.time())
                top3c = self.models.face_db.match_diagnostics(
                    consensus, top_k=self.match_top_k
                )
                cons_margin = top3c[0][1] - top3c[1][1] if len(top3c) >= 2 else 0.0
                best_f = max(frame_scores) if frame_scores else 0.0
                avg_f = float(np.mean(frame_scores)) if frame_scores else 0.0
                med_f = float(np.median(frame_scores)) if frame_scores else 0.0
                top3c_str = "  ".join(
                    f"{pid}:{sc:.3f}" for pid, sc in top3c
                ) if top3c else "no_gallery"
                id_seq = diag.get("identities", [])
                id_switches = sum(
                    1 for i in range(1, len(id_seq))
                    if id_seq[i] is not None
                    and id_seq[i - 1] is not None
                    and id_seq[i] != id_seq[i - 1]
                )
                if emit_event == "UNKNOWN":
                    reject_reason = "margin" if score >= self.similarity_threshold else "threshold"
                else:
                    reject_reason = "none"
                log.info(
                    "[DIAG DECISION] cam=%s track=%d frames=%d elapsed=%.2fs"
                    " | consensus: %s | margin=%.3f"
                    " | best_frame=%.3f avg_frame=%.3f median_frame=%.3f"
                    " | id_switches=%d reject_reason=%s"
                    " → %s (threshold=%.2f)",
                    self.camera_id, face.track_id,
                    len(frame_scores), elapsed,
                    top3c_str, cons_margin,
                    best_f, avg_f, med_f,
                    id_switches, reject_reason,
                    emit_event, self.similarity_threshold,
                )

                if emit_event == "AUTHORIZED":
                    diag_class = "AUTHORIZED"
                elif id_switches <= 2 and best_f >= 0.40:
                    diag_class = "LOW_CONFIDENCE_MATCH"
                else:
                    diag_class = "NO_STABLE_MATCH"
                candidate = top3c[0][0] if top3c else "none"
                log.info(
                    "[DIAG CLASS] cam=%s track=%d state=%s"
                    " best=%.3f switches=%d consensus=%.3f candidate=%s",
                    self.camera_id, face.track_id, diag_class,
                    best_f, id_switches, score, candidate,
                )

            # ── Baseline metrics for this decision ─────────────────────
            self.metrics.record_event(face.track_id)
            prev_event = self._track_last_event.get(face.track_id)
            if prev_event == "AUTHORIZED" and emit_event == "UNKNOWN":
                self.metrics.record_track_flip()
                log.warning(
                    f"[{self.camera_id}] TRACK FLIP detected: track={face.track_id} "
                    f"AUTHORIZED → UNKNOWN (RC3 symptom)"
                )
            self._track_last_event[face.track_id] = emit_event

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

            snap_frame = frame  # full-res — io_worker copies inside submit()

            # Save the best-quality runtime frame to raw_frames for gallery use.
            # This is the clearest frame from when the person was mid-traversal,
            # not the decision frame (often their back or an empty spot).
            self._save_gallery_frame(face.track_id, emit_identity, emit_event)

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

    def _save_gallery_frame(self, tid: int, identity: Optional[str], event: str) -> None:
        """Save the best-quality buffered frame to raw_frames for gallery rebuilding.

        AUTHORIZED → raw_frames/<identity>/
        UNKNOWN    → raw_frames/_unknowns/<camera_id>/
        """
        entry = self._best_frames.pop(tid, None)
        if entry is None:
            return
        _, best_frame = entry

        if event == "AUTHORIZED" and identity:
            out_dir = self._raw_frames_root / identity
        else:
            out_dir = self._raw_frames_root / "_unknowns" / self.camera_id

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"{ts}_{self.camera_id}_t{tid}.jpg"
            cv2.imwrite(str(out_dir / filename), best_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            log.debug("[%s] gallery frame saved: %s/%s", self.camera_id, out_dir.name, filename)
        except Exception as exc:
            log.warning("[%s] gallery frame save failed: %s", self.camera_id, exc)

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

                    # Daily metric summary — log once per calendar day
                    today = frame_ts.toordinal()
                    if today != self._last_metric_log_day:
                        self._last_metric_log_day = today
                        self.metrics.log_summary(log)

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
        "configs/dataset.yaml",
    )
    try:
        with open("configs/cameras.yaml") as f:
            camera_cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error("configs/cameras.yaml not found")
        return

    all_cameras = camera_cfg.get("cameras", [])
    # Honour explicit active flag; fall back to URL-presence check for legacy entries
    cameras = [c for c in all_cameras if c.get("active", bool(c.get("url")))]
    if not cameras:
        log.error("No active cameras defined in cameras.yaml")
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
    _cam_cfg_path = "configs/cameras.yaml"
    _worker_map = {w.camera_id: w for w in workers}
    _cam_cfg_mtime = os.path.getmtime(_cam_cfg_path)
    try:
        # Keep main thread alive while worker threads run; 1s timeout lets
        # KeyboardInterrupt be delivered promptly even inside join().
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=1.0)
            # Hot-reload config when cameras.yaml is modified externally (e.g. via API).
            try:
                mtime = os.path.getmtime(_cam_cfg_path)
                if mtime != _cam_cfg_mtime:
                    _cam_cfg_mtime = mtime
                    with open(_cam_cfg_path) as f:
                        reloaded = yaml.safe_load(f) or {}
                    for cam_cfg in reloaded.get("cameras", []):
                        cid = cam_cfg["id"]
                        is_active = cam_cfg.get("active", bool(cam_cfg.get("url")))

                        if cid in _worker_map:
                            worker = _worker_map[cid]
                            # ROI: applied immediately without restart
                            worker.set_roi(cam_cfg.get("roi"))
                            log.info("[%s] ROI hot-reloaded: %s", cid, cam_cfg.get("roi"))
                            # Disable: stop worker immediately
                            if not is_active and worker.running:
                                log.info("[%s] Disabled via config — stopping worker", cid)
                                worker.stop()
                        elif is_active and cam_cfg.get("url"):
                            # New camera added at runtime with a valid URL — spawn its worker now
                            log.info("[%s] New camera detected in config — spawning worker", cid)
                            new_worker = CameraWorker(cam_cfg, models, config)
                            new_thread = threading.Thread(
                                target=new_worker.run,
                                daemon=True,
                                name=f"cam-{cid}",
                            )
                            _worker_map[cid] = new_worker
                            workers.append(new_worker)
                            threads.append(new_thread)
                            new_thread.start()
            except Exception as e:
                log.warning("Config hot-reload check failed: %s", e)
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
