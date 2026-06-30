#!/usr/bin/env python3
"""cam2_capture.py — Live face capture for gallery building.

Connects to a camera's RTSP stream and saves full-resolution frames whenever
a face passes quality gates (pose, blur, size) — capturing the person at their
best frontal moment rather than waiting for a pipeline decision to fire.

Saved frames drop into the raw_frames folder under the given person name and
feed directly into extract_faces.py -> build_gallery.py.

Usage
-----
  # Capture for a specific person (creates raw_frames/b35_najira/ subfolder)
  python apps/dataset_tools/cam2_capture.py --person b35_najira

  # Different camera or custom output
  python apps/dataset_tools/cam2_capture.py --camera camera_01 --person a1_rozina

  # Capture everything (unsorted) — organise folder manually afterwards
  python apps/dataset_tools/cam2_capture.py

Controls (preview window)
-------------------------
  Q / ESC  — quit
  S        — force-save the current frame immediately
  P        — pause / resume auto-capture

Quality gate defaults (tune with --min-blur / --min-pose / --min-size)
------------------------------------------------------------------------
  min_blur  : 50   (higher than the pipeline adaptive threshold — want clean crops)
  min_pose  : 0.50 (clearly frontal; 0.0 = profile, 1.0 = dead-on)
  min_size  : 80   (face bbox width in pixels, same as pipeline runtime gate)
  cooldown  : 2.0s (minimum gap between auto-saves to avoid duplicate frames)
  max_saves : 30   (stop after this many saves; 0 = unlimited)
"""

import argparse
import logging
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.detection import SCRFDDetector
from core.quality import calculate_blur_score
from core.utils.config import load_config
from core.utils.image import pose_weight

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("cam2_capture")

# ── Colour palette (BGR) ─────────────────────────────────────────────────────
_GREEN  = (0, 220, 0)
_YELLOW = (0, 200, 255)
_RED    = (0, 0, 220)
_WHITE  = (255, 255, 255)
_GREY   = (120, 120, 120)
_FONT   = cv2.FONT_HERSHEY_SIMPLEX


def _load_camera_url(camera_id: str) -> str:
    cameras_path = Path("configs/cameras.yaml")
    if not cameras_path.exists():
        raise FileNotFoundError("configs/cameras.yaml not found")
    with open(cameras_path) as f:
        camera_cfg = yaml.safe_load(f) or {}
    cameras = camera_cfg.get("cameras", [])
    for cam in cameras:
        if cam.get("id") == camera_id:
            url = cam.get("url", "")
            if not url:
                raise ValueError(f"Camera '{camera_id}' has no URL in cameras.yaml")
            return url
    ids = [c.get("id") for c in cameras]
    raise ValueError(f"Camera '{camera_id}' not found in cameras.yaml. Available: {ids}")


def _draw_label(frame: np.ndarray, text: str, x: int, y: int,
                colour=_WHITE, scale: float = 0.55, thickness: int = 1) -> None:
    cv2.putText(frame, text, (x, y), _FONT, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, (x, y), _FONT, scale, colour, thickness, cv2.LINE_AA)


def _overlay_hud(frame: np.ndarray, saved: int, max_saves: int,
                 paused: bool, fps: float) -> None:
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 28), (0, 0, 0), -1)
    status = "PAUSED" if paused else "CAPTURING"
    colour = _YELLOW if paused else _GREEN
    limit  = f"/{max_saves}" if max_saves > 0 else ""
    hud    = f"[{status}]  saved={saved}{limit}  fps={fps:.1f}  Q=quit  S=save  P=pause"
    _draw_label(frame, hud, 8, 20, colour)


def run_capture(
    camera_id: str,
    person: str,
    output_dir: Path,
    min_blur: float,
    min_pose: float,
    min_size: int,
    cooldown: float,
    max_saves: int,
    show_preview: bool,
    config: dict,
) -> None:
    url = _load_camera_url(camera_id)
    log.info("Camera  : %s  (%s)", camera_id, url)
    log.info("Person  : %s", person)
    log.info("Output  : %s", output_dir)
    log.info("Gates   : blur>=%.0f  pose>=%.2f  size>=%dpx", min_blur, min_pose, min_size)
    log.info("Cooldown: %.1fs  max_saves=%s", cooldown, max_saves if max_saves else "unlimited")

    output_dir.mkdir(parents=True, exist_ok=True)

    model_path = config.get("models", {}).get("scrfd_onnx")
    if not model_path or not Path(model_path).exists():
        log.error("SCRFD model not found at '%s'. Check configs/default.yaml.", model_path)
        sys.exit(1)

    log.info("Loading SCRFD detector...")
    detector = SCRFDDetector(config, model_path)
    log.info("Detector ready.")

    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        log.error("Cannot open stream: %s", url)
        sys.exit(1)

    saved      = 0
    paused     = False
    last_save  = 0.0       # wall-clock time of most recent auto-save
    frame_count = 0
    fps_ts     = time.time()
    fps        = 0.0

    log.info("Stream open. Press Q to quit, S to force-save, P to pause.")
    if show_preview:
        cv2.namedWindow("cam2_capture", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("cam2_capture", 960, 540)

    while True:
        ret, frame = cap.read()
        if not ret:
            log.warning("Frame read failed — reconnecting in 2s...")
            time.sleep(2)
            cap.release()
            cap = cv2.VideoCapture(url)
            continue

        frame_count += 1
        now = time.time()

        # Rolling FPS estimate
        if frame_count % 15 == 0:
            fps = 15.0 / max(now - fps_ts, 1e-3)
            fps_ts = now

        display = frame.copy()
        faces   = detector.detect(frame)

        # ── Evaluate each detected face ──────────────────────────────────
        best_face      = None   # highest-quality face this frame
        best_score     = -1.0
        save_this_frame = False

        for face in faces:
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            x1 = max(0, x1); y1 = max(0, y1)
            x2 = min(frame.shape[1], x2); y2 = min(frame.shape[0], y2)

            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            blur  = calculate_blur_score(crop)
            pw    = pose_weight(face.kps) if face.kps is not None else 1.0
            width = int(face.width)

            fail_size  = width  < min_size
            fail_blur  = blur   < min_blur
            fail_pose  = pw     < min_pose
            passed     = not (fail_size or fail_blur or fail_pose)

            # Build failure reason string for display
            reasons = []
            if fail_size: reasons.append(f"size={width}<{min_size}")
            if fail_blur: reasons.append(f"blur={blur:.0f}<{min_blur:.0f}")
            if fail_pose: reasons.append(f"pose={pw:.2f}<{min_pose:.2f}")
            reason_str = "  ".join(reasons) if reasons else ""

            colour = _GREEN if passed else (_YELLOW if not fail_size else _RED)
            cv2.rectangle(display, (x1, y1), (x2, y2), colour, 2)

            label = f"blur={blur:.0f} pose={pw:.2f} sz={width}"
            if reason_str:
                label = f"SKIP: {reason_str}"
            _draw_label(display, label, x1, max(y1 - 6, 14), colour)

            if passed:
                # Track the best qualifying face by combined score
                combined = blur * pw * min(width / 112.0, 1.0)
                if combined > best_score:
                    best_score = combined
                    best_face  = face

        # ── Auto-save logic ──────────────────────────────────────────────
        if not paused and best_face is not None:
            if (max_saves == 0 or saved < max_saves) and (now - last_save >= cooldown):
                ts       = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename = f"{ts}_{camera_id}.jpg"
                save_path = output_dir / filename
                cv2.imwrite(str(save_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved    += 1
                last_save = now
                log.info("[%d] Saved: %s  (blur=%.0f pose=%.2f size=%d)",
                         saved, save_path.name,
                         calculate_blur_score(frame[
                             max(0, int(best_face.bbox[1])):min(frame.shape[0], int(best_face.bbox[3])),
                             max(0, int(best_face.bbox[0])):min(frame.shape[1], int(best_face.bbox[2]))
                         ]),
                         pose_weight(best_face.kps) if best_face.kps is not None else 1.0,
                         int(best_face.width))
                save_this_frame = True

        if max_saves > 0 and saved >= max_saves:
            log.info("Reached max_saves=%d. Done.", max_saves)
            break

        # ── Preview ──────────────────────────────────────────────────────
        if show_preview:
            if save_this_frame:
                # Flash green border on save
                cv2.rectangle(display, (0, 0), (display.shape[1]-1, display.shape[0]-1),
                              _GREEN, 6)
                _draw_label(display, f"SAVED ({saved})",
                            display.shape[1]//2 - 60, display.shape[0]//2,
                            _GREEN, scale=1.4, thickness=2)

            _overlay_hud(display, saved, max_saves, paused, fps)

            # Resize for display only (original is saved at full res)
            h, w = display.shape[:2]
            if w > 1280:
                scale  = 1280 / w
                display = cv2.resize(display, (1280, int(h * scale)))

            cv2.imshow("cam2_capture", display)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord('q'), ord('Q'), 27):   # Q or ESC
                log.info("Quit by user.")
                break
            elif key in (ord('s'), ord('S')):      # force save
                ts        = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename  = f"manual_{ts}_{camera_id}.jpg"
                save_path = output_dir / filename
                cv2.imwrite(str(save_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved    += 1
                last_save = now
                log.info("[MANUAL %d] Saved: %s", saved, save_path.name)
            elif key in (ord('p'), ord('P')):      # pause toggle
                paused = not paused
                log.info("%s", "Paused." if paused else "Resumed.")
        else:
            time.sleep(0.01)

    cap.release()
    if show_preview:
        cv2.destroyAllWindows()
    log.info("Capture complete. %d frames saved to: %s", saved, output_dir)
    log.info("Next steps:")
    log.info("  1. python apps/dataset_tools/extract_faces.py")
    log.info("  2. python apps/dataset_tools/build_gallery.py")
    log.info("  Then restart the pipeline to load the new gallery.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture frontal face frames from a camera stream for gallery building.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--camera",    default="camera_02",  help="Camera ID from cameras.yaml")
    parser.add_argument("--person",    default="unsorted",   help="Person name (creates subfolder in raw_frames)")
    parser.add_argument("--min-blur",  type=float, default=50.0,  help="Minimum Laplacian blur score")
    parser.add_argument("--min-pose",  type=float, default=0.50,  help="Minimum pose weight (0=profile, 1=frontal)")
    parser.add_argument("--min-size",  type=int,   default=80,    help="Minimum face width in pixels")
    parser.add_argument("--cooldown",  type=float, default=2.0,   help="Minimum seconds between auto-saves")
    parser.add_argument("--max",       type=int,   default=30,    help="Maximum frames to save (0=unlimited)")
    parser.add_argument("--no-preview", action="store_true",      help="Run headless (no display window)")
    args = parser.parse_args()

    config = load_config(
        "configs/default.yaml",
        "configs/thresholds.yaml",
        "configs/dataset.yaml",
    )

    dataset_cfg = config.get("dataset", {})
    raw_frames_root = Path(dataset_cfg.get("raw_frames", "dataset/raw_frames"))
    output_dir = raw_frames_root / args.person

    run_capture(
        camera_id   = args.camera,
        person      = args.person,
        output_dir  = output_dir,
        min_blur    = args.min_blur,
        min_pose    = args.min_pose,
        min_size    = args.min_size,
        cooldown    = args.cooldown,
        max_saves   = args.max,
        show_preview= not args.no_preview,
        config      = config,
    )


if __name__ == "__main__":
    main()
