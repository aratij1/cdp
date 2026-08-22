# CDP vNext Production Qualification

Qualification date: 2026-08-21  
Decision: **BLOCKED — DO NOT PROMOTE**

Machine-readable evidence can be regenerated with `python scripts/qualify_vnext.py`. The command
returns exit code 2 while any required gate fails or remains untested, making it safe for CI/CD.

## Reproducible results

| Gate | Result | Evidence |
|---|---|---|
| Full automated suite | FAIL | 544 passed, 5 skipped, 1 failed |
| Runtime architecture | PASS | Evaluation/worker imports removed from shared runtime packages |
| Local component performance | PASS/PARTIAL | 3 tests passed; 67 pages; preparation 2.15 pages/s |
| Frozen release integrity | FAIL | CMS-1500 threshold expected `a577e63f…`, actual `28f7f011…` |
| vNext governed accuracy | NOT TESTED | No locked vNext holdout execution |
| Live provider qualification | NOT TESTED | No RapidOCR model or Vertex/AWS execution |
| Cluster scaling/networking | NOT TESTED | No Kubernetes/KEDA/CNI environment |
| Security/PHI assessment | NOT TESTED | Structural controls only; no penetration or external approval |
| Restore/DR/rollback drills | NOT TESTED | Runbooks exist; drills not executed |
| Signed release evidence | NOT TESTED | No release authority/signing identity available |

The only failing automated test protects a frozen legacy release. Its manifest was deliberately not
rewritten: changing its recorded hash would conceal configuration drift. Reconcile the threshold file
through change control and issue a new governed version.

## Promotion gates

1. Resolve the frozen configuration drift with an auditable decision.
2. Run and sign a leakage-controlled vNext holdout evaluation.
3. Meter live provider and review costs under approved PHI/region policies.
4. Pass representative 10x burst, soak, backpressure and dependency-failure tests in Kubernetes.
5. Complete security, IdP, network-egress, retention, backup/restore, rollback and DR drills.
6. Obtain named release, clinical/operations, security and compliance approvals.

There are **7 implementation phases** (Phases 1–7; Phase 0 is baseline preparation). All seven have
now been implemented at code/artifact level, but Phase 7 correctly ends in a blocked production
decision until the environment-dependent gates above pass.
