# Kafka-lag autoscaling

The individual `ScaledObject` examples in this directory are retained for direct-manifest deployments. The production-oriented source is the consolidated `deploy/helm/cdp-worker-pools` chart, which renders a Deployment and matching KEDA `ScaledObject` for every configured, importable consumer entrypoint.

Current chart pools are document preparation, page detection/registration, standard-form OCR, retry, validation/evidence, output generation, and human-review task creation. Retry and output can scale to zero; the primary path retains warm capacity. Scale-up is aggressive and scale-down is stabilized to avoid runtime churn.

Run `python -m evaluation.validate_scalability` to verify the 1k/10k/50k workload tiers, required telemetry fields, module entrypoints, replica bounds, topics, and lag thresholds.

This preflight does not prove cluster capacity or validate installed CRDs. Before production, render the Helm chart, validate it against the target Kubernetes/KEDA versions, then execute all load tiers with Kafka, PostgreSQL, Redis, object storage, Prometheus, OpenTelemetry and Grafana enabled.
