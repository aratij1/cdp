# CDP Failure-Injection Report

Promotion status: `NOT_RUN`; gate not satisfied.

Unit contracts currently verify missing route registry rejection, evaluation-route rejection in runtime, immutable/tamper-evident holdout and frontier manifests, malformed governed models, shadow failure isolation, canonical retry/output convergence, and transactional-outbox domain behavior. Those checks are useful but are not a production-like fault campaign.

The required OCR timeout/crash, Kafka unavailable/duplicate/out-of-order, PostgreSQL unavailable, Redis unavailable, slow object storage, worker restart, poison event, malformed candidate, missing policy, and missing route registry matrix was not executed after the holdout gate blocked the ordered run. Therefore no claim is made for zero data loss, duplicate claims/tasks, queue recovery, or DLQ/operator replay under those faults.

Before promotion, run the matrix against the same production-like stack used by the load test and prove: no silent acceptance, no duplicate canonical claim, no duplicate review task, no data loss, bounded retries, durable DLQ, and deterministic replay.
