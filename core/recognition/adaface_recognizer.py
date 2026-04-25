import cv2
import numpy as np
import onnxruntime as ort
from typing import List

from .base_recognizer import BaseRecognizer


class AdaFaceRecognizer(BaseRecognizer):
    """AdaFace recognition via ONNX Runtime.

    Supports both single-image and batched inference.  Batching is attempted
    first; if the ONNX model was exported with a fixed batch size of 1 the
    session.run() call will raise, and we fall back to sequential processing
    transparently.
    """

    def __init__(self, config: dict, model_path: str):
        super().__init__(config)
        providers = (
            ["CPUExecutionProvider"]
            if self.device == "cpu"
            else ["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        # Suppress ORT shape-mismatch warnings that fire when sending batch>1
        # to a model exported with static batch_size=1.
        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3  # 3 = ERROR only; suppress WARNING (2)
        self.session = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = (112, 112)

        # Detect whether the model supports dynamic batching.
        # ONNX models exported with a fixed batch dim (integer > 0, not None/-1)
        # will warn on every batch>1 call. In that case we fall back to
        # sequential inference to keep the log clean.
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
            except Exception:
                pass  # fall through to sequential

        # Sequential path — safe for any model export
        embeddings = np.stack(
            [self.session.run(None, {self.input_name: self._preprocess_one(img)})[0][0]
             for img in face_imgs]
        )
        return self._l2_normalize(embeddings)
