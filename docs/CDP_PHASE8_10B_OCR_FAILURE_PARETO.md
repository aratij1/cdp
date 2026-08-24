# CDP Phase 8.10B OCR Failure Pareto

The frozen extraction records contain 390 regions marked expected-value-present. Rapid's page observation is correct on 301 and wrong on 89 (77.18% conditional accuracy). Selective regional extraction leaves 17 OCR-origin final failures; the field matrix has 18 total final failures because one field starts with correct observation OCR and fails later. This preserves the historical 301/390 denominator; it is not silently substituted with the separate 369/420 production-usable localization metric.

| Primary class | Count |
|---|---:|
| WORD_SEGMENTATION | 56 |
| CHAR_INSERTION | 25 |
| CHAR_DELETION | 5 |
| PUNCTUATION | 2 |
| CHAR_SUBSTITUTION | 1 |

Meaningful attribution: 100.00%. Datatype and image-condition labels are retained as secondary tags in `ocr_failure_records.jsonl`.

## Frozen-crop local engine benchmark

All engines received the exact same 89 crop byte sequences. RapidOCR's diagnostic reread solved 35 (39.33%); native Tesseract solved 18 (20.22%); PaddleOCR was not installed and is recorded as `ENGINE_UNAVAILABLE`, not as a zero-quality engine. Paddle therefore solved 0, Tesseract solved 18, Paddle and Tesseract jointly solved 0, and 44 failures remained wrong in every available engine run.

Rapid and Tesseract were partly complementary: 8 crops were solved by both available engines, 27 by Rapid alone, and 10 by Tesseract alone. Tesseract wins were patient name (7), provider name (5), insured name (2), relationship (2), and date of birth (2). The measured aggregate Tesseract latency divided by its 18 recovered fields was 1,457.81 ms per recovery; Rapid's equivalent was 5,059.33 ms. These are diagnostic failure-set economics, not common-path latency.
