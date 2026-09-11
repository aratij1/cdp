# CDP Security Readiness & Residual Risk Document

## Executive Summary
This document registers known architecture assumptions and residual security items for production deployment of the Claim Document Processing (CDP) platform.

---

## Registered Residual Risk: API Role-Based Access Control (RBAC) & Identity Propagation

### Context
In local development, automated integration testing, and sandbox staging, human review endpoints (e.g. `/review-tasks/{task_id}/correct`, `/review-tasks/{task_id}/escalate`, `/claims/{claim_id}/approve`) may accept client-supplied identity context (such as `reviewer_id` or `X-User-Role` development headers) to simulate multi-role operator interactions without requiring an active identity provider (IdP).

### Security Risk in Production
If deployed to a public or semi-trusted network without an intervening authenticated reverse proxy / API Gateway, malicious actors or compromised internal clients could attempt to forge headers or claim reviews without proper cryptographic attestation.

### Production Mitigation Requirements
Before promoting CDP to production healthcare enterprise environments (HIPAA / SOC 2 Type II compliance):
1. **API Gateway Enforced OIDC/JWT Validation**: An enterprise API Gateway (e.g., AWS API Gateway, Envoy, Kong, or Azure API Management) must validate cryptographically signed JSON Web Tokens (JWT) from the corporate IdP (e.g., Okta, Ping Identity, Azure AD).
2. **Header Stripping**: The gateway must strip any untrusted incoming client headers (e.g. `X-User-Role`, `X-User-Id`) and inject authenticated claims extracted from the verified JWT before forwarding to internal CDP microservices.
3. **Internal Mutual TLS (mTLS)**: Microservices communicating within the internal cluster (Ingestion API, Validation Worker, Human Review API) must use service-to-service mTLS or private VPC service meshes to prevent unauthorized lateral movement.
4. **Audit Trail Immutability**: All human review actions (`HUMAN_CONFIRMED`, `ESCALATE`) are logged with authenticated reviewer IDs and persisted in append-only audit outbox tables.
