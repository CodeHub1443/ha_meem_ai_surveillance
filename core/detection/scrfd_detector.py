import os
import cv2
import numpy as np
import onnxruntime as ort
from typing import List
from .base_detector import BaseDetector
from .face import Face

class SCRFDDetector(BaseDetector):
    """SCRFD Face Detector implementation using ONNX Runtime."""
    
    def __init__(self, config: dict, model_path: str):
        super().__init__(config)
        import insightface
        from insightface.model_zoo import get_model
        
        # insightface expects the file to exist, it doesn't need providers passed manually 
        # as it handles it internally via the context.
        self.detector = get_model(model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.detector.prepare(ctx_id=0 if self.device == 'cuda' else -1, input_size=(640, 640))

    def detect(self, image: np.ndarray) -> List[Face]:
        """Runs inference using insightface and returns Face objects."""
        # insightface internal detect returns (bboxes, kps)
        bboxes, kps = self.detector.detect(image)
        
        faces = []
        if bboxes is not None:
            for i in range(bboxes.shape[0]):
                # bbox is [x1, y1, x2, y2, score]
                face = Face(
                    bbox=bboxes[i],
                    kps=kps[i] if kps is not None else None
                )
                faces.append(face)
        
        return faces
