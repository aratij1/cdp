# Router Input Parity Audit

| Input | ROUTING_DEV_V3 | Representative/runtime | Parity | Impact |
|---|---|---|---|---|
| Decoder | PIL JPEG open | PIL open after document path resolution | same | low |
| Color mode | direct `convert(L)` | `convert(L)` | same | low |
| Orientation | none | detected and applied | different | high |
| Deskew | none | detected and applied | different | high |
| Denoise | none | applied | different | high |
| Resize | source dimensions | source dimensions | same | low |
| OCR engine/config | Tesseract PSM 11 | Tesseract PSM 11 | same | low |
| Line/geometry construction | Tesseract adapter | Tesseract adapter | same | low |
| Feature flag | direct canonical router | Router V3 evaluation flag | equivalent | low |
| Router configuration | frozen V3 YAML | frozen V3 YAML/hash checked | same | none |
| Page rasterization/DPI | homogeneous generated JPEG | heterogeneous prepared JPEG | different | high |

Conclusion: `INPUT_PIPELINE_PARITY_DEFECT`. The V3 promotion benchmark bypassed
orientation, deskew and denoise used by runtime/representative evaluation. V4
development evaluation must call `prepare_routing_image` (`routing-input-v4.0`)
before feature collection. Router V3 evidence remains frozen and is not
recomputed or promoted after this finding.
