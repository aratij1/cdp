# CDP Cost Baseline V2

> Recorded synthetic local frontier. Wall/provider latency is not mislabeled as CPU time or end-to-end document latency.

| Measure | Result |
|---|---:|
| Documents | 120 |
| Fields | 600 |
| OCR engine calls | paddleocr: 600, rapidocr: 60, tesseract: 540 |
| Selective confirmation/retry calls | 600 |
| Recorded OCR wall ms / field | 615.15 |
| Recorded field OCR P95 ms | 1821.95 |
| Human-review fields | 85 |
| Human-review claims | 24 |
| CPU ms/document and CPU ms/field | `NOT_MEASURED` |
| Memory and storage writes | `NOT_MEASURED` |
| Cost/document, page, field, STP, review, review avoided | `NOT_MEASURED` |

Promotion impact: `NEEDS_MORE_DATA`. A production-like run with resource meters and an approved price sheet is required; zero local API charges do not imply zero infrastructure cost.
