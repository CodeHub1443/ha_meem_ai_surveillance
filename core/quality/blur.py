import cv2
import numpy as np

def calculate_blur_score(image: np.ndarray) -> float:
    """Calculates the focus measure using the Variance of Laplacian.
    
    Args:
        image: BGR or Grayscale image.
        
    Returns:
        float: Blur score (higher means sharper).
    """
    if image is None or image.size == 0:
        return 0.0
    
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else: gray = image
        
    return cv2.Laplacian(gray, cv2.CV_64F).var()
