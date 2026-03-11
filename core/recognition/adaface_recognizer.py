import onnxruntime as ort
import numpy as np
import cv2
from .base_recognizer import BaseRecognizer

class AdaFaceRecognizer(BaseRecognizer):
    """AdaFace Recognition implementation using ONNX Runtime."""
    
    def __init__(self, config: dict, model_path: str):
        super().__init__(config)
        
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        if self.device == 'cpu':
            providers = ['CPUExecutionProvider']
            
        self.session = ort.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = (112, 112) # Standard AdaFace/ArcFace input size

    def _preprocess(self, face_img: np.ndarray) -> np.ndarray:
        # Resize to 112x112
        img = cv2.resize(face_img, self.input_shape)
        # BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # HWC to CHW
        img = img.transpose(2, 0, 1).astype(np.float32)
        # Normalize (0-255 to -1 to 1)
        img = (img - 127.5) / 128.0
        return np.expand_dims(img, axis=0)

    def extract_embedding(self, face_img: np.ndarray) -> np.ndarray:
        input_data = self._preprocess(face_img)
        outputs = self.session.run(None, {self.input_name: input_data})
        embedding = outputs[0][0]
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding
