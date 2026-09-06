# CDP closure iteration 3

Status: **CONTINUE**. Five additional exact source candidates were recovered. Targets and technical ceilings are not yet established. Production authority remains disabled.

## Fixed engineering cohort

The denominator remains 200 frozen synthetic fields across 20 claims. No reference value or reference crop enters candidate generation. The separate 150-page blind review selection is unchanged.

| Metric | Iteration 2 | Iteration 3 |
|---|---:|---:|
| Exact missing candidates | 29 | 24 |
| Governed missing candidates | 20 | 15 |
| Exact candidate Recall@1 / @3 / @5 | 67% / 85.5% / 85.5% | 68.5% / 88% / 88% |
| Governed candidate Recall@1 / @3 / @5 | 83.5% / 90% / 90% | 85% / 92.5% / 92.5% |
| C3 candidate Recall@5, 30 fields | 100% | 100% |
| Correct selected values, governed comparison | 166/200 | 166/200 |
| Technical blockers | 71 | 71 |
| Technical review fields | 29/200 | 29/200 |
| Zero recorded technical blockers | 14/20 | 14/20 |

Candidate Recall@1 measures the first available candidate; selected-value correctness measures actual selection, including abstention. New alternatives do not by themselves clear crop, form or authority requirements. Nine remaining exact misses already have governed-equivalent name representations. Correcting representation diagnostics is not extraction improvement.

Technical-STP-capable: **14/20 (70%)**, meaning zero recorded CDP-controlled technical blockers. Production-STP-capable with currently available evidence: zero; production STP performance is **NOT_EVALUABLE**.

Distances: zero = 14 claims; one = 1; two = 0; three = 1; four or more = 4. Remaining distances are 1, 3, 14, 16, 17 and 20. The distance-one provider ambiguity remains: its final characters are partly obscured. No source-based resolution was invented.

## Visibility and external disposition

All 29 starting exact misses have local source-bound audit records: 18 visible in existing OCR tokens, two visible in pixels but absent from OCR, nine partially visible. Inspection is engineering evidence, not independent truth. Root causes: seven token merges, two representation/reference mismatches, two date assembly defects, three unsupported atomic-field cases, four anchor misses, nine OCR corruptions and two OCR text absences. Five of these cases were recovered in this iteration.

| Remaining requirement | All 200 fields | 14 technically clean claims |
|---|---:|---:|
| Member authority | 20 | 14 |
| Provider authority | 20 | 14 |
| Patient/insured identity authority | 30 | 21 |
| Source evidence | 84 | 56 |
| Other recorded external field blockers | 0 | 0 |

All 14 clean claims additionally lack release qualification. No unsupported missing-attachment or business-exception labels were inferred. Local production distances include recorded field blockers plus one explicit claim qualification gap.

Engineering/frozen-cohort HITL: technical 29/200 = 14.5%; external 154/200 = 77%; observed union 155/200 = 77.5%. Overlapping review is counted once. These are not production-measured HITL rates.

## Fresh runtime

Same 12 pages, one worker, eight threads, CPU arena enabled, default recognition batch, fresh OCR and pooled sessions. Three separate processes; all five semantic comparisons match the retained baseline. Configuration did not change, so lower measurements are not credited as a new runtime optimization.

| Run | P95 seconds |
|---|---:|
| 1 | 5.998 |
| 2 | 5.581 |
| 3 | 5.573 |

Median P95/P99: **5.581s**. Median P50: 4.210s. Median throughput: 0.253 pages/s. Maximum sampled RSS: 1.41 GB; a continuous peak was not measured. Cold model setup: 1.23-1.28s, excluded from page timings. Host CPU and available memory, warm-only distributions and slowest-page stage breakdowns are in the aggregate JSON.

Recognition remains the largest measured OCR stage, approximately 2.49s/page on average, versus 0.55s detection and 0.18s classification. These stage means are not additive P95 estimates. Postprocessing is not separately timed. Registration, full claim processing and business validation are not executed by this timing harness. A complete production-path P95 and realistic cache-hit distribution remain unmeasured. **The five-second target is not met.**

## Same real 100-page cohort

Candidate-bearing pages: 38 originally, 46 in iteration 2, **46 now**. Alternatives: 66, 84, **85 now**. There are 76 candidate-bearing field pairs, seven ambiguous pairs and 54 no-candidate pages. Zero new full-page or regional OCR calls and zero LLM/VLM calls in this cached replay. Source validation plus discovery took 2.23s total; observed RSS approximately 88 MB. This timing excludes fresh OCR and complete claim processing. OTHER/UNKNOWN canonical localization remains zero, and package leakage is false. Coverage is not accuracy.

The separate timing experiments made 48 completed fresh OCR page calls (12 rejected pilot plus 36 retained-configuration repetitions), with no regional OCR or paid AI. Failed preliminary pilot invocations are excluded from successful-run metrics; they still consumed local runtime. Infrastructure cost is unmeasured.

## Retained and rejected changes

Retained: preserve a complete, calendar-valid date token beside a separate numeric flag (two exact recoveries); emit complete relationship and bill-type tokens under existing literal registry labels (three more). Tokens, provenance, external requirements and canonical decisions are preserved. A second complete date remains ambiguous; malformed tokens are never repaired by substring deletion.

Rejected: disabling ONNX idle spinning measured P95 7.039s with identical semantics, slower than the retained baseline. No runtime configuration change was retained. Earlier rejected broad OCR, name-window and batch/thread experiments were not reopened.

## Validation and publication

Full suite: **1485 passed, 6 skipped**, zero failures/errors. Prior baseline: 1,473 passed, six skipped; the same two dependency warnings remain. Strict identity, candidate engine, claim intelligence, evidence, routing/localization, Azure closed-world and historical regression tests are included. Ruff on changed Python files, scoped mypy on four files, architecture, Compose and diff checks passed. Three false-UB04 canaries pass; no candidate coverage or selected-value regressions; canonical outputs unchanged.

Only code, synthetic tests and aggregate reports are staged. Detailed visibility audits, claim matrices, field authority dispositions, source hashes and runtime records remain under ignored `evaluation_results/closure/iteration3/`. Existing reviewed commits are preserved. GitHub previously denied pushes by the authenticated account; publication does not establish technical closure.

## Remaining closure work

Candidate recall ceiling, blocker ceiling, technical-HITL ceiling and technical-STP-capable ceiling are **NOT_PROVEN**. The measured achieved values are 92.5% governed Recall@5, 71 blockers, 14.5% technical review and 70% technical capability; they are not proven ceilings. External requirements are enumerated, but do not justify calling visible unresolved candidates irrecoverable.

The distance-three follow-up was executed: its DOB, bill-type and diagnosis tokens contain leading contamination and their crops are unconfirmed. Existing characters cannot safely resolve those three blockers without deleting observed characters or relying on the reference. The distance-one provider value likewise cannot safely be completed from its obscured source. No blockers were removed by this review. The next unresolved engineering action is bounded label-to-value association for the four anchor-miss cases, using existing source tokens and independently justified geometry. Reference-driven values and crops, broad OCR retries and policy relaxation remain excluded.

Production accuracy, critical accuracy, accepted precision, critical false accepts, field HITL, claim HITL and STP are all **null / NOT_EVALUABLE** without independent release truth.
