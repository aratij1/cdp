# CDP vNext Deployment Guide

## Prerequisites

- Kubernetes 1.27+, Helm 3, KEDA 2.14+, a CNI enforcing NetworkPolicy
- PostgreSQL, Redis, S3-compatible storage and Kafka/Redpanda reachable through approved policies
- External Secrets or equivalent; never place credentials in Helm values
- OCI images pinned by immutable digest for production releases

## Order of operations

1. Back up PostgreSQL and apply migrations `002` then `003`.
2. Create the namespace and workload-identity bindings.
3. Create secrets out of band for database, broker, Redis and object storage.
4. Install API charts, then `cdp-worker-pools`.
5. Confirm every KEDA `scaleTargetRef` resolves and Kafka triggers report `Active/Ready`.
6. Import `grafana_vnext_dashboard.json` and load `alert_rules.yml`.
7. Run a canary tenant with external AI disabled, then enable only explicitly approved routes.

Example commands are intentionally non-secret:

```text
helm upgrade --install idp-ingestion deploy/helm/ingestion-api --namespace idp-claims-platform
helm upgrade --install idp-review deploy/helm/human-review-api --namespace idp-claims-platform
helm upgrade --install idp-workers deploy/helm/cdp-worker-pools --namespace idp-claims-platform
kubectl get deployments,scaledobjects,pdb,networkpolicy -n idp-claims-platform
```

## Scaling

Worker Deployments and KEDA objects are rendered from the same `workers` map. CPU pools retain one
warm replica on common-path stages; burst pools scale from zero. Scale-up permits 100% or four pods
per 30 seconds, while scale-down waits five minutes to avoid churn. Never raise maximum replicas
without checking PostgreSQL connections, broker partitions and object-store request capacity.

## Rollback

Disable external AI and stop new ingestion first. Roll worker images back before APIs. Database
evidence columns are backward compatible and should not be dropped. Confirm lag drains, audit writes
continue, and critical false accepts remain zero before reopening intake.
