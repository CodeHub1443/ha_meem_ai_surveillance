import os
import cv2
import yaml
import sys
from pathlib import Path

# Ensure we can import from the core module if run as a script
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from core.detection import SCRFDDetector

def load_config():
    """Load and merge configuration files identically to main pipeline."""
    def _read_yaml(path):
        if not os.path.exists(path):
            return {}
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    
    config = _read_yaml('configs/default.yaml')
    thresholds = _read_yaml('configs/thresholds.yaml')
    config.update(thresholds)
    return config

def main():
    # Load settings
    config = load_config()
    
    # Paths according to requirements
    input_dir = Path('dataset/raw_frames')
    output_dir = Path('dataset/aligned_faces')
    
    # Create base output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    if 'models' not in config or 'scrfd_onnx' not in config['models']:
        print("Error: Model path not found in config.")
        return
        
    detector = SCRFDDetector(config, config['models']['scrfd_onnx'])
    min_face_size = config.get('recognition', {}).get('min_face_size', 140)
    
    # Statistics
    persons_count = 0
    extracted_count = 0
    rejected_count = 0
    
    if not input_dir.exists():
        print(f"Error: Input folder '{input_dir}' does not exist.")
        return

    print(f"Starting dataset extraction...")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print("-" * 40)

    # Process each person subdirectory
    for person_path in sorted(input_dir.iterdir()):
        if not person_path.is_dir():
            continue
            
        persons_count += 1
        person_name = person_path.name
        
        # Mirror structure in output
        person_output_dir = output_dir / person_name
        person_output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Processing: {person_name}")
        
        # Process files in person folder
        for img_path in person_path.iterdir():
            if img_path.suffix.lower() not in ['.jpg', '.jpeg', '.png']:
                continue
                
            frame = cv2.imread(str(img_path))
            if frame is None:
                continue
                
            # Detect faces using SCRFD
            faces = detector.detect(frame)
            
            for i, face in enumerate(faces):
                # Requirement: reject faces < config['recognition']['min_face_size']
                if face.width < min_face_size:
                    rejected_count += 1
                    continue
                
                # Crop face region
                x1, y1, x2, y2 = face.bbox[:4].astype(int)
                
                # Maintain image bounds
                h, w = frame.shape[:2]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                face_crop = frame[y1:y2, x1:x2]
                
                if face_crop.size == 0:
                    continue
                
                # Save cropped face
                # Mirroring naming or appending index if multiple faces found
                save_path = person_output_dir / f"{img_path.stem}_{i:03d}.jpg"
                cv2.imwrite(str(save_path), face_crop)
                extracted_count += 1

    # Print summary as requested
    print("-" * 40)
    print("Extraction Summary:")
    print(f"Persons processed: {persons_count}")
    print(f"Faces extracted:   {extracted_count}")
    print(f"Faces rejected:    {rejected_count} (too small)")
    print("-" * 40)

if __name__ == "__main__":
    main()
