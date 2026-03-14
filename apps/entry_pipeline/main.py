import cv2
import yaml
import time
import os
import numpy as np

from core.events import EventEmitter, SnapshotWriter
from core.detection import SCRFDDetector, Face
from core.tracking import IOUTracker
from core.recognition import AdaFaceRecognizer
from core.fusion import EmbeddingAggregator
from core.quality import calculate_blur_score
from core.database import FaceDatabase


def load_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def run_pipeline():
    # Load configs
    default_cfg = load_config('configs/default.yaml')
    camera_cfg = load_config('configs/cameras.yaml')
    threshold_cfg = load_config('configs/thresholds.yaml')
    
    # Merge configs
    config = {**default_cfg, **threshold_cfg}
    
    # Initialize components
    # Note: Paths are placeholders as weights aren't committed
    detector = SCRFDDetector(config, config['models']['scrfd_onnx'])
    tracker = IOUTracker(iou_threshold=0.3)
    recognizer = AdaFaceRecognizer(config, config['models']['adaface_onnx'])
    aggregator = EmbeddingAggregator(
        buffer_size=10, 
        min_frames=config['recognition']['min_frames_for_decision']
    )
    
    dataset_cfg = load_config('configs/dataset.yaml')

    gallery_path = dataset_cfg['dataset']['gallery_embeddings']

    gallery_embeddings = np.load(gallery_path, allow_pickle=True).item()

    face_db = FaceDatabase(gallery_embeddings)
    
    # Open camera (using camera_01 from config)
    cap = cv2.VideoCapture(camera_cfg['cameras'][0]['url'])
    
    event_emitter = EventEmitter(
        camera_id="cam_01",
        log_file="logs/events.jsonl"
    )
    
    snapshot_writer = SnapshotWriter(
        base_dir="snapshots",
        camera_id="cam_01"
    )
    
    decided_tracks = set()
    
    # Cooldown mechanism for authorized identities
    identity_last_seen = {}
    identity_cooldown_seconds = 6
    
    print("Starting AI Surveillance Pipeline...")
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        start_time = time.time()
        
        # 1. Detection
        faces = detector.detect(frame)
        
        # 2. Tracking
        tracked_faces = tracker.update(faces)
        
        active_track_ids = set(face.track_id for face in tracked_faces)
        for track_id in list(aggregator.track_buffers.keys()):
            if track_id not in active_track_ids:
                del aggregator.track_buffers[track_id]
                decided_tracks.discard(track_id)
                
        for face in tracked_faces:
            # Operational Constraints: Resolution Gate
            if face.width < config['recognition']['min_face_size']:
                continue
                
            # Blur Rejection
            x1, y1, x2, y2 = face.bbox[:4].astype(int)
            face_img = frame[max(0, y1):y2, max(0, x1):x2]
            
            face.blur_score = calculate_blur_score(face_img)
            if face.blur_score < config['recognition']['blur_threshold']: # Threshold should be in config
                continue
                
            # 3. Recognition (Feature Extraction)
            face.embedding = recognizer.extract_embedding(face_img)
            
            # 4. Fusion (Aggregation)
            aggregator.add_face(face)
            
            # Get consensus
            consensus_emb = aggregator.get_aggregated_embedding(face.track_id)
            
            if consensus_emb is not None and face.track_id not in decided_tracks:
                identity, score = face_db.match(
                    consensus_emb, 
                    config['recognition']['similarity_threshold']
                )
                
                current_time = time.time()
                
                event_emitted = False
                
                if identity is not None:
                    last_seen = identity_last_seen.get(identity, 0)
                    
                    if current_time - last_seen >= identity_cooldown_seconds:
                        print(f"Authorized: {identity} ({score:.3f})")
                        snapshot_path = snapshot_writer.save(frame, identity)
                        event_emitter.emit_authorized(face.track_id, identity, score, snapshot_path)
                        identity_last_seen[identity] = current_time
                        event_emitted = True
                else:
                    print(f"Unknown ({score:.3f})")
                    snapshot_path = snapshot_writer.save(frame, None)
                    event_emitter.emit_unknown(face.track_id, score, snapshot_path)
                    event_emitted = True
                
                if event_emitted:
                    decided_tracks.add(face.track_id)
            
            # 5. Visualization (Simplified)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"ID: {face.track_id}", (x1, y1 - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # Performance Logging
        fps = 1.0 / (time.time() - start_time)
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
        
        cv2.imshow('Ha-Meem AI Surveillance', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_pipeline()
