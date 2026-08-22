# CDP Scalability Report

Promotion status: `NOT_RUN` / `NEEDS_MORE_DATA`.

The required 1,000-, 10,000-, and 50,000-page burst and sustained tests were not run because execution stopped at the untouched-holdout gate. No documents/hour, pages/hour, fields/sec, end-to-end P50/P95/P99, broker lag, database/cache/object-store utilization, review creation, error, or retry results are claimed.

The planning target is 5,000 documents/day with 50,000 pages/day headroom. The latter averages 2,083 pages/hour (0.58 pages/sec); the required 10× burst is 20,833 pages/hour (5.79 pages/sec). These are workload targets, not demonstrated capacity.

Kafka-lag KEDA manifests exist for document preparation, page detection, standard extraction, retry, validation, output, HITL, unstructured extraction, and disabled VLM fallback. Static inventory finds two independence gaps against the Phase 4 gate: classification and registration share page detection, while evidence and claim decisions share validation orchestration. Scale-out, scale-in, scale-to-zero, cold start, queue recovery, pod failure, and rolling deployment have not been cluster-validated.

Required next run: deploy production-like Redpanda, PostgreSQL, Redis, object storage, Prometheus, and KEDA; capture the complete matrix; then rerun the machine promotion gate. Field-level OCR latency must not be substituted for whole-pipeline throughput.
