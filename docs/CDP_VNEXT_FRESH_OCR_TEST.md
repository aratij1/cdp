# Fresh Local OCR Test

Test date: 2026-08-21  
Decision: **FAIL — DO NOT PROMOTE**

PaddleOCR 2.10.0 and Tesseract 5.4 were executed freshly against copied field crops with empty OCR
caches. The evaluator joined ground truth only after prediction generation. RapidOCR 1.4.4 passed a
separate live recognition smoke test, but the repository's legacy atomic benchmark driver does not
yet route through the vNext RapidOCR provider.

| Slice | Documents | Fields | Normalized accuracy | Critical false-accept rate | Perfect claim rate | STP rate |
|---|---:|---:|---:|---:|---:|---:|
| Holdout | 5 | 61 | 68.8525% | 0% | 0% | 0% |
| Validation | 5 | 61 | 75.4098% | 0% | 20% | 20% |
| All splits | 30 | 366 | 67.2131% | 3.8462% | 3.3333% | 3.3333% |

Across all splits, CMS-1500 accuracy was 80.5430%, UB-04 was 74.0741%, and unstructured-document
accuracy was 30.7692%. Critical-field accuracy was 57.7778%. The critical false-accept result makes
the candidate unsafe for promotion regardless of aggregate accuracy.

The crop-generation stage could not be rerun because both template YAML files intentionally have
`reference_image_path: null`; the test therefore used the repository's existing 280 PNG crop/contact
sheet artifacts. Structured OCR was fresh, while unstructured predictions were inherited from the
prior prediction file by the legacy driver. Results live under `evaluation_results/vnext_fresh_ocr`.
