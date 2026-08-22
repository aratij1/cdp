# ML eligibility assist design

The experimental ML layer converts canonical, PHI-safe routing evidence into `MLEligibilityFeatures`, produces only `MLRouteEvidence`, and passes through `EligibilityFusionService`. Fusion requires deterministic corroboration; existing scoring, margin, safety and route-to-extractor contracts remain authoritative.

`ENABLE_ML_ELIGIBILITY` and `ENABLE_ML_ELIGIBILITY_SHADOW` default to false. Model loading validates feature order/version and SHA-256 and fails closed. Training dependencies are isolated under the `router-ml-training` optional dependency.

