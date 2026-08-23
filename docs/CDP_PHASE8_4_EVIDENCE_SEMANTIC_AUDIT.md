# CDP Phase 8.4 Evidence Semantic Audit

## Outcome

The frozen Phase 8.3 extraction frontier was replayed without OCR. The dominant defect was policy reachability, not extraction. Of 667 reviewed fields, 626 were correct; 479 of those correct reviews were governed by an unreachable Phase 8.3 policy. No reviewed field was missing only E3 because the old builder already emitted E3, but it emitted it with pre-Phase-8 registration semantics.

Profile C reaches 66.21% safe field coverage and 33.79% field HITL at 100% accepted precision, zero false accepts, zero critical false accepts, and zero cloud cost. The requested 70%/30% field frontier and 60% claim STP frontier were not forced because the remaining critical fields lack independent corroboration and UB `federal_tax_no` is not extracted.

## Canonical authority audit

The production authority remains exactly:

`FieldCandidates -> EvidenceDecisionService -> FieldDecision[] -> ClaimDecisionService -> STP/HITL`

`packages/hitl_optimization.py` is `ANALYTICS_ONLY`. It projects canonical field decisions for historical evaluation and has no production caller.

`packages/stp_policy.py` is `LEGACY_COMPATIBILITY`. Its adapter still reconstructs blocking from required/criticality and can create `__legacy_claim_gate__`, but neither behavior is reachable from production workers. Architecture tests prohibit production imports and prohibit the synthetic gate in the canonical path. It should be removed from production packaging in a separately governed compatibility retirement.

`FieldPolicyRegistry` is the sole owner of `blocks_stp`. Unknown fields return `FIELD_POLICY_NOT_CONFIGURED`, fail closed at field level, and default to non-blocking so they cannot silently redefine claim semantics. Every CMS/UB field definition is explicitly configured.

## E1-E8 semantic audit

| Class | Canonical meaning | Actual production emission | Reachability finding |
|---|---|---|---|
| E1 | Primary extraction evidence | Every non-empty local OCR candidate | Available for extracted fields; never sufficient critical-field proof |
| E2 | Agreement across independent OCR engine families | Emitted only when normalized values agree across distinct engine families | Frozen full-page/regional candidates are both Rapid/ONNX, so they correctly do not create E2 |
| E3 | Qualified structural localization | Approved subtypes for compatible template, anchor-relative, structural layout, UB row/column, and checkbox geometry | Runtime now requires measured confirmation, reason codes, positive geometry, and the wrong-crop firewall; mode alone cannot emit E3 |
| E4 | Versioned deterministic validation | Format, checksum, date, code, amount, identifier, type-of-bill, and name-token validators | Available only on explicit PASS; validator version, input, result, and reasons are persisted |
| E5 | Authorized reference match | Only when reference state is `AUTHORIZED` | Disabled in the frozen corpus; never fabricated |
| E6 | Deterministic cross-field/claim corroboration | Totals, dates, identities, and UB row coherence | DOB/service-date consistency is now emitted; evidence only corroborates or contradicts and never changes a value |
| E7 | Independent AI confirmation | Only governed cloud-AI candidates/routes | No production-equivalent E7 in this replay; evaluation-only routes are rejected |
| E8 | Human verification | Human-confirmed disposition | Available as the terminal safe fallback |

## E3 qualification

`STRUCTURAL_LOCALIZATION_CONFIRMED` is the E3 umbrella. Approved persisted subtypes are `TEMPLATE_REGISTRATION_CONFIRMED`, `ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED`, `STRUCTURAL_LAYOUT_CONFIRMED`, `UB_ROW_COLUMN_GEOMETRY_CONFIRMED`, and `CHECKBOX_GEOMETRY_CONFIRMED`.

Anchor-relative evidence requires verified form identity, an approved priority-1 anchor, bounded alias match, positive bounded ROI, structural confidence of at least 0.80, observed token geometry or a field spatial contract, and a passed wrong-crop firewall. Structural layout requires the priority-2 structural region plus the same confidence, geometry, and crop safety. Compatible-template evidence additionally requires accepted registration, corner/transform evidence, and compatible template identity. An extraction-mode string alone is not evidence.

## First required measurement

| Diagnostic | Count | Percent all fields | Percent reviewed fields |
|---|---:|---:|---:|
| Correct and reviewed | 626 | 65.89% | 93.85% |
| Correct and reviewed, E3 only missing | 0 | 0.00% | 0.00% |
| Correct and reviewed, policy unreachable | 479 | 50.42% | 71.81% |

Correct-and-reviewed counts by family were CMS 286 and UB 340. By criticality they were C1 239, C2 288, and C3 99. All 100 claims were blocked and all 100 were single-blocker claims under Profile A.

Review buckets under Profile A were: 626 `CORRECT_BUT_EVIDENCE_INSUFFICIENT`, 15 `WRONG_AND_SAFELY_REJECTED`, 13 `TRUE_AMBIGUITY`, and 13 `UNSUPPORTED_OR_MISSING`.

## Safety conclusions

- Profile A exactly reproduces Phase 8.3: 29.79% coverage, 70.21% field HITL, 0% STP, and zero false accepts.
- Profile B changes only E3 semantics. Its metrics remain identical to A, proving that E3 availability alone was not the blocker.
- Profile C fixes only demonstrated reachability and supported field-specific evidence. It accepts 629/950 fields, all correct.
- No evaluation-only evidence or forbidden route satisfies a production-equivalent decision.
- Extraction digest is identical across all profiles and OCR rerun count is zero.
- The remaining work is new independent evidence availability, not a lower confidence threshold.
