# Runtime field policy coverage and saved-output replay

All 178 supported runtime field/family combinations now have explicit canonical identity, criticality, required/optional status, versioned validation, evidence requirements, and disposition policies. Coverage is derived from active templates, unstructured schemas/labels, and approved OCR routes. Configuration completeness is not automation approval.

The new runtime profile is `cdp-runtime-decision@field-policy-coverage-v1`. Existing acceptance rules and thresholds are preserved. Evidence, routing, criticality, claim, reference, and calibration configuration hashes are unchanged. Previously uncovered fields explicitly require human review. Generic review-only document families cannot obtain STP, including empty-field cases.

Runtime factory construction rejects incomplete coverage. The ingestion readiness endpoint returns HTTP 503 / `CONFIGURATION_INCOMPLETE` for invalid configuration. Per-field missing-policy handling also remains fail-closed.

## Same 12 scans: saved OCR disposition replay

The replay used the original saved candidates and provenance, the original evaluation date, and the recorded document families. No scans were opened and no OCR/model calls occurred. The saved execution SHA-256 was identical before and after replay. This is a disposition replay, not a new end-to-end OCR run.

| Measure | Fields |
| --- | ---: |
| Extracted | 21 |
| Auto-eligible | 0 |
| Missing policy | 0 |
| Validation blocked | 15 |
| Detected semantic contradictions | 0 |
| Semantic authority unverified | 21 |
| Independent confirmation required | 19 |
| Authority required | 21 |
| Authoritative reference required (subset) | 13 |
| HITL required | 21 (100%) |

Blocker categories overlap. Zero detected semantic contradictions does not establish semantic correctness. Validation failures are not accuracy errors against trusted labels. No automatic claim passage is established by this field-only replay. Field accuracy, critical-field accuracy, accepted precision, critical accepted precision, false accepts, claim HITL, and production `STP_SAFE` are not measured here. Trusted labels and claim-level qualification remain necessary.

## Validation and frozen receipt

See [validation_receipt.json](validation_receipt.json) for final unit, architecture/integration, Ruff, governed mypy, and repository safety outcomes, artifact hashes, and code/configuration manifest. Full unit coverage includes semantic authority parity and runtime-versus-truth STP integrity checks. [policy_coverage.json](policy_coverage.json) contains the explicit field matrix; [disposition_replay.json](disposition_replay.json) contains aggregate replay results. No extracted values are published.

## Qualification status

The field-policy engineering gate is complete. The overall `CODE_READY_FOR_TRACK_B_QUALIFICATION` milestone remains conditional: the read-only controller reports a stale Track A runtime freeze and an invalid deployment contract as well as outstanding external governed inputs. Historical freezes were preserved; they were not relabeled as approving this new runtime.

Owner membership has 0 of 150 rows confirmed, owner approval is missing, reviewer registration is invalid, completed independent reviews and adjudications are both zero, and frozen truth is missing. These must be supplied through the governed process. See [track_b_input_status.json](track_b_input_status.json). No approvals, membership, review records, or truth were created or modified. Production readiness is not claimed.

Performance optimization remains deferred. The original roughly 155.8-second unstructured extraction and 79.0-second routing measurements are historical timings, not replay timings.
