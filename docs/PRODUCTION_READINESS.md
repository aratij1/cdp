# Production readiness gate

This document separates repository hardening from authorization to process
production healthcare data. Passing the code-quality gate does not by itself
authorize a production launch.

## Automated code gate

The following checks are mandatory on every pull request:

- architecture dependency validation;
- Python lint and unit/architecture tests;
- evaluation UI tests and production build;
- high/critical JavaScript dependency audit;
- secret and generated-artifact exclusions.

Current local verification:

- Python: 418 tests passed;
- evaluation UI: 3 tests passed and production build completed;
- JavaScript audit: zero known vulnerabilities;
- Compose configuration: valid;
- architecture and lint checks: passed.

GitHub Actions reproduces the code checks from a clean checkout.

## Release blockers

These items require implementation or an explicitly approved operational
control before processing production PHI:

1. Replace header-based RBAC with the organization's authenticated identity
   provider and enforce tenant claims at every API boundary.
2. ~~Wire validation failures to automatic review-task creation; no critical
   unresolved field may finalize without authorized reference evidence or an
   approved human decision.~~ (Wired via Phase 7)
3. ~~Complete and exercise the live validation, retry, VLM-escalation, and output
   consumer chain. Offline evaluation success is not a substitute for an
   end-to-end production event flow.~~ (Wired via Phase 7)
4. Apply versioned database migrations against a production-like Postgres
   environment and test backup, restore, retention, and deletion workflows.
5. Add deployment definitions for every live worker and validate Helm/KEDA,
   network policy, secret injection, resource limits, and rollback in a staging
   cluster.
6. Complete security/contract approval for any external OCR or VLM processing,
   including BAA, region, retention, diagnostics, key rotation, and cost limits.
7. Pass the frozen untouched holdout and canary gates defined in the evaluation
   policy. The current-sample benchmark is not an independent production
   generalization estimate.

## Launch evidence

A release record must contain:

- immutable application/config/model checksums;
- migration and rollback identifiers;
- holdout, false-accept, abstention, latency, and cost results;
- security and PHI-processing approvals;
- incident owner, dashboards, alerts, runbook, and rollback decision maker;
- canary scope and signed promotion decision.

Until every blocker is closed or formally accepted by the accountable owner,
the correct status is **production-hardened, not production-authorized**.
