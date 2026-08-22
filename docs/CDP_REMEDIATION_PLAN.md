# CDP remediation plan

## Promotion invariant

No component except `EvidenceDecisionService` may assign a machine-accepted field disposition. Provider, retry, validation, reference, and AI components only create evidence. Every unit requires runtime/evaluation parity tests and zero critical-false-accept regression.

## Ordered work

| Order | Unit | Acceptance evidence | Status |
|---:|---|---|---|
| 1 | Canonical decision contracts/service | critical evidence, contradiction, wrong-crop and non-blocking tests | implemented |
| 2 | Persist OCR candidates and wire live validation | round-trip mapper test; validation cannot bypass policy | implemented |
| 3 | Route evaluation through the same service | identical context produces identical disposition/reasons | implemented, parity suite pending full regression |
| 4 | Converge retry and output | retry only appends candidates; decision service controls requeue/HITL; output accepts canonical terminal dispositions | implemented |
| 5 | PreprocessingRouter | at most two reason-selected variants with CPU/value metrics | pending |
| 6 | Live UB-04 engine and Bundle D consumer | event contract/integration/golden tests | pending |
| 7 | Reference adapters and governed values | snapshot/REST/Postgres contracts; contradiction and lineage tests | pending external records |
| 8 | Shared persistence package | workers no longer import application DB modules; Alembic forward/rollback | pending |
| 9 | OIDC/RBAC and service identity | issuer/audience/tenant/RBAC negative tests | pending |
| 10 | DLQ/replay, staging scale, restore/security/holdout | failure injection, 1k/10k/50k evidence and signed gates | environment dependent |

## Immediate next change

Implement `PreprocessingRouter` so retry chooses at most two reason-specific variants and records CPU time, review reduction, and marginal accuracy. In parallel, add the missing Bundle D consumer and wire the specialized UB-04 service-line engine into live orchestration; both must use the canonical decision service.
