# HA-MEEM AI Surveillance — Agent Context

## Project Objective
Build a production-grade, real-time face recognition system for entry-zone CCTV in factory environment.

PoC: 1–2 cameras  
Production target: 20 cameras  

Primary goal:
Reliable Authorized / Unknown classification at entry gate.

---

## Operational Constraints

- Workers do NOT intentionally pause
- Workers do NOT intentionally look at camera
- Camera tilt: 15°–25°
- Real-world blur and partial occlusion expected
- Face must be ≥140px width to qualify for recognition
- Single-frame recognition is forbidden
- Multi-frame fusion is mandatory

---

## Technical Stack

OS: Windows  
Framework: PyTorch 2.5.1 + CUDA 12.1  
Optimization: TensorRT 10.12  
Experiment Tracking: ClearML  
Version Control: GitHub  
IDE: Google Antigravity (Agentic AI IDE)

---

## System Design Principles

1. Modular architecture (no monolithic scripts)
2. Separation of concerns:
   - core/ → CV logic only
   - apps/ → runtime pipeline
   - experiments/ → research & training
3. Config-driven system (no hardcoded thresholds)
4. Production stability > academic novelty
5. No GAN-based frontalization
6. No super-resolution for FR
7. No heavy transformers unless justified by measured failure

---

## Recognition Pipeline (PoC)

Face Detection: SCRFD  
Recognition Model: AdaFace (pretrained baseline)  
Embedding: 512-d normalized  
Matching: Cosine similarity  
Decision: Track-level aggregated embedding  
Threshold: Configurable  

Resolution gate:
- Reject face < 140px width
- Reject blurry frames

---

## Future Integration

CV core must remain framework-agnostic.

FastAPI or message service will consume structured JSON output.
Do NOT introduce API dependencies into core/.

---

## Code Rules for Agent

- Always create small, single-responsibility classes
- Use type hints
- Use config files for thresholds and paths
- Never hardcode model paths
- Never commit model weights
- Write testable components
- Avoid hidden global state

---

## Definition of Done (PoC)

- Stable multi-frame fusion
- FAR < 2%
- FRR < 5%
- Real-time performance sustained
- Clean logs per entry event