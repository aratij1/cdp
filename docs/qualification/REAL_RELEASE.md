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

## Claim execution monitoring

The existing publisher also maintains `claim_execution_manifest.json` with
hashed claim/package/page IDs, declared page sequence and completion flags for
truth, prediction, validation, evidence, authority, decision and output.
Unknown completion remains null. Claims are marked ELIGIBLE, INCOMPLETE_TRUTH,
INCOMPLETE_MEMBERSHIP, INCOMPLETE_EXECUTION or EXCLUDED. This manifest monitors
readiness; it does not remove human-routed claims from raw HITL/STP denominators
because their final output or authority resolution is still pending.

Frozen truth metadata explicitly seals the source-binding and claim-membership
inputs. Source values and original IDs remain private. Canonical validation and
decision completion are captured from actual validation events; authority
completion requires explicit evidence and is never inferred from missing fields.

## Operational review and automatic claim inventory

The source-only UI provides an independent second-review queue at
`/qualification-review/second-review-queue`. It requires a verified authorized
reviewer and never reveals the first reviewer's values. Save responses refresh
progress; complete reviews also trigger qualification immediately. Progress
includes hashed reviewer cohort coverage, trusted complete-page fields, remaining
independent page-review actions and adjudications. Trusted reviewed fields are
reported separately from frozen release labels. No minutes-to-completion estimate
is invented without observed review duration.

The existing watcher calls `evaluation.claim_inventory.build` on every refresh.
It accepts complete explicit governed membership from the existing private
`claim_membership.local.json`, or the owner-supplied `package_manifest.local.json`,
`ingestion_lineage.local.json`, or `document_manifest.local.json` in the same
qualification directory. Full document boundaries, declared page sequence,
claim-form/attachment relationships and expected fields are mandatory. Conflicting
manifests fail closed; automatic materialization never overwrites owner input.
No package-to-claim rule, identity, or adjacency boundary is invented.

`claim_inventory.json` distinguishes EXACT, AMBIGUOUS and UNBOUND known claim
identities. With no identities supplied, claim counts are zero inventory entries,
not a claim that the source contains zero claims. The pre-owner-confirmation audit covered
150 pages in 88 packages and found no governed claim mapping for that cohort. All 150 pages
therefore remain without exact claim membership. The metadata search found no
governed complete claim mapping among 74 candidate JSON metadata files.

Current validation: 107 focused tests, Ruff and scoped mypy pass. The read-only
operational smoke verifies all 150 HTML shells, PNG decodes and frozen source pixel
bindings without accessing the review database. Synthetic isolated API and Node
DOM tests exercise saving, resuming, keyboard navigation, second review and
adjudication. They are workflow tests, not human truth or production accuracy.
Browser visual rendering and browser network inspection were not verified.

Start verified reviewers in the existing qualification-review UI.

## Source-owner-confirmed membership (2026-09-07)

Ashish Singh confirmed image-file occurrence sequence against DATAMATICS claim
sequence for the supplied Groups A-D. The later explicit clarification permits
UB Record 91 to be absent under the supplied specification: validate 20 through
90 and include 91 when present. This establishes lineage only, never field truth.

The watcher now revalidates the sealed workbook, output files, specifications,
owner confirmation, source hashes, package-local sequence, complete image/count
sets, claim boundaries and control-number consistency on each refresh. It matches
presentation filename aliases only when original image bytes match the workbook
hash. Patient Control Numbers and detailed source mappings stay in ignored local
evidence. Changes invalidate membership; original pinned evidence is not resealed
automatically. The local input is `owner_sequence_input.local.json` under
`evaluation_results/qualification_closure`; source results are published as
`source_claim_membership_report.json` and nested in the existing claim inventory
and claim binding report. Existing top-level cohort counts retain their scope.

Measured source membership: A 12/12, B 5/5, C 6/6, D 7/7 EXACT: 30 claims from
30 TIFF files, 67 frames, five packages. No ambiguous or unbound source claims.
All source hashes and governed control references passed; no field truth created.

The frozen 150-page review cohort uses `evaluation_data/source_b_1000_claims`,
whereas the confirmed workbook covers `dataset_raw`. Their source asset hashes
have zero overlap. Page binding remains 150/150; claim membership coverage of
that cohort remains 0/150. The A-D owner confirmation cannot authorize a different
source set. The frozen review cohort was not replaced or expanded.

Reviewers can continue at http://127.0.0.1:8094/qualification-review/ once the
verified reviewer registry is supplied. Qualification still requires governed
membership for the actual review cohort, blind field reviews and governed
execution/deployment inputs. A-D membership is established; real release metrics
remain NOT_EVALUABLE. No extraction, OCR, threshold or scoring changes were made.

Validation: 1,755 unit/architecture tests passed; all five fixed-width golden
tests passed with canonical output bytes unchanged. Ruff and scoped mypy passed.
Human corrections/revalidation were exercised by existing synthetic workflow
tests, not by fabricating a real reviewer or production correction.

The two-track watcher now publishes governed-30 engineering measurements and
preliminary blind field metrics separately. See [TWO_TRACK_CLOSURE.md](TWO_TRACK_CLOSURE.md)
for measured failures, the 47-page reserved holdout denominator and owner lineage request.
