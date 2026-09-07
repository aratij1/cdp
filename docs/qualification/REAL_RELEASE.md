# Real CDP qualification

The current real-data scorecard is generated at
`evaluation_results/real_release/release_scorecard.md` and `.json`.
It is pending human review; no accuracy, HITL or STP measurement exists yet.

## Frozen candidate

Repository: https://github.com/ashishdat/CDP
Branch: `closure/cdp-target`
Latest fetched remote candidate: `55b4c10ad91e1e3a7bf478b1d63be01d406680d7`.
A clean detached candidate checkout is retained at
`.runs/real-release-candidate-55b4c10`. No candidate files are modified by this
measurement work. The working branch already contained a later local closure
commit and pending control-plane work; these are preserved separately.
`origin` refers to a different repository and has no requested branch; the
matching repository is the `ashishdat` remote. Both remotes were fetched.

## Human inputs that enable measurement

1. A coordinator verifies two independent reviewers and an independent
   adjudicator and supplies `reviewer_registry.local.json` with the existing
   example contract. The coding assistant cannot supply those identities or
   verify human independence on the coordinator's behalf.
2. Reviewers transcribe the unchanged 150-page source-only cohort at
   <http://127.0.0.1:8094/qualification-review/>. VALUE, BLANK, UNREADABLE,
   NOT_PRESENT, SOURCE_CONFLICT and NOT_APPLICABLE are valid observations.
   Existing governed comparison rules determine agreement; source values are
   never replaced by CDP predictions. The eight fixed reviewed fields are all
   governed critical fields; noncritical metrics remain unavailable unless a
   separately governed complete field contract supplies such records.
3. The data owner supplies complete claim membership. Each claim requires
   `package_id`, `page_ids`, `claim_form_page_ids`, `attachment_page_ids`
   (explicitly empty where none), `expected_field_keys`, and a `documents`
   mapping. Each document names its `page_ids`, boundary `CONFIRMED` or
   `GOVERNED`, and `boundary_provenance`. Global `governed`,
   `complete_claim_membership_confirmed`, and `boundary_provenance` are required.
   Do not infer boundaries from adjacency. Missing or conflicting scope excludes
   the claim from measurement.
4. The deployment owner configures the actual frozen candidate execution and
   supplies `deployment_attestation.local.json`: `governed: true`, an actual
   `approval_reference`, `deployment_id`, `candidate_commit_sha` and
   `pipeline_configuration_sha256`. `cdp_services` repeats the matching identity
   and supplies `deployment_attestation_sha256` using `content_digest`.
   This is governed owner evidence, not a claim that the local harness inspected
   remote deployment binaries. Existing authority providers remain fail closed.

All private inputs live under `evaluation_results/qualification_closure/`.
Never commit review values, patient/provider identifiers, images, OCR text,
credentials, source TIFFs or detailed execution snapshots.

## Automatic qualification

The existing watcher calls `evaluation.real_release.build` after every refresh
and after input invalidation. It checks review integrity continuously and records
milestones at 10, 25, 50, 100 and 150 reviewed pages. Checkpoints validate workflow;
they never publish interim production accuracy or authorize extraction tuning.

Once governed reviews, adjudications, complete membership and exact binding are
available, it freezes release truth and runs the configured RAW executor. The
raw snapshot must match the pinned candidate and the full bound denominator.
Automatic acceptance excludes human-routed fields. STP requires explicit safe
output completion, all required field/evidence gates and zero human intervention.
The separate HITL_FINAL executor waits for actual corrections, canonical
revalidation and the corresponding output-completion event. Corrected claims
remain HITL_CLOSED, not STP. No source truth is read by execution capture.

The publisher writes all requested real_release artifacts, plus review
checkpoints, error categories and cost-usage context. Each metric has integer
numerator/denominator counts; unavailable observations are null, not fabricated
zeros. Claim outcome partitions and field denominators must reconcile before
metrics publish. Frozen public truth metadata contains hashed IDs, provenance
hashes, timestamp and a content seal; it cannot be rewritten after invalid input.

Wilson 95% intervals are descriptive binomial intervals. Fields within claims
are correlated, and this selected cohort cannot establish population certainty.
Raw accuracy and critical-field HITL have no separate numerical gate in the
existing frozen closure contract; no new threshold is invented. All existing
final accuracy, accepted precision, false-accept, HITL, STP, latency and paid-AI
thresholds are retained. Latency and missing pricing never prevent truth scoring.

The cached replay's zero paid-AI observation remains explicitly separate from
production costs. Total production cost remains NOT_CONFIGURED without measured
workload and contracted rates. Unobserved HITL ownership and error causes remain
UNKNOWN/UNCLASSIFIED; the harness does not guess explanations or tune extraction.

To refresh manually without changing labels or candidate code:

```powershell
.venv/Scripts/python.exe -m evaluation.real_release
```

The watcher handles the same command path automatically; no further coding prompt
is needed when the governed inputs arrive.
