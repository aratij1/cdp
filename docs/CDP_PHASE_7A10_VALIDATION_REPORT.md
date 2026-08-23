# Phase 7A.10 — Multi-Source Hierarchical Routing Validation

Status: **NEEDS_MORE_DATA**.

The hierarchical baseline is frozen as `hierarchical-routing-baseline-v1.0.0`. Its manifest records the Git base SHA, exact source bundle/diff hashes, taxonomy version, CMS/UB verification policy versions, processing-route contract/policy versions, and corpus-builder version. The working tree is explicitly recorded as dirty relative to the base SHA, so the source bundle hash—not an inaccurate clean-tree claim—is the exact implementation identity.

Local corpus inventory found no eligible taxonomy corpus with independent reviewed source lineage. Existing renderer datasets, frozen A/B/C/D, and `VISUAL_SAFETY_DEV_V1` cannot satisfy this gate. Acquisition remains required. No LOSO numbers, candidate, frozen regression, or holdout result is claimed.

The evaluation now separates safety and efficiency:

- false standard authorization: non-standard truth reaches a fixed extractor;
- unverified fixed authorization: any fixed extractor route lacks matching VERIFIED evidence;
- standard-to-standard misroute: CMS reaches UB or UB reaches CMS;
- safe standard fallback: correctly nominated CMS/UB fails verification and reaches structured layout.

Frozen A/B/C/D remain unrun. `HIERARCHICAL_ROUTER_CANDIDATE_1` remains not created.
