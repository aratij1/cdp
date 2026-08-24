# CDP Phase 8.10 — Runtime Parity

Historical extraction/candidate-generation parity is `PASS`. Historical
end-to-end decision parity is `FAIL` because Phase 8.10 used evaluation route
mode and the balanced evidence policy while runtime used runtime route mode and
the default evidence policy. Phase 8.10B replaces this ambiguous label with
separate extraction, decision, and end-to-end parity gates.

The evaluator invokes the canonical `StandardFormProcessingService`, `FieldLocator`, `DynamicROIResolver`, OCR execution service, and extraction service. Its historical decision replay is intentionally reproducible but is not runtime-equivalent; Phase 8.10B binds normal runtime and evaluation decisions through one canonical profile factory.

The only evaluation-only geometry operation maps frozen Source-C truth boxes into the affine-transformed page coordinate system. That mapping is used solely for scoring expected regions and is never available to runtime localization, extraction, validation, or decision code.

Safety invariants remained intact:

- critical false accepts: 0;
- invalid deterministic auto-accepts: 0;
- accepted-field precision: 100%;
- secondary provenance coverage: 100%;
- unknown dependency rate: 0%;
- cloud calls/cost: 0 / $0.00.

The locked holdout was not accessed, no new model was introduced, and routing or decision policy was not tuned.
