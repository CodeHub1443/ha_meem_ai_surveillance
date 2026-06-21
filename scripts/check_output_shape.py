import os
import onnx

# Load the AdaFace ONNX model (relative to repo root)
model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "exported", "adaface.onnx"))
print(f"Loading model from: {model_path}")
model = onnx.load(model_path)

print("--- Output tensor shapes ---")
for out in model.graph.output:
    # Directly print the shape protobuf (will show dimensions)
    print(out.type.tensor_type.shape)
