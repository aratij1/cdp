# CDP scalability report

Status date: 2026-08-22. Deployment definitions and static preflight pass; full-cluster capacity remains unproven.

## Architecture

FastAPI ingress and HITL APIs each start with two replicas. Seven independently scalable Kafka consumer pools cover document preparation, page detection/registration, primary standard-form OCR, field retry, validation/evidence, output generation and HITL task creation. The Helm chart creates the Deployments and KEDA ScaledObjects together, using consumer lag, bounded replica ranges, rapid scale-up, stabilized scale-down, fallback replicas and scale-to-zero for eligible exception pools.

Pods run non-root with dropped capabilities, read-only root filesystems, resource requests/limits, bounded temporary storage, service-account token mounting disabled and default-deny network policy with scoped platform egress.

## Load qualification contract

Versioned tiers are 1,000, 10,000 and 50,000 pages, with a 10x burst objective. Each run must record pages/second, documents/hour, P50/P95/P99 latency, CPU, memory, Kafka lag, database connections and transactions, Redis hit ratio, object-store throughput, AI calls, review rate and total cost. Default gates are <=1% errors, <=30 seconds P95 end-to-end latency and <=30 minutes backlog drain; environment-specific SLOs may be stricter.

The static preflight validates that every configured worker module is importable and every scaler has a topic, lag threshold and valid replica range. New Prometheus contracts cover database connections/transactions, Redis hits/misses, object-store bytes and worker CPU/memory utilization without PHI-valued labels.

## Measured evidence

Only a local field-OCR component test has been measured previously: concurrency 4 achieved approximately 11.33 fields/second with P95 434.56 ms and zero execution errors. It excluded Kafka, PostgreSQL, Redis, object storage, Kubernetes, KEDA, cloud AI and failure recovery. It is not evidence that the full pipeline supports 50,000 pages/day.

No 1k/10k/50k cluster run was executed in this environment. KEDA reaction, database saturation, Redis behavior, object-store throughput, autoscaling cost and recovery remain release blockers. Decision: `NEEDS_MORE_DATA`.
