# Ha-Meem AI Surveillance

A professional-grade AI surveillance system for real-time inference and data management.

## Structure

- `apps/`: High-level applications (inference pipeline, dataset tools).
- `core/`: Core AI modules (detection, recognition, tracking, fusion, quality).
- `models/`: Model storage and exported ONNX/TensorRT engines.
- `configs/`: Configuration for models, cameras, and thresholds.
- `experiments/`: Research and experiment scripts.
- `tests/`: Testing suite.
- `docker/`: Deployment configurations.
- `requirements/`: Python dependencies.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements/base.txt
   ```
2. Configure cameras in `configs/cameras.yaml`.
3. Run the application:
   - **One command (Recommended):**
     ```bash
     npm start
     ```
     *This runs both backend and frontend in one terminal window.*
   - **Separate windows:**
     ```bash
     .\start_all.ps1
     ```
