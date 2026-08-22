# CDP production readiness

Status date: 2026-08-22. Decision: **BLOCKED — DO NOT PROMOTE**.

## Verified in this workspace

- The complete unit suite passes: 632 tests.
- The React/TypeScript HITL production build succeeds.
- Local-first OCR, adaptive registration, reference and deterministic evidence, fail-closed reconciliation, safe-STP policy, selective AI gateway controls, field-level HITL, versioned observability, Kubernetes/KEDA definitions, and scalability preflight are implemented.
- Current development evidence contains zero measured false accepts; no threshold was weakened to increase STP.

## Required before promotion

1. Freeze and run a separately sourced untouched holdout with independent truth.
2. Run incremental candidate experiments and demonstrate `<30%` HITL without critical-false-accept or critical-accuracy regression.
3. Qualify live OCR/cloud providers under approved PHI, region, cost, timeout, and audit policies.
4. Pass representative 1k/10k/50k-page cluster, 10x burst, soak, backpressure, autoscaling, and dependency-failure tests.
5. Complete security, identity, network-egress, retention, backup/restore, rollback, and disaster-recovery reviews and drills.
6. Obtain named operations, security, compliance, data-governance, and release approvals.

Implementation readiness is materially ahead of evidence readiness. Production promotion remains blocked because external data, infrastructure, and organizational approvals are unavailable in this workspace—not because a safety gate was bypassed.
