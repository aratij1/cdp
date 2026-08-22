# CDP Router V3 Experiments

All experiments used synthetic development-only ROUTING_DEV_V3; no production
holdout page or label was used. EXP-R20 proved identity dependency. R21 added
weighted anchors. R22 added bounded normalized matching. R23 retained anchor
geometry. R24 added form structure and service-table evidence. R25 added
form-specific combinations. R26 centralized scoring and eligibility. R27
preserved structured unknowns. R28 placed V3 behind one canonical runtime
decision service with V2 rollback. R29 added 20 adversarial EOB-like negatives.

Before: CMS precision n/a, recall 0%; UB precision 100%, recall 75%; structured
recall 100%; non-claim accuracy 100%; false standards 0; P95 450 ms. After:
CMS and UB precision/recall 100%; structured and non-claim recall 100%; false
standards 0; P50 378 ms; P95 492 ms; one OCR call/document. Decision: PROMOTE
behind the disabled-by-default V3 feature flag.
