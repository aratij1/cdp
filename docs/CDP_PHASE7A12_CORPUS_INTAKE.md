# Phase 7A.12 Controlled Corpus Intake

Status: **NEEDS_MORE_DATA**. No authorized assets were supplied in the working environment, so no source, PHI, usage, review, freeze, or LOSO claim has been made.

The controlled implementation is `evaluation/corpus_intake`. It reuses the Phase 7A.11 taxonomy, label-agreement, LOSO, route-truth, and runtime decision contracts. It does not discover local datasets, copy assets, train a model, or activate a router.

## Acquisition checklist

Each asset must have all of the following before it can enter review:

- an opaque asset/document/page identifier and a relative URI under an explicitly supplied controlled asset root;
- recomputable SHA-256, 64-bit perceptual hash, MIME type, readability, and page count;
- PHI status of `PHI_FREE`, `APPROVED_DEIDENTIFIED`, or `AUTHORIZED_CONTROLLED_TEST_DATA`, backed by evidence;
- usage status of `AUTHORIZED`, `PUBLICLY_USABLE`, `INTERNAL_APPROVED`, or `LICENSED_FOR_EVALUATION`, backed by an authorization reference;
- source family/instance, template, renderer, layout, acquisition, and degradation lineage;
- a source attestation reviewed by an accountable reviewer, with an exact source hash manifest and `PASS` independence status;
- taxonomy and route truth from blind review, with required second review and adjudication of disagreements;
- explicit split eligibility and no exact, near-duplicate cross-source, or related-lineage leakage.

Milestone A requires at least 500 qualified pages and four independent sources; at least 100 CMS and 100 UB pages from three sources each; at least 100 hard negatives; and at least 100 claim-support/non-claim/unknown pages. The mature target is 1,000–2,000 pages.

## Operator commands

Start with [the empty batch template](../config/phase7a12_corpus_intake_batch_template.json) and use [the field template](../config/phase7a12_corpus_intake_field_template.json) only as a field reference. Place no assets in Git.

```powershell
python -m evaluation.corpus_intake.cli --write-schema evaluation_results/phase7a12/intake.schema.json
python -m evaluation.corpus_intake.cli `
  --batch C:\controlled\phase7a12\intake.json `
  --asset-root C:\controlled\phase7a12\assets `
  --output-dir evaluation_results/phase7a12 `
  --reviewer-id reviewer-1 `
  --reviewer-id reviewer-2
```

`asset_uri` must be relative to `--asset-root`; absolute and parent-traversal paths fail closed. LOSO additionally requires `--loso-cases` with exactly one existing-runtime evidence case per qualified asset. The parity audit must pass before evaluation starts.
