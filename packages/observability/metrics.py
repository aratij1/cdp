"""Prometheus metrics -- the exact names from the platform spec, defined
once here so every app/worker imports the same `CollectorRegistry` instead
of each inventing its own metric names. `packages/security/redaction.py`
is what keeps PHI out of these (labels are field *names*/document IDs/
route names, never field *values*).
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

documents_received_total = Counter(
    "documents_received_total",
    "Documents accepted by the ingestion API",
    ["tenant_id", "detected_format"],
    registry=REGISTRY,
)

pages_processed_total = Counter(
    "pages_processed_total",
    "Pages decoded and preprocessed",
    ["bundle_type"],
    registry=REGISTRY,
)

attachments_skipped_total = Counter(
    "attachments_skipped_total",
    "Bundle B/D pages classified as attachments and preserved without extraction",
    registry=REGISTRY,
)

cache_hits_total = Counter(
    "cache_hits_total",
    "Idempotent re-ingestions served from an existing Document/Claim",
    registry=REGISTRY,
)

ocr_latency_seconds = Histogram(
    "ocr_latency_seconds",
    "Regional OCR call latency",
    ["extraction_method"],
    registry=REGISTRY,
)

classification_latency_seconds = Histogram(
    "classification_latency_seconds",
    "Page routing/classification latency",
    ["method"],
    registry=REGISTRY,
)

validation_failure_total = Counter(
    "validation_failure_total",
    "Deterministic validation failures",
    ["rule_name", "criticality"],
    registry=REGISTRY,
)

retry_total = Counter(
    "retry_total",
    "Alternate-preprocessing OCR retries",
    ["improved"],
    registry=REGISTRY,
)

preprocessing_strategy_cpu_seconds = Histogram(
    "preprocessing_strategy_cpu_seconds",
    "CPU time consumed by a bounded preprocessing retry strategy",
    ["strategy", "outcome"],
    registry=REGISTRY,
)

vlm_invocation_total = Counter(
    "vlm_invocation_total",
    "VLM fallback calls",
    ["insufficient_evidence"],
    registry=REGISTRY,
)

human_review_total = Counter(
    "human_review_total",
    "Fields routed to human review",
    ["reason"],
    registry=REGISTRY,
)

straight_through_rate = Gauge(
    "straight_through_rate",
    "Fraction of claims completed with no human review, over the current window",
    registry=REGISTRY,
)

estimated_cost_usd_total = Counter(
    "estimated_cost_usd_total",
    "Estimated inference/processing cost",
    ["extraction_method"],
    registry=REGISTRY,
)

processing_errors_total = Counter(
    "processing_errors_total",
    "Unhandled errors per worker/stage",
    ["worker", "stage"],
    registry=REGISTRY,
)

kafka_consumer_lag = Gauge(
    "kafka_consumer_lag",
    "Consumer group lag per topic (source: broker admin API, updated by a poller)",
    ["topic", "consumer_group"],
    registry=REGISTRY,
)

field_reconciliation_total = Counter(
    "field_reconciliation_total",
    "Field reconciliation decisions without field values",
    ["field_name", "criticality", "decision"],
    registry=REGISTRY,
)

critical_false_accepts_total = Counter(
    "critical_false_accepts_total",
    "Confirmed critical-field false acceptances; release-blocking when nonzero",
    ["field_name", "model_version"],
    registry=REGISTRY,
)

ai_gateway_requests_total = Counter(
    "ai_gateway_requests_total",
    "External AI gateway requests",
    ["provider", "model", "outcome"],
    registry=REGISTRY,
)

ai_gateway_cost_usd_total = Counter(
    "ai_gateway_cost_usd_total",
    "Actual external AI cost reported by the gateway",
    ["tenant_id", "provider", "model"],
    registry=REGISTRY,
)

ai_gateway_tokens_total = Counter(
    "ai_gateway_tokens_total",
    "External AI tokens by direction",
    ["provider", "model", "direction"],
    registry=REGISTRY,
)

registration_confidence = Histogram(
    "registration_confidence",
    "Accepted and rejected page registration confidence",
    ["algorithm", "accepted"],
    registry=REGISTRY,
)

image_quality_score = Histogram(
    "image_quality_score",
    "Page image quality score distribution",
    ["document_family"],
    registry=REGISTRY,
)

human_review_queue_depth = Gauge(
    "human_review_queue_depth",
    "Review tasks by workflow status",
    ["status", "criticality"],
    registry=REGISTRY,
)

human_review_turnaround_seconds = Histogram(
    "human_review_turnaround_seconds",
    "Time from review task creation to terminal decision",
    ["criticality", "decision"],
    registry=REGISTRY,
)

database_connections = Gauge("database_connections", "Open database connections by state", ["state"], registry=REGISTRY)
postgres_transactions_total = Counter("postgres_transactions_total", "PostgreSQL transactions by outcome", ["outcome"], registry=REGISTRY)
redis_cache_operations_total = Counter("redis_cache_operations_total", "Redis cache operations by hit or miss", ["result"], registry=REGISTRY)
object_store_bytes_total = Counter("object_store_bytes_total", "S3-compatible object bytes transferred", ["operation"], registry=REGISTRY)
worker_resource_utilization = Gauge("worker_resource_utilization", "Worker resource utilization ratio", ["worker", "resource"], registry=REGISTRY)

# Phase 4 production-readiness SLOs. Labels are allow-listed operational
# dimensions; candidate values, document IDs, claim IDs, and patient data are
# deliberately absent.
cdp_field_safe_coverage = Gauge(
    "cdp_field_safe_coverage", "Safely auto-resolved field fraction", registry=REGISTRY,
)
cdp_raw_accuracy = Gauge(
    "cdp_raw_accuracy", "Truth-qualified raw field accuracy", registry=REGISTRY,
)
cdp_critical_accuracy = Gauge(
    "cdp_critical_accuracy", "Truth-qualified C2/C3 field accuracy", registry=REGISTRY,
)
cdp_field_hitl_rate = Gauge(
    "cdp_field_hitl_rate", "Field fraction requiring human review", registry=REGISTRY,
)
cdp_claim_stp_rate = Gauge(
    "cdp_claim_stp_rate", "Claim straight-through-processing fraction", registry=REGISTRY,
)
cdp_claim_hitl_rate = Gauge(
    "cdp_claim_hitl_rate", "Claim fraction requiring human review", registry=REGISTRY,
)
cdp_false_accept_total = Counter(
    "cdp_false_accept_total", "Confirmed false field acceptances",
    ["field_name", "criticality"], registry=REGISTRY,
)
cdp_critical_false_accept_total = Counter(
    "cdp_critical_false_accept_total", "Confirmed C2/C3 false acceptances",
    ["field_name", "criticality"], registry=REGISTRY,
)
cdp_route_invocation_total = Counter(
    "cdp_route_invocation_total", "Governed OCR route invocations",
    ["route_id", "route_status", "outcome"], registry=REGISTRY,
)
cdp_route_shadow_total = Counter(
    "cdp_route_shadow_total", "Shadow route observations",
    ["route_id", "outcome"], registry=REGISTRY,
)
cdp_route_agreement_total = Counter(
    "cdp_route_agreement_total", "Production/shadow agreement observations",
    ["route_id", "agreement"], registry=REGISTRY,
)
cdp_route_false_agreement_total = Counter(
    "cdp_route_false_agreement_total", "Truth-confirmed false route agreements",
    ["route_id", "criticality"], registry=REGISTRY,
)
cdp_router_ml_inference_total = Counter(
    "cdp_router_ml_inference_total", "ML eligibility inference attempts",
    ["model_version", "outcome"], registry=REGISTRY,
)
cdp_router_ml_inference_latency_seconds = Histogram(
    "cdp_router_ml_inference_latency_seconds", "ML eligibility inference latency",
    ["model_version"], registry=REGISTRY,
)
cdp_router_ml_proposed_eligibility_total = Counter(
    "cdp_router_ml_proposed_eligibility_total", "ML-proposed eligibility by safe family",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_router_ml_fused_eligibility_total = Counter(
    "cdp_router_ml_fused_eligibility_total", "Fused eligibility by safe family",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_router_ml_false_eligibility_total = Counter(
    "cdp_router_ml_false_eligibility_total", "Truth-confirmed false ML eligibility",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_router_ml_model_version_info = Gauge(
    "cdp_router_ml_model_version_info", "Loaded ML eligibility model version",
    ["model_version", "feature_version"], registry=REGISTRY,
)
cdp_visual_route_prediction_total = Counter(
    "cdp_visual_route_prediction_total", "Visual evidence predictions",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_visual_route_latency_seconds = Histogram(
    "cdp_visual_route_latency_seconds", "Visual evidence inference latency",
    ["model_version"], registry=REGISTRY,
)
cdp_visual_standard_proposal_total = Counter(
    "cdp_visual_standard_proposal_total", "Visual standard-family proposals",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_visual_standard_veto_total = Counter(
    "cdp_visual_standard_veto_total", "Visual standard proposals vetoed by existing evidence",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_visual_standard_contradiction_total = Counter(
    "cdp_visual_standard_contradiction_total", "Contradiction classes observed for visual proposals",
    ["family", "contradiction_class", "model_version"], registry=REGISTRY,
)
cdp_visual_standard_ambiguity_total = Counter(
    "cdp_visual_standard_ambiguity_total", "Visual standard proposals made ambiguous",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_visual_false_standard_total = Counter(
    "cdp_visual_false_standard_total", "Truth-confirmed false visual standard proposals",
    ["family", "model_version"], registry=REGISTRY,
)
cdp_visual_model_version_info = Gauge(
    "cdp_visual_model_version_info", "Loaded visual evidence model version",
    ["model_version", "feature_version"], registry=REGISTRY,
)
cdp_policy_decision_total = Counter(
    "cdp_policy_decision_total", "Canonical field/claim policy decisions",
    ["policy_id", "decision"], registry=REGISTRY,
)
cdp_claim_blocker_total = Counter(
    "cdp_claim_blocker_total", "Blocking field decisions by safe dimensions",
    ["document_family", "field_name", "criticality"], registry=REGISTRY,
)
cdp_cost_per_document = Gauge(
    "cdp_cost_per_document", "Measured processing cost per document in USD",
    registry=REGISTRY,
)
cdp_cost_per_stp_claim = Gauge(
    "cdp_cost_per_stp_claim", "Measured processing cost per STP claim in USD",
    registry=REGISTRY,
)
cdp_cost_per_review_avoided = Gauge(
    "cdp_cost_per_review_avoided", "Measured processing cost per review avoided in USD",
    registry=REGISTRY,
)
cdp_queue_lag = Gauge(
    "cdp_queue_lag", "Consumer lag for a governed pipeline stage",
    ["topic", "consumer_group"], registry=REGISTRY,
)
cdp_p95_document_latency = Gauge(
    "cdp_p95_document_latency", "P95 end-to-end document latency in seconds",
    ["document_family"], registry=REGISTRY,
)
