# CDP Router Architecture Review

The pre-V3 production path was `DUAL_ROUTER_ARCHITECTURE`: trusted template
anchors could finalize first, reference grid/alignment could finalize second,
and `MultiSignalRouter` ran only as a fallback. It also collapsed
`UNKNOWN_STRUCTURED` into `D_UNSTRUCTURED`.

With `ENABLE_ROUTER_V3=true`, page OCR runs once and all anchor, geometry and
OpenCV structure signals enter `CanonicalRoutingDecisionService`. That service
alone emits `CMS1500`, `UB04`, `UNKNOWN_STRUCTURED`, `UNKNOWN_UNSTRUCTURED`, or
`NON_CLAIM`. V2 remains available through `ENABLE_ROUTER_V2` for rollback.

The identity audit proved `IDENTITY_ANCHOR_DEPENDENCY_DEFECT`: the old maximum
standard score without identity was 0.55, below the 0.60 global threshold.
V3 keeps identity as positive evidence and adds a separately gated structural
eligibility path. No OCR engine was added; runtime and evaluation use one
Tesseract pass plus OpenCV features.
