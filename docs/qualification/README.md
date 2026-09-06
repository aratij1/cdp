# Production qualification closure

The current decision is **EXTERNAL_INPUT_REQUIRED / NO-GO**. Page binding is
150/150 exact. Release truth and production accuracy remain unavailable.
See `closure_status.json` and `closure_report.md` for the measured snapshot.
No production authority is activated by this workflow.

## Human review: start here

Open <http://127.0.0.1:8094/qualification-review/> on the review workstation.
The server is loopback-only. Sign in with the reviewer identity assigned by the
review coordinator. This local identity entry is not enterprise authentication;
the coordinator must supervise access and verify reviewer identities before
finalization. Do not expose this annotation server directly to a network.

Each reviewer independently transcribes the source. The view does not load CDP
predictions, OCR values or another reviewer's annotations. Select the field,
drag its source region, enter its value or explicit non-value state, and record
form, quality and claim-boundary observations. Alt+N advances fields;
Ctrl+Enter completes the page and advances. Drafts autosave and survive restart.
Completed reviews are immutable. Each critical field needs two independent
reviews; an independent authorized adjudicator resolves disagreements.

The initial eight-field review covers the selected critical extraction fields.
It does not silently stand in for a larger canonical claim denominator.
Release scoring requires the complete governed expected field list for every
included claim. A claim lacking any required reviewed/bound page is excluded
in full; partial claims do not count toward STP.

Copy `config/qualification_reviewer_registry.example.json` to the ignored
`evaluation_results/qualification_closure/reviewer_registry.local.json`.
The coordinator supplies the verified identities, adjudicators and governance
policy ID and sets `identity_verified` only after verification. Do not put
personal identities or review values in the committed example.

For a disagreement, the independent adjudicator signs in, opens the Adjudication queue link, or opens
`/qualification-review/adjudication/{zero_based_page_index}`. This view shows
the source and independent human conclusions, never CDP predictions. Submit
the field name and conclusion; metadata disagreements use `__metadata__`.
Review digests bind an adjudication to the exact immutable reviews.

## Running and resuming

From the repository root with the project virtual environment:

```powershell
.venv/Scripts/python.exe -m evaluation.reconstruct_source_bindings
.venv/Scripts/python.exe -m uvicorn evaluation.annotation_app.app:app --host 127.0.0.1 --port 8094 --no-access-log
```

In a separate terminal, run the automatic qualification watcher:

```powershell
.venv/Scripts/python.exe -m evaluation.qualification_closure --watch
```

Review completion also triggers refresh immediately. The watcher checks for
governed external inputs every five seconds. Invalid inputs cannot preserve a
previous GO. Refresh finalizes eligible truth, freezes a complete package-held-out
cohort, scores supplied actual canonical execution snapshots and updates the
existing `evaluation.final_qualification` reports. No extra approval prompt is
needed for those calculations. It neither manufactures predictions nor runs a
production deployment that is not configured.

## Required private execution inputs

Keep all following files under ignored
`evaluation_results/qualification_closure/`, outside Git:

- `claim_membership.local.json`: governed complete claim membership, boundary
  provenance and expected field keys. Page IDs reference the exact source binding;
  claim IDs must come from ingestion or independently confirmed boundaries.
  The present binding identifies existing CDP replay pages, not production
  database UUIDs. Production ingestion must retain that lineage.
- `raw_predictions.local.json` and `post_hitl_predictions.local.json`: sealed
  actual canonical pipeline snapshots, the same configuration and full field/
  claim denominator, execution provenance, `purpose: FINAL_GATE` and
  `used_for_tuning: false`. Raw outputs precede any HITL correction. Final outputs
  follow correction, revalidation and canonical `STP_SAFE` output generation.
  `packages/real_data_evaluation/release_scoring.py` defines the checked contract.
- `deployment_operational_evidence.local.json`: measured production deployment
  run ID, scoped release truth hash and database/events, load/KEDA, failure,
  security, outbox, revalidation and restart results. Unit tests are not a
  substitute. No deployment services were running during this closure run.
- `deployment_latency.local.json`: complete production page-path measurements,
  protected semantic equality, at least three warm repetitions and measured
  median warm P95. Include external authority work in the relevant production
  path. The retained workstation shadow benchmark is insufficient.
- `pricing.local.json`: copy the pricing example and enter contracted rates only.
  `measured_workload.local.json`: measured pages, claims, busy-hour throughput,
  utilization, GPU use and actual provider calls/tokens; the `Workload` dataclass
  defines its fields. Missing rates for used services remain `NOT_CONFIGURED`.

Use `packages/real_data_evaluation/blind_workflow.py:content_digest` for canonical
SHA-256 seals. Seals establish immutability, not the truth of self-asserted
provenance; the deployment operator must supply actual governed executions.
Never populate these files with synthetic passing claims. The immutable execution
ledger rejects changed scored holdout outputs; tuning requires a new governed
cohort. The old 500-document shadow cohort remains regression/readiness only.

The existing human-review API writes the correction and revalidation outbox in
one transaction. Validation recomputes canonical evidence. A `HUMAN_CONFIRMED`
marker alone cannot remove an unresolved authority requirement. The correction
audit persists, and the final decision remains blocked when evidence is missing.
Worker completion IDs suppress event redelivery; output keys, service-line IDs
and timestamps remain stable after a partial object write. Completion outbox
records must be retained for the full redelivery window.

## Target hardware qualification

Securely stage the existing private benchmark cache, immutable qualification
baseline and exact source TIFFs on the intended deployment host. Preserve asset
hashes and the fixed 12-page cohort. Install the governed dependency versions.
Use a new output directory for every run:

```powershell
.venv/Scripts/python.exe -m evaluation.production_latency_qualification --target-output evaluation_results/target_host_run1 --source-root D:/secure/source_b_1000_claims
```

This runs three isolated processes, each with a cold pass and a fresh warm pass,
and checks protected output fingerprints. It does not activate a new provider.
A measured-path pass still requires complete production-path qualification.
Do not repeat the rejected CPU/thread/resolution/accelerator experiments on this
workstation. `HOST_LATENCY_LIMIT_MEASURED` describes this measured host/configuration,
not a universal hardware ceiling.

Runtime reports, source bindings, TIFFs, OCR, review values and credentials remain
ignored. Only aggregate snapshots in this directory are committed. Historical
freeze documents retain their original meaning and hashes.
