# Routing Architecture Authority Audit

Audit date: 2026-08-22. Production Router V4 remains disabled and unchanged.

| Path | Decision point | Input → output | Runtime / evaluation | Dispatch authority | Conflict/status |
|---|---|---|---|---|---|
| `packages/document_routing/router.py` | `MultiSignalRouter.route` | image + OCR geometry → `RoutingEvidence` nomination | legacy runtime when enabled; evaluation | none after firewall | formerly treated as final family |
| `packages/document_routing/v4.py` | `InvariantRouterV4.route` | feature bundle → `RoutingEvidence` | evaluation only | none | V4 rejected/not eligible |
| `packages/document_routing/ml/inference.py` | ML eligibility | safe features → eligibility evidence | evaluation only | none | LightGBM/XGBoost rejected |
| `packages/document_routing/visual/inference.py` | visual evidence | thumbnail → `VisualRouteEvidence` | evaluation only | none | Visual V1 rejected |
| `packages/layout_intelligence/engine.py` | `BundleDLayoutEngine` | OCR/layout tokens → generic layout route | unstructured runtime | layout result only | cannot authorize CMS/UB |
| `workers/unstructured_extraction/family_router.py` | family routing | layout evidence → Bundle-D family | unstructured runtime | field-engine selection only | downstream of canonical non-standard route |
| `workers/page_detection/router.py` | `PageRoutingService` | page images → legacy bundle/template nomination | runtime | none after firewall | retains legacy thresholds as evidence producer; migration debt |
| `packages/document_routing/decision_service.py` | `DocumentRoutingDecisionService` | classification + verification evidence → canonical decision | runtime and evaluation | **sole `ProcessingRoute` producer** | authoritative |
| `packages/standard_form_verification/service.py` | `StandardFormVerificationService` | candidate + independent invariants → verification | runtime and evaluation | eligibility evidence only | fail-closed |
| `packages/processing_routes/resolver.py` | `ProcessingRouteResolver` | classification + verification → processing route | runtime and evaluation | **sole fixed-route mapping** | firewall |
| `workers/page_detection/consumer.py` | orchestration | page result → decision-service call/event | runtime | publishes canonical result only | no thresholds or verification logic |
| `workers/standard_form_extraction/consumer.py` | defense-in-depth validation | standard event → extraction | runtime | consumes only verified fixed route | rejects missing/mismatched verification |
| `packages/extraction_routing.py` | target adapter | `ProcessingRoute` → legacy target enum | runtime | mapping adapter only | rejects classifier family strings |

The pre-remediation conflict was direct `MultiSignalRoute.CMS1500/UB04 → ExtractionTarget` conversion in the page worker. That path has been removed. Remaining legacy bundle and page-role decisions are nomination evidence and migration debt; they cannot cross the fixed-extractor firewall.
