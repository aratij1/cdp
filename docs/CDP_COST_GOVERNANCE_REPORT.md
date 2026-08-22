# Cost Governance — Local Load Profile

The measured load run made 480 Tesseract calls and zero RapidOCR, PaddleOCR, Docling, Gemini, Textract, or human-review calls. Metered provider cost was $0 because Tesseract executed locally.

The auditable planning model now combines the configured extraction route mix, measured local OCR throughput, assumed vCPU and platform unit costs, and the existing $1.00 per reviewed-page HITL assumption.

At the current 76.67% review rate, projected cost is $0.76936/page: $0.00210 extraction routes, $0.00010 compute, $0.00050 storage/orchestration, and $0.76667 HITL. HITL represents 99.65% of the projected total.

Scenario totals are $0.30270/page at 30% review, $0.10270/page at 10% review, and $0.05270/page at 5% review.

These are planning projections, not invoiced production costs. Reviewer payroll, deployed vCPU pricing, storage, and route mix must be replaced with production telemetry when available. Cloud-provider cost controls remain enforced by the adaptive router and AI gateway budgets.

Machine-readable evidence is stored at `evaluation_results/cost_model_v1/report.json`.
