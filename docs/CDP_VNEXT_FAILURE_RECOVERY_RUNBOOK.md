# CDP vNext Failure and Recovery Runbook

| Signal | Immediate containment | Diagnosis | Recovery gate |
|---|---|---|---|
| Critical false accept | Freeze promotion and downstream release | Inspect candidate, validation, reference and model versions | Corrected audit evidence, regression test, zero on holdout |
| Kafka lag above 5,000 | Preserve intake; prevent unsafe threshold changes | KEDA status, max replicas, partitions, DB/object latency | Lag declining for 30 minutes |
| Provider circuit open | Keep local path/HITL active; do not bypass gateway | Region, quota, latency, schema failures | Approved probe succeeds and budget remains |
| PostgreSQL unavailable | Stop consumers that would accumulate failed commits | HA status, connections, storage | Primary writable and outbox/review audit verified |
| Object store unavailable | Pause decode/OCR consumers | endpoint, credentials, KMS, capacity | Read/write/hash probe succeeds |
| Review backlog | Add trained reviewers; prioritize C3 | claim rate, route regression, staffing | C3 queue and p95 turnaround inside SLO |
| Bad model/template release | Disable feature flag and roll back image/config | shadow comparison and evidence drift | Previous version restored; replay quarantined cohort |

Never delete Kafka topics, audit rows, evidence crops or reference snapshots during incident recovery.
Replay uses original event identifiers and idempotency keys. Any recovery that changes a canonical
field must create new evidence; it must not mutate the prior decision record.
