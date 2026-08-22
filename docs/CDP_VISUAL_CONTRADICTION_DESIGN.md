# Visual Contradiction Design

`VisualContradictionService` consumes frozen `VisualRouteEvidence` and already-computed deterministic `RoutingEvidence`. It performs no OCR, CV, model inference, routing, or extractor selection. A standard proposal is vetoed only by at least two independent hard contradiction classes, or by the paired low-margin/high-entropy uncertainty rule in VC-05. Missing evidence alone is not a contradiction. CMS and UB are treated symmetrically through opposing structure, anchors, and geometry; UB additionally uses existing service-table evidence.

The result is `StandardContradictionEvidence`, not `RouteDecision`. Runtime flags remain disabled and evaluation-only.
