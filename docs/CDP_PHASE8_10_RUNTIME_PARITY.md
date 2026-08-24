# CDP Phase 8.10 — Runtime Parity

Runtime/evaluation parity is `PASS`.

The evaluator invokes the canonical `StandardFormProcessingService`, `FieldLocator`, `DynamicROIResolver`, OCR execution service, extraction service, and the same evidence/claim decision services used by runtime. It does not implement an evaluation-only acceptance route.

The only evaluation-only geometry operation maps frozen Source-C truth boxes into the affine-transformed page coordinate system. That mapping is used solely for scoring expected regions and is never available to runtime localization, extraction, validation, or decision code.

Safety invariants remained intact:

- critical false accepts: 0;
- invalid deterministic auto-accepts: 0;
- accepted-field precision: 100%;
- secondary provenance coverage: 100%;
- unknown dependency rate: 0%;
- cloud calls/cost: 0 / $0.00.

The locked holdout was not accessed, no new model was introduced, and routing or decision policy was not tuned.
