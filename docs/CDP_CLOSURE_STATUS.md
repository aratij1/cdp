# CDP closure iteration 4

Status: **CONTINUE**. The four identified anchor misses now have source-bound review candidates. Release qualification and production authority are unchanged.

## Candidate experiment

Three long damaged labels are matched only as whole registry labels, within two edits, with a second literal registry boundary corroborating the row. These matches produce **WEAK_LABEL_DISCOVERY**, retain observed value characters and source provenance, and have unknown anchor confidence. They cannot establish extraction support or enter the bounded recovery selection policy. Weak duplicates cannot replace or contaminate literal candidates.

Compound printed labels are exact only when every component names the same registry field. This addresses a compound diagnosis label, a distinct trigger from the earlier rejected expansion of diagnosis discovery. No OCR character in a candidate value is replaced, deleted or inferred. Approximate matching does not confirm form identity and is confined to noncanonical discovery.

| Metric, fixed 200 fields / 20 claims | Iteration 3 | Iteration 4 |
|---|---:|---:|
| Exact missing candidates | 24 | 22 |
| Governed missing candidates | 15 | 11 |
| Exact candidate Recall@1 / @3 / @5 | 68.5% / 88% / 88% | 69% / 89% / 89% |
| Governed candidate Recall@1 / @3 / @5 | 85% / 92.5% / 92.5% | 86.5% / 94.5% / 94.5% |
| C3 candidate Recall@5, 30 fields | 100% | 100% |
| Correct selected values under governed comparison | 166 | 166 |
| Technical blockers | 71 | 71 |
| Technical review fields | 29 | 29 |
| Technical-STP-capable claims | 14/20 | 14/20 |

Two recoveries preserve compact name tokens and therefore improve governed recall without exact-string recovery. Candidate Recall@1 counts the first available candidate; it is distinct from actual selected-value correctness when selection abstains. No existing covered reference or correct selected value regressed. All four improvements remain engineering evidence.

## Claim closure and external evidence

The six blocked claims retain distances 1, 3, 14, 16, 17 and 20. Their detailed matrices were regenerated locally. New weak candidates do not clear technical blockers. The obscured distance-one provider and contaminated distance-three date, bill-type and diagnosis observations remain unresolved. No source completion or reference-driven crop was invented.

Technical-STP capability remains 14/20 (70%). For those 14 claims, the prior separate external requirements remain: 14 member-authority, 14 provider-authority, 21 patient/insured-identity and 56 source-evidence field requirements, plus a release-qualification gap on every claim. Across the full 200 fields, technical review is 14.5%, external review 77%, and their union 77.5%. These are frozen engineering observations, not production HITL.

## Same 100 real pages

Candidate-bearing pages increased from **46 to 48**; alternatives from **85 to 87**. Current candidate-bearing field pairs: 78; ambiguous pairs: seven; no-candidate pages: 52. The cohort and source evidence are unchanged. Every blind-review package remains excluded.

This cached replay made zero new full-page/regional OCR calls and zero LLM/VLM calls. OTHER/UNKNOWN canonical localization remains zero. Runtime and sampled RSS are recorded in the aggregate JSON; this replay excludes fresh OCR and full claim processing. Coverage is not accuracy.

## Performance experiment

The new bounded experiment reduced OpenCV's thread pool from 16 to one, leaving ONNX at eight threads and keeping the same 12 pages, models, arena, batch and process model. The pilot preserved all five semantic comparisons but measured P95 **11.770s**, versus 5.573s in the retained comparison run. It was rejected, and no runtime option or experimental implementation was retained.

The prior retained three-run P95 measurements remain 6.00s, 5.58s and 5.57s, median **5.58s**, P50 4.21s, throughput 0.253 pages/s and maximum sampled RSS 1.41 GB. These are prior measurements, not new iteration-four repetitions. The fresh harness covers OCR, routing and spatial shadow extraction, not a complete production claim path. No five-second target or latency ceiling is claimed. No rejected OCR engine, recognition batch, arena/thread or spinning configuration was reopened.

## Human-review handoff

The existing **150-page** selection is preserved byte-for-byte. A local handoff packet contains only its original page/package references, instructions for two independent reviewers and adjudication, and an empty response schema. It contains no model predictions, filled answers, labels or authority grants. Source hashes are required on responses; source extraction and external identity validation are separate. Detailed responses must remain outside Git and pass existing governed truth-ingestion and release gates.

Packet: `evaluation_results/closure/iteration4/human_review/`. Status: **AWAITING_INDEPENDENT_HUMAN_REVIEW**. No reviewers were contacted and no human review is claimed to have occurred.

## Safety and remaining work

Canonical output hashes and frozen cohort/evidence hashes match the iteration-three baseline. Production authority remains disabled. The overall recall target of 98%, preferred 18/20 clean claims and five-second latency target are not met. Candidate, technical blocker, HITL and runtime ceilings remain unproven. Remaining 11 governed misses require source-specific evidence; do not reinterpret the weak label alternatives as trusted recovery.

Production accuracy, critical accuracy, accepted precision, critical false accepts, field HITL, claim HITL and STP remain **null / NOT_EVALUABLE**. Detailed claim, page, source and review artifacts stay in ignored local storage. Only code, synthetic tests and aggregate reports are committed.

Validation: **1,497 passed, six skipped**, zero failures/errors and zero new semantic regressions against iteration three. The same two dependency warnings remain. Three false-UB04 canaries pass; Ruff on changed Python files, scoped mypy on four files, architecture validation, Compose and diff checks pass.
