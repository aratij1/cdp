# Engineering Holdout V1 Baseline

## Qualification

`PRODUCTION_HOLDOUT_V1_SYNTHETIC` is registered as a frozen engineering
holdout. Its own manifest and attestation identify it as synthetic, without
real PHI, and without production-promotion authority. The source hashes were
verified, 500/500 document hashes matched, and no exact image overlap with the
development corpora was found. It must not be presented as real production
evidence.

The archive also omits `UB04.federal_tax_no` ground truth. Consequently it
cannot qualify the complete claim-level STP policy even as engineering
evidence.

## Untouched baseline

Inference retained only `document_id` and `path` from the index. Family,
quality, and ground-truth values were not loaded until predictions had been
persisted. The run used the live preparation, page-routing, standard regional
OCR, and Bundle-D family-routing components without changing their thresholds
or configurations.

| Measure | Result |
|---|---:|
| Documents | 500 |
| Canonical field observations | 1,988 |
| Exact raw accuracy | 0.00% (0/1,988) |
| Bundle-D routes | 100.00% (500/500) |
| Mean wall time/document | 0.890 s |
| P95 wall time/document | 1.304 s |
| Mean CPU time/document | 0.154 s |

All CMS-like and UB-like pages fell through to Bundle D. The configured
Bundle-D families do not describe these simplified layouts, so no governed
claim fields were emitted. This is primarily a format-coverage/routing gap,
not evidence that lowering acceptance thresholds would be safe.

Safe accuracy, field HITL, claim STP, and claim HITL are deliberately not
reported as qualified values: the unchanged path emitted no canonical field
decisions, and the archive lacks one required UB policy field. Operationally,
these documents must remain review-bound until a supported route is promoted.

Machine-readable evidence is under
`evaluation_results/production_readiness/engineering_holdout_v1_synthetic/`.
No tuning was performed against this frozen holdout.
