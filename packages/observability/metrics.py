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
