import os
import sys
import logging
import cv2
import numpy as np
import onnxruntime as ort
from typing import List

from .base_recognizer import BaseRecognizer

# Windows: TensorRT pip package puts its DLLs in a non-standard location.
# Prepend tensorrt_libs to PATH before onnxruntime loads its providers.
if sys.platform == "win32":
    _trt_lib_dir = os.path.normpath(
        os.path.join(os.path.dirname(sys.executable), "..", "lib", "site-packages", "tensorrt_libs")
    )
    if os.path.isdir(_trt_lib_dir) and _trt_lib_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _trt_lib_dir + os.pathsep + os.environ.get("PATH", "")

log = logging.getLogger(__name__)


class AdaFaceRecognizer(BaseRecognizer):
    """AdaFace recognition via ONNX Runtime.

    Supports both single-image and batched inference.  Batching is attempted
    first; if the ONNX model was exported with a fixed batch size of 1 the
    session.run() call will raise, and we fall back to sequential processing
    transparently.

    When ``config["tensorrt"]["enabled"]`` is true and device is cuda,
    TensorRT Execution Provider is prepended — FP16 engine is compiled on first
    run (~60-120 s) then loaded from disk cache on subsequent runs (~10 ms).
    Falls back to CUDAExecutionProvider if TRT is disabled or unavailable.
    """

    def __init__(self, config: dict, model_path: str):
        super().__init__(config)

        trt_cfg = config.get("tensorrt", {})

        if self.device == "cpu":
            providers = ["CPUExecutionProvider"]
        else:
            providers = []
            if trt_cfg.get("enabled", False):
                cache_path = trt_cfg.get("engine_cache_path", "./trt_cache")
                os.makedirs(cache_path, exist_ok=True)
                trt_opts = {
                    "trt_fp16_enable": trt_cfg.get("fp16", True),
                    "trt_engine_cache_enable": trt_cfg.get("engine_cache_enable", True),
                    "trt_engine_cache_path": cache_path,
                    "trt_max_workspace_size": trt_cfg.get("max_workspace_size", 1073741824),
                    "trt_dla_enable": trt_cfg.get("dla_enable", False),
                }
                providers.append(("TensorrtExecutionProvider", trt_opts))
            providers.append(("CUDAExecutionProvider", {"device_id": 0}))
            providers.append("CPUExecutionProvider")

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3  # ERROR only; suppress WARNING (2)
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        n_threads = config.get("models", {}).get("ort_intra_threads", 2)
        sess_opts.intra_op_num_threads = n_threads
        self.session = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = (112, 112)

        active = self.session.get_providers()
        if "TensorrtExecutionProvider" in active:
            log.info("AdaFaceRecognizer: TensorRT backend ACTIVE (FP16=%s, cache=%s)",
                     trt_cfg.get("fp16", True), trt_cfg.get("engine_cache_path", "./trt_cache"))
        elif "CUDAExecutionProvider" in active:
            log.info("AdaFaceRecognizer: CUDA backend active (TensorRT not available — install tensorrt-cu12)")
        else:
            log.info("AdaFaceRecognizer: CPU backend active")
        log.debug("AdaFaceRecognizer full provider list: %s", active)

        # Detect whether the model supports dynamic batching.
        # Fixed batch_size=1 models warn on every batch>1 call — use sequential path instead.
        batch_dim = self.session.get_inputs()[0].shape[0]
        self._dynamic_batch: bool = not (isinstance(batch_dim, int) and batch_dim > 0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _preprocess_one(self, face_img: np.ndarray) -> np.ndarray:
        """Returns (1, 3, 112, 112) float32 tensor for a single face crop."""
        img = cv2.resize(face_img, self.input_shape)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.transpose(2, 0, 1).astype(np.float32)
        img = (img - 127.5) / 128.0
        return np.expand_dims(img, axis=0)

    @staticmethod
    def _l2_normalize(embeddings: np.ndarray) -> np.ndarray:
        """Row-wise L2 normalisation; safe against zero vectors."""
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1.0)
        return embeddings / norms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_embedding(self, face_img: np.ndarray) -> np.ndarray:
        """Extract a single normalised 512-d embedding."""
        inp = self._preprocess_one(face_img)
        outputs = self.session.run(None, {self.input_name: inp})
        embedding = outputs[0][0]
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else embedding

    def extract_embeddings_batch(self, face_imgs: List[np.ndarray]) -> np.ndarray:
        """Extract normalised embeddings for a list of face crops.

        Uses a single batched ONNX call when the model supports dynamic batch
        sizes.  Falls back to sequential inference for models exported with a
        fixed batch size of 1 (avoids ONNX Runtime shape-mismatch warnings).

        Returns:
            np.ndarray of shape (N, 512), L2-normalised rows.
        """
        if not face_imgs:
            return np.empty((0, 512), dtype=np.float32)

        if self._dynamic_batch and len(face_imgs) > 1:
            batch = np.concatenate(
                [self._preprocess_one(img) for img in face_imgs], axis=0
            )
            try:
                embeddings = self.session.run(None, {self.input_name: batch})[0]
                return self._l2_normalize(embeddings)
            except Exception as _e:
                log.debug("Batch inference fell back to sequential: %s", _e)

        # Sequential path — safe for any model export and fixed TRT engine shapes
        embeddings = np.stack(
            [self.session.run(None, {self.input_name: self._preprocess_one(img)})[0][0]
             for img in face_imgs]
        )
        return self._l2_normalize(embeddings)
