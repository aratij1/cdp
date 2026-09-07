# Track B operator input contract

Candidate: `2a310ed51720b854cca99d361940eb929027e529`. Track A runtime, comparators, thresholds, architecture, and sealed engineering evidence remain frozen.

## Source owner: Ashish Singh

Edit only the existing `evaluation_results/real_release/150_cohort_missing_membership.csv`. This remains the sole owner-editable membership input. The initial six lineage columns are sealed and must remain unchanged. Aliases map privately through `evaluation_results/qualification_closure/blind_lineage_alias_lookup.local.json`; do not put patient names, member IDs, or Patient Control Numbers in the CSV.

For each page, fill:

| Column | Contract |
|---|---|
| claim_alias_to_fill | Stable opaque claim alias, letters/digits/underscore/hyphen only. |
| document_alias | Stable opaque document alias; a document cannot belong to multiple claims. |
| page_role | CLAIM_FORM or ATTACHMENT. |
| claim_page_order | Consecutive integers starting at 1 within the complete claim. |
| owner_confirmation | CONFIRM, CORRECT, or AMBIGUOUS. |
| membership_status | EXACT, AMBIGUOUS, or UNBOUND. |
| membership_provenance | Owner evidence reference establishing boundaries and complete membership. |
| owner_approved_at | Actual approval time in ISO 8601 with UTC offset. |
| claim_complete_confirmed | YES only after confirming the complete claim is represented. |

CONFIRM and CORRECT require all fields above and EXACT status. Before EXACT membership can be published, Ashish Singh must supply `evaluation_results/qualification_closure/membership_owner_approval.local.json` using `config/qualification/membership_owner_approval.example.json`: owner_id must identify Ashish Singh, owner_role must be SOURCE_DATA_OWNER, csv_sha256 must bind the exact completed CSV bytes, and approved_at must be timezone-aware and not in the future. An actual approval_reference and policy_id are required. CSV strings alone do not establish owner authority. For unresolved pages use AMBIGUOUS or UNBOUND; never infer claim membership from source container adjacency. Owner confirmation establishes membership only, never field truth.

The existing controller consumes these edits, validates sealed lineage, unique pages, source bytes, source/package consistency, document boundaries, complete field scope, and Track A isolation. Once all 150 pages form complete EXACT claims it immutably publishes the private execution membership. Partial approval cannot authorize release scoring. `evaluation_results/real_release/track_b_claim_membership.json` and `track_b_claim_membership_report.json` contain aliases/counts only. Subsequent edits cannot silently replace approved membership.

## Reviewer registration operator

Populate `config/qualification/reviewer_registry.yaml` only after identity verification. Set the real policy reference and each entry's reviewer_id, REVIEWER or ADJUDICATOR role, enabled, independence_group, qualification_scope containing TRACK_B_150, effective_from, effective_to, provenance, and access_token_env (an operator-provisioned environment-variable name only). Times must carry a timezone. Enable at least two different reviewers and an independent adjudicator. Every enabled assignment must have a distinct identity and independence group. Set identity_verified only after the operator's actual verification. Source ownership does not register Ashish Singh as a reviewer.

The YAML is the sole reviewer authority. The controller projects valid initial registration into the private registry, including contract_sha256. Every consumer validates the current YAML and exact cache projection before trusting it. Missing/invalid YAML, expired assignments, or a changed contract hash disables authority while preserving observations. A stale active cache is never silently replaced. After an approved policy change, the registration operator must archive the old private cache and remove that cache file; the controller can then project the current valid contract. Existing sessions must sign in again. Access-code removal or rotation also revokes prior write sessions. Cached registries are diagnostic only without a valid matching current contract.

## Registered reviewers and adjudicator

Use the existing http://127.0.0.1:8094/qualification-review/ application. Sign in with the operator-assigned identity in the governed local review environment. The operator must provision a separate assigned access code for each enabled identity through its access_token_env variable in the review-server environment. Governed sign-in requires both identity and code. The operator remains responsible for independently verifying those identities; codes are not stored in the registry or repository. Reviewer pages show source images and only the current reviewer's observations. Drafts autosave and resume; Alt+N advances a field, Ctrl+Enter completes the page and moves next. Use the second-review queue and independent adjudication queue.

Allowed observations: VALUE, BLANK, NOT_PRESENT, UNREADABLE, SOURCE_CONFLICT, NOT_APPLICABLE. A value requires source-region evidence. Do not resolve disagreements using CDP predictions. Adjudication requires a reason and cannot use either original reviewer. Completed reviews are immutable; identical retries preserve the original review timestamp.

The private review database stores observations. The private provenance journal records source hash, page identity, reviewer identity, review round, timestamp, version, observations/digest, and adjudication reason. Nothing in those databases is intended for Git. The controller requires matching provenance before truth freeze and writes an immutable Track B truth-freeze receipt containing candidate, cohort, membership, truth, review and adjudication hashes.

## Deployment owner

Populate `config/qualification/deployment_control.yaml` with the designated host/environment, execution provider, deployment ID, approval reference, pinned candidate attestation, service scope/configuration digest, ingestion endpoint and tenant. Provision secrets through the named environment variables in the controller/executor environment; never put values in the YAML or logs. Restart the relevant service after provisioning or rotating its environment variables so the running process receives them.

Canonical runtime names are DATABASE_URL, KAFKA_BOOTSTRAP_SERVERS, OBJECT_STORE_ENDPOINT, OBJECT_STORE_ACCESS_KEY, and OBJECT_STORE_SECRET_KEY. CDP_QUAL_AUTHORITY_CONFIG and CDP_QUAL_PRICING_CONFIG name paths to owner-provided configurations; no canonical equivalents were found in shared settings. Authentication for the ingestion service uses its configured authorization_env variable name. The required broker_probe contract contains argv, executable_sha256, timeout_seconds (1..60), and required_env variable names. Supply the deployment-owned probe that implements the actual TLS/mTLS, SASL/SCRAM, OAuth or other configured Kafka security. It inherits the configured process environment, reports success by exit status, and has stdout/stderr suppressed. There is no built-in unauthenticated or plaintext fallback, no certificate-verification override, and no security settings are stripped. Missing required probe variables block connectivity before any service call.

Contract preflight first validates the exact candidate SHA, qualification environment, service deployment identity, pipeline hash, ingestion URL/tenant/authorization variable, all five job executable paths/hashes, three UB canary fingerprints, and the actual deployment_attestation.local.json digest and matching approval reference. No external service is contacted until this passes. Connectivity then checks required variable presence, authority/pricing configuration availability, database SELECT 1, the governed broker probe, and S3 connectivity. Active deployment configuration is published only after both stages pass. Contract status is VALID or INVALID; connectivity status is PASS, MISSING, or UNREACHABLE. Invalid contracts remain INVALID_CONTRACT and cannot launch jobs. Connectivity PASS does not certify operational resilience or security. Owner-governed pricing must populate the existing pricing schema at `evaluation_results/qualification_closure/pricing.local.json`; unknown rates remain NOT_CONFIGURED.

Configure the existing job contract for TARGET_LATENCY, OPERATIONAL_PREFLIGHT, RAW, OPERATIONAL, and HITL_FINAL. Each `jobs.<PHASE>` requires an explicit `argv` list beginning with an absolute executable path and that executable's `executable_sha256`. No shell command is inferred. Each job may set max_attempts from 1 to 5; absence means one attempt. The existing controller uses `evaluation.track_b_jobs.advance` to preserve the frozen runtime job contract while adding durable recovery. Per-attempt submitted/running/failure records retain request ID, executor/configuration hashes, deployment ID, PID identity and timestamps. Concurrent refreshes share an OS-released SQLite launch lock. A definitely dead executor becomes EXECUTOR_FAILED; the identical request can retry only within its configured bound. Unknown or historical PID-less launch state blocks automatic retry. A valid receipt always takes precedence over markers and is never rerun. The controller appends `--qualification-request` and `--qualification-receipt`; the executor must honor the immutable request ID and produce hashed evidence plus a sealed receipt. The deployment owner supplies commands appropriate to the actual environment, including approved restart/failure-injection controls. Existing `evaluation/deployment_control_executor.py` implements RAW and HITL_FINAL against deployed services; it does not implement latency or infrastructure restart jobs.

TARGET_LATENCY must emit complete-production-path measurements for a cold pass and at least three isolated warm repetitions, runtime/CPU/GPU/provider/memory evidence, governed UB canaries, baseline digest, semantic equality, and per-page latency. The existing validator checks percentile/throughput arithmetic and median warm P95 <= 5 seconds/page. The local target-host benchmark alone does not certify the complete deployed path.

Operational evidence must cover the existing database, broker, outbox, retry, dead-letter, worker/database/broker restart, load/concurrency, security/authorization/secret-management, audit/PHI, observability and backup gates. Include actual partial-output resume and duplicate event/output protection evidence with zero lost claims and duplicate outputs. Test doubles and unit-test results cannot populate these deployment gates.

## Automatic continuation

The existing `evaluation.qualification_closure --watch` remains authoritative. No review application or alternate controller was created. Owner CSV approval, registry updates, completed reviews, adjudication, deployment inputs, execution receipts, and pricing are re-evaluated on refresh. Complete EXACT membership and source/package integrity precede truth freeze. Raw and post-HITL metrics remain separate; corrected claims cannot become true STP. Qualification uses the pinned candidate and existing frozen comparators. Failed or unavailable release gates are not waived.

The current aggregate final report is `docs/qualification/track_b_completion/CDP_TRACK_B_FINAL_QUALIFICATION.md`. Actual owner approvals, independent reviews, deployment execution commands/access, and pricing are external inputs; software cannot manufacture them.
