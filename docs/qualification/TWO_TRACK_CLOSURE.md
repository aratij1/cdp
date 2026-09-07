# CDP two-track measured closure

Track A uses the 30 owner-confirmed claims and the frozen current candidate `71c184b3`. Its authority is **ENGINEERING_REFERENCE_ONLY**. Track B retains its separate candidate and immutable 150-page cohort. No denominators are shared.

| Engineering metric | Numerator | Denominator | Percentage | Status |
|---|---:|---:|---:|---|
| raw_accuracy | 1 | 124 | 0.8065% | MEASURED |
| critical_accuracy | 1 | 86 | 1.1628% | MEASURED |
| accepted_precision | 0 | 0 | NOT_EVALUABLE | NOT_EVALUABLE |
| critical_accepted_precision | 0 | 0 | NOT_EVALUABLE | NOT_EVALUABLE |
| critical_false_accepts | 0 | 0 | NOT_EVALUABLE | NOT_EVALUABLE |
| field_hitl | NOT_EVALUABLE | 124 | NOT_EVALUABLE | NOT_EVALUABLE |
| claim_hitl | 30 | 30 | 100.0000% | MEASURED |
| true_stp | 0 | 30 | 0.0000% | MEASURED |

All 30 claim attempts remain included: 29 reached extraction and one explicitly routed to review because page selection was ambiguous. The run prepared all 67 frames. It persisted 62 extracted fields and 62 HITL tasks. Seven empty extractions became canonical NEEDS_REVIEW states; 22 claims reached canonical decisions, followed by output errors (`OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`). No safe output completed. These are measured failures, not omitted claims.

The deterministic reference adapter found 124 available instances, 30 unavailable, 72 not comparable and 14 ambiguous across the eight target fields. It does not turn DATAMATICS outputs into human truth. Dates with unspecified formats and incompatible provider/diagnosis roles remain excluded. The current C2/C3 policy identifies 86 eligible critical instances. Missing candidates count wrong; conflicting occurrences cannot select whichever matches.

Field HITL cannot be reported as a complete rate: 16 eligible instances have explicit routing and 108 have unknown routing. The 12.90%-100% interval is only a bound. There are no eligible auto-accepted fields, so accepted precision and a false-accept rate remain unavailable.

## Execution and revalidation evidence

Production ingestion, preparation, routing, OCR, validation, retry/HITL and output worker handlers ran unchanged using local immutable object storage and a durable SQLite transactional outbox. Transport was in-process; this is not a target-host deployment attestation. A missing Python 3.12 interpreter and Tesseract binary were restored locally. No OCR configuration, extraction logic or threshold was tuned.

The raw snapshot was sealed before reference-driven correction. A separate SQLite copy exercised 15 reference injections through HUMAN_CONFIRMED, validation PENDING, 15 transactional revalidation requests and 15 canonical decisions. Zero validations remained pending afterward. All 15 outputs were blocked by the same existing output error. This is REVALIDATION_TEST, with zero actual human reviews. A positive safe-output path was not exercised.

## Independent blind cohort

All 150 source-container/frame relationships were recovered from the cohort's own lineage; no governed claim boundaries were recovered. The generated `evaluation_results/real_release/150_cohort_missing_membership.csv` contains aliases and frame numbers, with a private ignored lookup. The watcher preserves owner edits. Source and normalized pixel hashes have zero overlap with Track A; package and known-identity comparisons also have zero overlap. Blind claim identities are still unknown.

The original package reservation marks 47 pages HOLDOUT and 103 DEVELOPMENT. Preliminary field scoring honors those reservations, exact source binding, independent review finalization and canonical prediction/deployment provenance. It does not wait for claim membership. Current reviewed pages and trusted fields are both zero; all blind metrics remain NOT_EVALUABLE. Final release truth and claim metrics retain their stronger membership and leakage gates.

The existing watcher refreshes engineering reports and preliminary blind field reports automatically and withdraws them if source, raw-capture or isolation seals fail. It does not rerun extraction or overwrite frozen predictions. The blind review UI remains at http://127.0.0.1:8094/qualification-review/.

Validation: 1,826 unit/architecture/golden tests passed, plus the final 16-test
scorecard check. Ruff and scoped mypy passed. No new semantic regressions; golden
fixed-width outputs remain unchanged.

## Export and next action

Repository export policy (`docs/CDP_CLOSURE_STATUS.md`) permits code, synthetic tests and PHI-safe aggregate documentation. Detailed claim/source manifests, semantic hashes, reference values, execution traces, failure rows and the owner confirmation CSV remain ignored/local. Only aggregate results are included here.

Next action: Ashish Singh completes the aliased `150_cohort_missing_membership.csv` confirmation request.
