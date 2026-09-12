# Frozen runtime candidate 5c32532

The immutable [candidate freeze](../candidates/5c325326c5f83247680b18f4340eab2ce56a2963.json) binds commit `5c325326c5f83247680b18f4340eab2ce56a2963` to its Git-derived runtime manifest, runtime profile, field/evidence/route/criticality/claim/reference/calibration configuration hashes, semantic-authority implementation and policy hashes, acceptance/STP implementation hash, and deployment pipeline digest.

Controller verification now reports:

```ini
qualification_candidate.status = PASS
qualification_candidate.freeze_integrity = PASS
qualification_candidate.runtime_changed_paths = []
controller.status = READY_FOR_EXTERNAL_INPUT
```

See [controller readiness](controller_readiness.json). The historical Track A freeze and the 1a85733 candidate freeze remain unchanged. This commit changes candidate selection, controller status reporting, deployment draft bindings, tests, and reports only; runtime implementation and policy bytes still match 5c32532. It does not create a new runtime candidate or restart the freeze cycle.

Before creating this freeze, six adversarial tests ran against isolated real Git checkouts. Verification rejected changed runtime code, changed semantic-authority policy, added runtime code, changed configuration bytes, changed recorded configuration hash, and wrong recorded candidate SHA. Recomputing a tampered manifest's own digest did not bypass reconstruction from the selected Git commit. See [validation receipt](validation_receipt.json) for tests and hashes.

The deployment draft now uses the selected candidate SHA and its exact pipeline digest. It remains `INVALID_CONTRACT` until the operator supplies the actual environment, jobs, service configuration, secure broker probe, and attestation. No network probes were performed. Governed input bytes were unchanged.

Engineering changes stop here unless a genuine defect is demonstrated. Remaining work is governed: confirm membership for all 150 pages; supply owner approval; activate valid independent reviewers and adjudicator; complete dual review and adjudication; freeze Track B truth; complete deployment and preflight; then run untouched Track B qualification. Owner-confirmed membership is currently 0/150, reviews and adjudications are zero, and truth is missing.

No OCR was invoked or tuned. The prior 10 format, 4 checksum, and 1 date failures remain diagnostics, not verified OCR errors. Accuracy, accepted precision, and production STP_SAFE are not claimed.
