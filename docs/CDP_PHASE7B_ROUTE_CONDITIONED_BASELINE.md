# CDP Phase 7B Route-Conditioned Extraction Baseline

This is a regression observation on the previously observed production-
representative V2 set. It is not untouched and cannot tune frozen Router V3.
Routing and extraction correctness are reported separately.

Frozen Router V3 routed 70/500 documents correctly (14%). The correctly routed
subset contains 20 CMS-1500 documents and 50 attachments; it contains no UB-04
or custom structured documents. Consequently UB fixed-field/service-line and
UNKNOWN_STRUCTURED extraction metrics are `NOT_MEASURABLE_DUE_TO_ROUTING`.

For CMS, registration succeeded on 30% of the correctly routed subset. Field
exact match was 0/480. The failure Pareto is 224 registration-bound fields, 160
unsupported schema fields and 96 OCR-or-crop fields. Field-level ground-truth
boxes are absent, so crop correctness is a conservative OCR-evidence proxy and
must not be treated as an independently labeled crop metric.

For the 50 correctly routed attachments, token accuracy was 55.71%, detected-
value normalization was 66.23%, and final field exact match was 14.57%. The
Pareto is 155 token-OCR failures, 122 label/link failures, 22 normalization
failures and 51 matches.

All Phase 7B Gate 1 checks fail. False accepts and critical false accepts remain
zero because the benchmark does not promote any extraction candidate. The next
development work is registration/reference governance, canonical schema
coverage, then crop/OCR analysis on independently labeled development boxes.
HITL, evidence thresholds and STP remain frozen.
