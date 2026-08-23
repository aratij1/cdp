# CDP Phase 8 Production Accuracy Architecture

Phase 8 changes the standard-form foundation from template-first regional OCR to local-first dynamic layout evidence.

The production path now builds one cached `PageObservation` per page from full-page RapidOCR and OpenCV structure. CMS uses a configurable semantic field graph with bounded alias matching and field-specific spatial contracts. UB-04 uses a separate institutional structural map and reconstructs service rows from the observation's existing token geometry. Neither family is modeled as the other with different coordinates.

Dynamic ROI priority is:

1. anchor-relative;
2. structural-region;
3. compatible registered-template fast path;
4. unresolved.

Registration remains available, but it is attempted only after dynamic field evidence cannot resolve the page. Incompatible lineages cannot authorize template ROIs. The former safety invariants—no rescale-only fixed extraction, no cross-family fallback, and canonical post-evidence HITL authority—remain enforced.

The local evidence cascade accepts a RapidOCR candidate when deterministic normalization and healthcare datatype validation succeed. Otherwise, it selects one configured local secondary: Tesseract for numeric/date/code fields, Paddle for names/addresses, OpenCV for checkboxes, and token geometry for tables. Cloud providers are disabled on the common path. Docling/Gemini remain exception-gateway concerns and Textract requires explicit opt-in.

Performance contracts:

- full-page OCR calls per normal page: one;
- OCR engines: worker-local and long-lived;
- primary field regional OCR calls: zero when observation tokens suffice;
- UB per-cell OCR: prohibited as a default;
- incompatible template SIFT retries: avoided;
- observation cache key: page SHA-256 + OCR model version + preprocessing version.

Accuracy numbers are intentionally not claimed before verified truth exists. Phase 7A.15's 800-page observation-only boundary remains untouched.
