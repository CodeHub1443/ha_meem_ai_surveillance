import os
import onnx
import json

# Resolve model path relative to this script
model_path = os.path.join(os.path.dirname(__file__), "..", "models", "exported", "adaface.onnx")
model_path = os.path.abspath(model_path)

print(f"Loading ONNX model from: {model_path}")
model = onnx.load(model_path)

# Print inputs and outputs
for inp in model.graph.input:
    print("INPUT:", inp.name)
for out in model.graph.output:
    print("OUTPUT:", out.name)

print("Nodes:", len(model.graph.node))
print("Initializers:", len(model.graph.initializer))

print("--- First 50 node op types ---")
for node in model.graph.node[:50]:
    print(node.op_type)

# Optional: attempt to infer backbone by residual block counts (simple heuristic)
# Count occurrences of "Add" nodes which often correspond to residual connections
add_counts = sum(1 for node in model.graph.node if node.op_type == "Add")
print(f"Add (residual) node count: {add_counts}")
