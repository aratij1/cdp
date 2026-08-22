# Source-invariant visual evidence design

The evaluation-only visual path uses a 224×224 grayscale HOG page embedding and balanced logistic classifier. It is CPU-only, local, approximately 35 KB, and produces only `VisualRouteEvidence`. It cannot finalize routes or dispatch extractors. `ENABLE_VISUAL_EVIDENCE` and shadow mode default to false.

This baseline was chosen instead of adding a GPU/native neural runtime after the feature-sufficiency prerequisite weakened the visual hypothesis. No VLM, cloud API, OCR, Gemini or production path was added.

