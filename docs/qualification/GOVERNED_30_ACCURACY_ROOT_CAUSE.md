# GOVERNED 30 ACCURACY ROOT-CAUSE

Final status: **MIXED_CAUSES**. All 124 original comparisons and all 123 original mismatches are accounted for. References remain **ENGINEERING_REFERENCE_ONLY**; these are not blind human-truth or release-qualification results.

Original raw accuracy was **1/124 = 0.81%**, with critical accuracy **1/86 = 1.16%**. Reconciled raw accuracy is **1/118 = 0.85%**; critical accuracy remains **1/86 = 1.16%**. The six excluded UB service-date slots are not critical under the frozen policy. No additional match was created.

| Mismatch primary cause | Count |
|---|---:|
| Reference mapping | 102 |
| Reference parsing | 0 |
| Claim alignment | 0 |
| Form alignment | 14 |
| Normalization | 0 |
| Comparator | 0 |
| Reference not comparable | 0 |
| Candidate missing | 0 |
| Wrong candidate | 0 |
| Extraction wrong | 6 |
| Validation/selection | 0 |
| Other | 1 |

Counts total **123**. Each mismatch has exactly one primary cause. The correctly extracted field remains included and is still routed to HITL.

**Denominator reconciliation:** 124 original mapped fields minus zero wrong semantic mappings, zero invalid parsed references, and six ambiguous references equals **118**. Those six are `CLM_C_001` through `CLM_C_006`, `service_date`: UB record 20 defines a statement-period start, while CDP exposes a statement period and lacks a governed projection to a single header service date. They are marked `AMBIGUOUS_MAPPING`, not silently remapped. All 102 genuinely missing supported candidates remain failures. Unsupported extraction capability alone is not a reason to exclude a field; insured-name failures remain included.

**Reference and alignment evidence:** 30/30 owner-confirmed source-to-output-to-CDP bindings passed source hashes, complete frame membership, record boundaries, control checks, contiguous owner sequence, and nonoverlapping output ranges. Optional UB record 91 follows the owner-approved rule. NSF references pair only with governed CMS claims; UB references pair only with governed UB claims. All 25 mapped component positions/pictures were checked against the sealed original specifications; independent character enumeration reproduced 124/124 available reference values across 130 occurrences. No one-character offset was found.

Implied cents, component names, record selection, dates, continuation records, leading zeros, blanks, and numeric zeros were checked. All 30 monetary observations are digit-only, with no all-zero totals or explicit signed representation. Unsupported overpunch is rejected rather than guessed. Blank output does not establish source-blank truth; conflicts and unavailable references remain excluded under the existing contract.

**Normalization and candidate selection:** existing comparators were retained. Raw and stored-normalized predictions have identical match outcomes. All five emitted charge values fail the existing monetary syntax contract; none is a simple cents-scale discrepancy. `CLM_A_005/patient_name` has label contamination. `CLM_D_006/patient_name` has one matching unselected alternative among three; the selected value remains wrong. The other 14 emitted mismatches have no matching stored alternative. This proves failure at the emitted/selected candidate boundary, not a standalone character-level OCR accuracy rate.

| Field | Original | Comparable | Correct | Missing candidate | Wrong selection | Wrong extraction | Not comparable |
|---|---:|---:|---:|---:|---:|---:|---:|
| insured_name | 26 | 26 | 0 | 26 | 0 | 0 | 0 |
| member_id | 20 | 20 | 0 | 19 | 0 | 1 | 0 |
| patient_dob | 6 | 6 | 0 | 6 | 0 | 0 | 0 |
| patient_name | 30 | 30 | 1 | 20 | 1 | 8 | 0 |
| principal_diagnosis | 6 | 6 | 0 | 6 | 0 | 0 | 0 |
| service_date | 6 | 0 | 0 | 0 | 0 | 0 | 6 |
| total_charge | 30 | 30 | 0 | 25 | 0 | 5 | 0 |

The detailed matrix also groups failures by form, reference record, normalizer, comparator, and claim. All 26 insured-name slots and 19 of 20 member-ID slots lack emitted candidates. UB contributes 28 missing candidates, two wrong emitted values, and six ambiguous service-date comparisons. The 22 observed validated claims carry runtime form `UNSTRUCTURED`; that production routing behavior is separate from reference-pairing validity and output completion.

| Field routing, original 124 slots | Count |
|---|---:|
| Auto accepted | 0 |
| HITL | 16 |
| Rejected | 0 |
| Not emitted | 102 |
| Not eligible | 6 |
| Unknown bug | 0 |

All 108 formerly unknown slots have no emitted canonical field, including alias and service-line checks. Six now have ineligible reference semantics; 102 are proven not emitted using complete extraction events/field inventories or the explicit no-automated-route event. No missing field is called accepted. Field HITL is **16/118 = 13.56%** over reconciled comparable slots, **16/124 = 12.90%** over the original scope, and **16/16 = 100%** over emitted comparable fields. The low first two rates reflect missing outputs and do not establish automation.

Claim HITL remains **30/30 = 100%**. True STP remains **0/30**. Output completion is separate: **22 attempts, 22 failures, zero safe outputs**; failures remain `OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`.

Track B at 2026-09-07T05:10:28.354089+00:00: **0/150 memberships confirmed, 150 remaining; zero reviewed pages and zero trusted fields**. The source-only review UI returned HTTP 200 at http://127.0.0.1:8094/qualification-review/ with predictions hidden. The independent reviewer registry is not configured. Owner input remains captured through `evaluation_results/real_release/150_cohort_missing_membership.csv`. No membership or review was inferred; the frozen blind manifest is unchanged and Track A references did not enter Track B truth.

Validation: **1,863 tests passed** across `tests/unit`, `tests/architecture`, and `tests/golden`, including 18 new independent parser goldens and 19 new reconciliation tests. Two dependency deprecation warnings were observed. Scoped Ruff and mypy passed. Production worker, package, configuration, template, and API code are unchanged from the starting commit; **NEW_SEMANTIC_REGRESSIONS = 0** in the executed suite. No OCR tuning was performed.

Artifacts: [mapping audit](reference_mapping_audit.json), [claim alignment](claim_alignment_audit.json), [form alignment](form_alignment_audit.json), [normalization audit](governed_30_normalization_audit.json), [denominator reconciliation](governed_30_denominator_reconciliation.json), [124-field aliased failure matrix](governed_30_reconciled_failure_matrix.json), [scorecard](governed_30_root_cause.json), and [hashed run manifest](governed_30_root_cause_run_manifest.json).

Frozen originals remain under ignored `evaluation_results/governed_30_root_cause/frozen/`. Private raw values, normalized values, candidate observations and reference provenance are in `evaluation_results/governed_30_root_cause/runs/66555119628534e0ba45ee9ee56fc3049f413d82a72bacfee94585163c1db256/field_reconciliation.local.json`. The content-hashed audit includes source/spec seals and comparator dependencies. Original execution observations and the historical scorecard remain intact.

Next action: **Trace why `CLM_A_001`?s selected CMS page reached unstructured extraction before changing OCR.**
