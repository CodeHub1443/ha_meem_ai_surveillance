import os
import cv2
import numpy as np
import yaml
import sys
from pathlib import Path

# Ensure we can import from the core module if run as a script
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from core.detection import SCRFDDetector
from core.utils.image import align_face


def apply_clahe(frame: np.ndarray) -> np.ndarray:
    """Improve local contrast via CLAHE on the L channel (LAB colour space).

    Lifts underexposed faces (dark skin / poor lighting) without
    overexposing already-bright regions.  Applied to the full frame
    before detection so SCRFD and the aligner both see better contrast.
    """
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)


def load_config():
    """Load and merge configuration files identically to main pipeline."""
    def _read_yaml(path):
        if not os.path.exists(path):
            return {}
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    
    config = _read_yaml('configs/default.yaml')
    thresholds = _read_yaml('configs/thresholds.yaml')
    dataset = _read_yaml('configs/dataset.yaml')
    
    config.update(thresholds)
    if dataset:
        if 'dataset' in config:
            config['dataset'].update(dataset.get('dataset', {}))
        else:
            config.update(dataset)
            
    return config

def main():
    # Load settings
    config = load_config()
    
    # Paths according to requirements or config
    dataset_cfg = config.get('dataset', {})
    input_dir = Path(dataset_cfg.get('raw_frames', 'dataset/raw_frames'))
    output_dir = Path(dataset_cfg.get('aligned_faces', 'dataset/aligned_faces'))
    
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

    # Process each person subdirectory or individual files
    print(f"Starting dataset extraction...")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print("-" * 40)

    # Collect work items: (person_name, list_of_images)
    work_items = {}
    
    for item in sorted(input_dir.iterdir()):
        if item.is_dir():
            person_name = item.name
            work_items[person_name] = [img for img in item.iterdir() if img.suffix.lower() in ['.jpg', '.jpeg', '.png']]
        elif item.is_file() and item.suffix.lower() in ['.jpg', '.jpeg', '.png']:
            # Infer person name from filename: e.g. "albid_1.jpg" -> "albid"
            person_name = item.stem.split('_')[0].split(' (')[0]
            if person_name not in work_items:
                work_items[person_name] = []
            work_items[person_name].append(item)

    for person_name, images in work_items.items():
        if not images:
            continue
            
        persons_count += 1
        
        # Mirror structure in output
        person_output_dir = output_dir / person_name
        person_output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Processing: {person_name} ({len(images)} images)")
        
        # Process files in person folder
        for img_path in images:
                
            frame = cv2.imread(str(img_path))
            if frame is None:
                continue

            frame = apply_clahe(frame)

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
                
                raw = frame[y1:y2, x1:x2]
                if raw.size == 0:
                    continue
                if face.kps is not None:
                    face_crop = align_face(frame, face.kps, crop=raw)
                else:
                    face_crop = cv2.resize(raw, (112, 112))

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
