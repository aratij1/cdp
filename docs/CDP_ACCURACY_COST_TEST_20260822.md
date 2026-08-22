# CDP accuracy and cost test — 2026-08-22

## Governed labeled sample

The evaluation reran against 30 documents and 366 labeled fields using ground-truth hash `f7f91d5e...f954` and prediction hash `2ad18b25...2c67`.

| Metric | Result |
|---|---:|
| Overall normalized field accuracy | 72.13% |
| CMS-1500 accuracy | 87.33% |
| UB-04 accuracy | 75.93% |
| Unstructured accuracy | 32.97% |
| Critical-field accuracy | 65.56% |
| Total false-accept rate | 0.00% |
| Critical false-accept rate | 0.00% |
| Perfect-claim rate | 20.00% |
| Safe STP rate | 0.00% |
| Human-review rate | 76.67% |

The validation split contained 5 documents and 61 fields and measured 75.41% overall, 82.05% CMS-1500, 77.78% UB-04, 53.85% unstructured, 60.00% critical-field accuracy, zero false accepts, 20% perfect claims and 80% claim review.

## Fresh synthetic OCR robustness test

The installed local OCR runtime processed 600 field crops from 120 non-PHI synthetic documents. Exact-match accuracy was 37.33% overall: CMS-1500 58.33% and UB-04 23.33%. Mean OCR latency was 359.37 ms/field and P95 was 813.00 ms. All candidates were forced non-accepted, so false accepts were zero by construction.

Condition accuracy: clean 65.00%, low contrast 65.00%, skew 56.67%, handwriting 53.33%, poor DPI 46.67%, fax 36.67%, cropped edges 3.33%, and rotation 0.00%. This is a robustness diagnostic, not production accuracy.

## Processing plus HITL cost

| Scenario | Review rate | Pre-HITL/page | HITL/page | Total/page |
|---|---:|---:|---:|---:|
| Current | 76.67% | $0.002698 | $0.766667 | $0.769365 |
| Milestone | 30% | $0.002698 | $0.300000 | $0.302698 |
| Target | 10% | $0.002698 | $0.100000 | $0.102698 |
| Stretch | 5% | $0.002698 | $0.050000 | $0.052698 |

Current HITL accounts for 99.65% of projected total cost. Processing includes the configured route mix, compute derived from the measured 11.33 local OCR fields/second, and storage/orchestration. Reviewer, vCPU and platform unit costs are configured planning assumptions rather than invoice measurements.

## Decision

`NEEDS_MORE_DATA`. Safety remains fail-closed, but current accuracy, STP and review rate do not meet release targets. The largest measured robustness failures are rotation, cropped edges, UB-04 field localization, IDs and NPI. Production claims remain blocked pending an untouched external holdout.
