# CDP Phase 5: Layout Intelligence Foundation

## Implemented

Unknown layouts now have a deterministic, geometry-preserving Bundle-D path.
The engine reconstructs reading order, detects configurable healthcare labels,
enforces a label/value firewall, links candidate values using spatial evidence,
validates healthcare datatypes, infers a schema family, and maps results into
canonical fields. Every live generic candidate is submitted to the existing
`EvidenceDecisionService`; the layout relationship is E3 structural evidence
and cannot independently authorize C2/C3 acceptance.

The generic routes are `UNKNOWN_STRUCTURED`, `UNKNOWN_UNSTRUCTURED`, and
`NON_CLAIM`. Known standard forms remain on their existing template pipeline.
Existing recurring Bundle-D families also remain the first Bundle-D route.

Local table reconstruction maps healthcare headers to columns and reconstructs
service-line rows using OCR geometry. It exposes `requires_docling` only when a
table is detected but deterministic reconstruction confidence is insufficient.
No Docling or cloud-AI call is made by default.

## Development and evaluation separation

`BUNDLE_D_DEV_V1` is a deterministic 30-document development corpus covering
professional-claim-like, institutional-claim-like, EOB, itemized bill, medical
invoice, lab report, attachment, provider statement, correspondence, and
non-claim families. Its manifest marks it development-only.

The frozen 500-document engineering holdout was not used for aliases,
thresholds, schemas, OCR selection, prompts, or table parameters. It must not
be rerun as an iterative tuning set. An independently generated untouched
holdout is required to measure Phase 5 generalization.

## Metrics required for promotion

Promotion reporting must keep these layers separate:

- Routing: standard-form precision/recall, unknown-layout recall, non-claim accuracy.
- Layout: label detection, label/value links, table detection, table cells.
- Extraction: exact match, CER, and critical-field exact match.
- Decisions: safe coverage, false accepts, and field HITL.
- Claims: qualified STP and claim HITL.

Full-page OCR was measured on 30 annotated development pages. PaddleOCR reached
100% token recall/precision, 0 CER, 0.689 mean matched-box IoU, and 1.43 seconds
mean latency. RapidOCR reached 78.27% recall, 88.75% precision, 2.47% CER,
0.635 IoU, and 3.31 seconds. PaddleOCR is therefore promoted only for the live
Bundle-D full-page route; standard forms retain regional OCR.

The first generated untouched corpus was rejected after the freeze audit found
9 byte-identical documents. It is not promotion evidence. Replacement
`BUNDLE_D_UNTOUCHED_V2` was frozen with 50 unique document hashes before its
only evaluation run. Results were 100% unknown-layout recall, 100% non-claim
accuracy, 100% label recall/link accuracy, and 175/175 exact fields. Mean
latency was 1.10 seconds and P95 was 2.39 seconds.

Decision results remain deliberately conservative: safe coverage 0%, field
HITL 100%, and zero false accepts. One OCR route plus E3/E4 does not satisfy
the existing multi-evidence acceptance policy. The raw/layout result therefore
does not authorize STP promotion.

Selective AI is connected through the existing central gateway as a bounded
ambiguous-region request. Responses are explicitly E7 auxiliary candidates;
they never carry acceptance authority and must return through
`EvidenceDecisionService`.

## Verification

Standard-form routing and extraction were not modified.
