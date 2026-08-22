# CDP Evidence Frontier Regression

## Result

The Phase 3 full repository regression passed after the claim-decision, claim-evidence, E4, E2-normalization, worker, evaluation, and output changes.

| Scope | Result |
|---|---:|
| Full collected suite | 716 passed |
| External-stack ingestion tests | 5 skipped |
| Warnings | 1 |
| Duration | 76.67 seconds |

Command:

```text
.venv/Scripts/python.exe -m pytest -q -rs --basetemp test-artifacts/pytest-claim-phase3-full
```

The five skipped tests are `tests/integration/test_ingestion_pipeline.py` at lines 54, 61, 84, 101, and 110. They require the ingestion API at `:8000`; it was unreachable. These tests are recorded as **not run**, not as passes. Unit tests, non-external integration tests, architecture/policy tests, OCR/evidence tests, retry/worker tests, output tests, and claim-finalization tests completed in the collected suite.

The single warning is the installed FastAPI/Starlette `TestClient` dependency deprecation for its current `httpx` integration. It is not a test failure.

## Frozen extraction gates

`EXTRACTION_BASELINE_V1` remains unchanged at:

| Metric | Measured | Gate | Result |
|---|---:|---:|---|
| Overall raw extraction accuracy | 99.00% (594/600) | >=98.50% | pass |
| CMS-1500 raw accuracy | 98.33% | >=97.50% | pass |
| UB-04 raw accuracy | 99.44% | >=98.50% | pass |
| Critical-field raw accuracy | 99.05% | >=98.50% | pass |

The Phase 3 replay did not change raw extraction values. It changed only evidence validation, agreement canonicalization, and claim disposition.

## Frozen evidence frontier gates

`EVIDENCE_FRONTIER_V1` contains all 600 field dispositions and all 120 canonical claim dispositions.

| Metric | Measured | Gate/target | Result |
|---|---:|---:|---|
| Safe field coverage | 85.83% (515/600) | >=75.00% | pass |
| Field HITL/unresolved rate | 14.17% (85/600) | <=25.00% | pass |
| Claim STP | 80.00% (96/120) | >70.00% | pass |
| Claim HITL | 20.00% (24/120) | <30.00% | pass |
| False accepts | 0 | 0 preferred | pass |
| Critical false accepts | 0 | 0 | pass |

These are corrected synthetic evaluation-frontier results. All non-member confirmation routes are `EVALUATION_ONLY` and are rejected by runtime routing. Therefore the table is not a production STP or accuracy claim.

The frozen machine-readable artifacts are under `evaluation_results/claim_stp_recovery/baseline/`. Normal analysis reruns write to `current/` and cannot replace either frozen baseline without an explicit replacement flag.
