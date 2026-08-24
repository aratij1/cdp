# CDP Phase 8.9 — Localization Recovery and Provenance Completion

## Decision

`NEEDS_MORE_DATA`

Phase 8.9 improves validation localization from the Phase 8.8C baseline of about
24.76% to 95.24% without weakening acceptance policy. It does not qualify for
promotion because critical localization, wrong-crop recall, extraction accuracy,
and latency miss their engineering gates. The locked holdout was not accessed;
these results are source-disjoint synthetic engineering evidence, not
production-source validation.

## Frozen evaluation result

The evaluator used `DEV`, `VALIDATION`, and `ADVERSARIAL` engineering partitions.
All localization and extraction accuracy values below are from the `VALIDATION`
partition (420 field observations). Results are persisted under
`evaluation_results/phase8_9/`; the evaluator fails with
`PROMOTION_NOT_EVALUABLE` when mandatory Phase 8.8C observation artifacts are
missing.

| Gate | Measured | Target | Result |
| --- | ---: | ---: | --- |
| Overall localization | 95.24% | >= 90% | PASS |
| Critical localization | 94.94% | >= 95% | FAIL |
| Value-span containment | 95.48% | >= 95% | PASS |
| Wrong-crop recall | 10.00% | >= 95% | FAIL |
| Wrong-crop precision | 50.00% | reported | — |
| Overall raw accuracy | 73.33% | >= 90% | FAIL |
| Critical raw accuracy | 83.63% | >= 95% | FAIL |
| CMS1500 raw accuracy | 74.89% | >= 90% | FAIL |
| UB04 raw accuracy | 71.43% | >= 90% | FAIL |
| Unknown dependency | 0.00% | <= 5% | PASS |
| Secondary provenance coverage | 100.00% | 100% | PASS |
| Worst-source P95 latency | 14.53 s | <= 10 s | FAIL |

The crop strategy deliberately favored containment during this recovery phase.
Consequently, 93.81% of validation crops are classified as over-crops. That is
not treated as a localization success when the crop is empty, under-cropped,
wrong, or contaminated by a configured neighboring field. The low wrong-crop
recall is a blocking result and is not masked by the high containment rate.

## Safety, automation, and economics

| Metric | Result |
| --- | ---: |
| Critical false accepts | 0 |
| Correlated false-agreement auto-accepts | 0 |
| Invalid-NPI auto-accepts | 0 |
| Accepted-field precision | 100.00% |
| Claim STP | 0.00% |
| Claim HITL | 100.00% |
| Field HITL | 91.17% |
| Common-path cloud cost/page | $0.00000 |

The Phase 8.9 replay estimates fully loaded cost per page, including HITL, at
$0.39008 for SOURCE_A, $0.38264 for SOURCE_B, and $0.38760 for SOURCE_C
(mean $0.38677). Local compute cost was not remeasured in this phase, so these
figures must not be represented as a fresh infrastructure cost benchmark.

Latency by source:

| Source | P50 | P95 | P99 |
| --- | ---: | ---: | ---: |
| SOURCE_A | 8.10 s | 14.53 s | 26.74 s |
| SOURCE_B | 7.12 s | 11.59 s | 13.58 s |
| SOURCE_C | 5.27 s | 10.90 s | 18.93 s |

## Implemented architecture

Localization is now an explicit evidence-producing stage:

1. Bounded anchor discovery records the matched alias, anchor box, and anchor
   confidence.
2. The locator generates anchor-relative token, line, and contract candidates.
3. Versioned scoring combines anchor, geometry, semantic, zone, neighbor, and
   structural signals using `config/localization_scoring_v1.yaml`.
4. Candidate ranking emits the selected region, candidate set and hash,
   localization stage/version, component scores, confidence, and reason codes.
5. Wrong-crop signals are evaluated before structural fallback and remain
   blocking evidence; localization never creates an acceptance disposition.
6. Registered-template resolution records template identity, registration method
   and confidence, transform hash, source/mapped coordinates, and linked
   localization identity. Registration failure remains fail-closed.

Ground-truth metrics now distinguish geometric match, value containment,
over-crop, under-crop, wrong neighbor, wrong region, and empty region. The
evaluator reports IoU, containment, error rates, strategy/family/field/source/
criticality breakouts, and empirical confidence calibration buckets.

## Provenance and dependency policy

Every governed OCR execution returns a candidate with provenance containing the
document/page representation, page and crop hashes, bounding box,
preprocessing profile and hash, localization identity/version, engine/model
identity and versions, invocation identity, upstream/shared dependency IDs,
normalization version, and timestamp.

Dependency is classified from lineage dimensions, not engine names:

- `CORRELATED`: derived lineage, a shared dependency/upstream candidate, or
  shared crop pixels plus shared localization/observation.
- `UNKNOWN`: required representation, crop, localization, preprocessing, or
  engine lineage is missing.
- `INDEPENDENT`: representation, crop, localization, preprocessing, and engine
  family are distinct, preprocessing hashes do not match, and crop overlap is
  below 50%.
- `PARTIALLY_INDEPENDENT`: complete lineage has a mixture of shared and distinct
  dimensions that does not satisfy either stronger classification.

The replay observed 126 multiple-local-evidence pairs; all were correctly
classified `CORRELATED`, unknown dependency was 0%, and all 126 secondary
candidates had complete provenance. Correlated agreement therefore supplied no
independent-E2 acceptance credit.

## Verification

- Ruff checks: PASS
- Full repository tests: 954 passed, 5 skipped
- Runtime/evaluation parity: PASS
- Required adversarial coverage includes correct-anchor/wrong-crop, two engines
  agreeing on the wrong crop, correlated agreement, distinct-engine/distinct-crop
  dependency classification, valid-looking neighboring values, invalid NPI
  agreement, neighboring patient/provider names, and template registration
  failure.
- Missing mandatory evaluation artifacts fail the promotion evaluation rather
  than silently skipping it.

## Residual priority

No STP policy change is justified. The next bounded work should improve
wrong-crop classification (especially valid-looking neighboring values), tighten
the current over-crops while preserving containment, recover the remaining
critical UB localization misses, and reduce repeated OCR work driving SOURCE_A
P95. Extraction errors must then be addressed downstream of confirmed-correct
localization. A locked-holdout or production promotion remains prohibited until
the engineering gates pass and genuinely independent real-source evidence is
available.
