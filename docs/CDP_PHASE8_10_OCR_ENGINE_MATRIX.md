# CDP Phase 8.10 — OCR Engine Matrix

Only RapidOCR was executed on the Phase 8.10 common path. Across 485 persisted
page-observation/regional candidate observations its weighted normalized accuracy
is 80.82%. PaddleOCR and Tesseract have zero Phase 8.10 executions and therefore
receive no invented accuracy or latency result.

Primary RapidOCR accuracy is 83.33% across 420 validation fields. Selective
regional RapidOCR ran for 78 fields and produced 11 incremental correct values.
The largest gains are patient names (6), insured names (3), provider name (1),
and member ID (1).

The versioned Phase 8.10 route/profile candidates remain `EVALUATION_ONLY`.
Digit-, date-, name-, currency-, and alphanumeric-preserving profiles are
available through the governed preprocessing registry but are not promoted
because a source-disjoint engine/profile bakeoff has not established an advantage.

Artifacts: `ocr_engine_matrix.json/csv` and `evidence_yield.json/csv`.
