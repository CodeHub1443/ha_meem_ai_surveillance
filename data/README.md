# Data Management

Large datasets are not stored within this repository to maintain performance and cleanliness.

## External Dataset Reference

Datasets must live outside the repository and be referenced through the configuration system.

1. Store your raw frames and aligned faces in an external directory.
2. Update the paths in `configs/dataset.yaml` to point to your local data locations.

## Expected Structure
The system expects the following structure at the configured paths:

```text
raw_frames/
    Person_A/
        001.jpg
    Person_B/
        001.jpg

aligned_faces/
    Person_A/
        crop_001.jpg
```
