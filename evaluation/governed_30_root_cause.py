"""Read-only forensic reconciliation of the sealed governed engineering run.

Detailed observations stay in ignored local storage. No inference or production
policy is changed, and unsupported references never become human truth.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from PIL import Image

from evaluation.governed_30_reference import (
    AUTHORITY,
    ROOT,
    catalog,
    digest,
    freeze,
    load_schemas,
    parse_reference,
    seal,
)
from evaluation.governed_30_scorecard import (
    _accepted,
    _canonical,
    _decisions,
    _route,
    metric,
    score,
)
from packages.claim_intelligence.normalization import comparison_key, normalize
from packages.field_policy import FieldPolicyRegistry

CATEGORIES = (
    "REFERENCE_MAPPING_DEFECT",
    "REFERENCE_PARSE_DEFECT",
    "CLAIM_ALIGNMENT_DEFECT",
    "FORM_ALIGNMENT_DEFECT",
    "NORMALIZATION_DEFECT",
    "COMPARATOR_DEFECT",
    "TRUTH/REFERENCE_NOT_COMPARABLE",
    "CANDIDATE_MISSING",
    "WRONG_CANDIDATE",
    "EXTRACTION_WRONG",
    "VALIDATION/SELECTION",
    "OTHER",
)
ROUTES = ("AUTO_ACCEPTED", "HITL", "REJECTED", "NOT_EMITTED", "NOT_ELIGIBLE", "UNKNOWN_BUG")


def payloads(claim: dict, topic: str) -> list[dict]:
    return [
        e.get("envelope", {}).get("payload", {})
        for e in claim.get("events", [])
        if e.get("topic") == topic
    ]


def emission_complete(claim: dict) -> bool:
    completed = payloads(claim, "extraction.completed")
    if completed:
        # A field inventory inconsistent with the event is not proof of absence.
        return completed[-1].get("field_count") == len(claim.get("fields", []))
    return claim.get("document_status") == "NEEDS_REVIEW" and any(
        p.get("needs_review") is True
        and "NO_AUTOMATED_EXTRACTION_ROUTE" in p.get("reason_codes", [])
        for p in payloads(claim, "page.selected")
    )


def routing_state(
    claim: dict,
    rows: list[dict],
    canonical: str,
    form: str,
    policy: FieldPolicyRegistry,
    *,
    eligible: bool = True,
) -> tuple[str, str]:
    routed = _route(claim, rows, canonical, form, policy)
    if routed is True:
        return "HITL", "MATCHING_TASK_OR_FIELD_DECISION_OR_EXPLICIT_BLOCKER"
    if rows:
        if _accepted(rows, _decisions(claim), routed):
            return "AUTO_ACCEPTED", "VALIDATED_AUTO_DECISION_WITH_SUPPORTING_EVIDENCE"
        if all(r.get("disposition") == "REJECTED" for r in rows):
            return "REJECTED", "EXPLICIT_REJECTED_FIELD_DISPOSITION"
        return "UNKNOWN_BUG", "EMITTED_FIELD_WITHOUT_PROVEN_TERMINAL_ROUTE"
    if not eligible:
        return "NOT_ELIGIBLE", "NO_FIELD_EMITTED_AND_REFERENCE_CONTRACT_NOT_COMPARABLE"
    if emission_complete(claim):
        return "NOT_EMITTED", "SEALED_COMPLETE_FIELD_INVENTORY_OR_EXPLICIT_NO_ROUTE"
    return "UNKNOWN_BUG", "ABSENT_FIELD_WITHOUT_COMPLETE_EMISSION_EVIDENCE"


def compare_rows(name: str, rows: list[dict], expected: str) -> tuple[bool, list[str], str]:
    keys = [
        comparison_key(name, r["raw_value"])
        for r in rows
        if isinstance(r.get("raw_value"), str) and r["raw_value"].strip()
    ]
    expected_key = comparison_key(name, expected)
    return (
        (bool(rows) and len(keys) == len(rows) and len(set(keys)) == 1 and keys[0] == expected_key),
        keys,
        expected_key,
    )


def mismatch_cause(
    rows: list[dict],
    keys: list[str],
    expected_key: str,
    name: str,
    mapping_status: str,
    parse_valid: bool,
) -> tuple[str, str]:
    if mapping_status == "WRONG_SEMANTIC_MAPPING":
        return "REFERENCE_MAPPING_DEFECT", "GOVERNED_SEMANTIC_CONTRACT_MISMATCH"
    if mapping_status != "VALID":
        return "TRUTH/REFERENCE_NOT_COMPARABLE", "SEMANTIC_PROJECTION_NOT_GOVERNED"
    if not parse_valid:
        return "REFERENCE_PARSE_DEFECT", "FROZEN_REFERENCE_DIFFERS_FROM_SEALED_SPEC_REPLAY"
    if not rows or not keys:
        return "CANDIDATE_MISSING", "NO_NONBLANK_SEMANTIC_HEADER_CANDIDATE_EMITTED"
    if expected_key in keys:
        return "VALIDATION/SELECTION", "MATCHING_AND_CONFLICTING_HEADER_OCCURRENCES"
    alternate_keys = [
        comparison_key(name, c["raw_text"])
        for r in rows
        for c in r.get("candidates", [])
        if isinstance(c, dict) and isinstance(c.get("raw_text"), str) and c["raw_text"].strip()
    ]
    if expected_key in alternate_keys:
        return "WRONG_CANDIDATE", "MATCHING_ALTERNATIVE_EXISTS_BUT_WAS_NOT_SELECTED"
    return "EXTRACTION_WRONG", "EMITTED_VALUE_AND_STORED_ALTERNATIVES_DO_NOT_MATCH_REFERENCE"


def verify_alignment(
    root: Path, frozen: Path, manifest: dict, reference: dict, execution: dict
) -> tuple[dict, dict, dict]:
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    membership = read(frozen / "owner_sequence_membership.local.json")
    inputs = read(frozen / "owner_sequence_input.local.json")
    owner = read(frozen / "source_owner_confirmation.json")
    if owner.get("status") != "OWNER_CONFIRMED" or owner.get("mapping_rule") != (
        "SOURCE_IMAGE_SEQUENCE_MATCHES_DATAMATICS_CLAIM_SEQUENCE"
    ):
        raise ValueError("OWNER_SEQUENCE_AUTHORITY_REQUIRED")
    for name, expected in inputs["sealed_inputs"].items():
        if digest(Path(name)) != expected:
            raise ValueError("SOURCE_OR_SPEC_SEAL_CHANGED")
    schemas = {f: load_schemas(root, f) for f in ("CMS1500", "UB")}
    mappings = {f: catalog(schemas[f], f) for f in schemas}
    mi = {c["claim_alias"]: c for c in manifest["claims"]}
    ri = {c["claim_alias"]: c for c in reference["claims"]}
    ei = {c["claim_alias"]: c for c in execution["claims"]}
    rows = membership["mappings"]
    if len(rows) != 30 or {r["claim_id"] for r in rows} != set(mi):
        raise ValueError("THIRTY_UNIQUE_OWNER_BINDINGS_REQUIRED")
    sequences: dict[str, list[int]] = defaultdict(list)
    sequence_positions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    aligned, replayed = [], {}
    for row in rows:
        alias = row["claim_id"]
        m, ref, actual = mi[alias], ri[alias], ei[alias]
        form = "UB" if row["claim_form_type"] in {"UB", "UB04"} else "CMS1500"
        source = Path(row["actual_source_path"])
        output = source.parent / row["output_text_file"]
        start, end = row["output_record_start"], row["output_record_end"]
        lines = output.read_text(encoding="utf-8-sig").splitlines()[start - 1 : end]
        spec = next(
            f
            for f in schemas[form][row["claim_record_start"]]["fields"]
            if f["canonical_name"] == "patient_control_number"
        )
        with Image.open(source) as image:
            frames = getattr(image, "n_frames", 1)
        checks = {
            "owner_membership_exact": row["membership_status"] == "EXACT",
            "source_hash_matches": digest(source)
            == row["source_sha256"]
            == m["source_hash"]
            == actual["source_sha256"],
            "all_frames_bound": frames
            == row["source_frame_count"]
            == len(m["pages"])
            == actual["source_frames"]
            == actual["prepared_frames"]
            and row["source_page_numbers"] == list(range(1, frames + 1)),
            "output_hash_matches": digest(output) == m["output_provenance"]["source_file_hash"],
            "output_boundaries_match": start == m["output_provenance"]["start_line"]
            and end == m["output_provenance"]["end_line"]
            and bool(lines)
            and lines[0].startswith(row["claim_record_start"])
            and (
                lines[-1].startswith(row["claim_record_end"])
                or form == "UB"
                and owner.get("ub_record_91_optional") is True
                and lines[-1].startswith("90")
            ),
            "control_matches": bool(lines)
            and lines[0][spec["start_position"] - 1 : spec["end_position"]].strip()
            == row["source_control_reference"],
            "reference_form_matches": form == m["form_type"] == ref["form_type"],
        }
        if not all(checks.values()):
            raise ValueError("CLAIM_ALIGNMENT_FAILED:" + alias)
        sequences[row["group"]].append(row["output_claim_sequence"])
        sequence_positions[row["group"]].append((start, row["output_claim_sequence"]))
        ranges[str(output)].append((start, end))
        aligned.append(
            {
                "claim_alias": alias,
                "form_type": form,
                "checks": checks,
                "status": "EXACT",
                "owner_sequence": row["output_claim_sequence"],
            }
        )
        replayed[alias] = parse_reference(
            lines,
            mappings[form],
            schemas[form],
            source_hash=digest(output),
            claim_alias=alias,
            start_line=start,
        )
    if any(sorted(s) != list(range(1, len(s) + 1)) for s in sequences.values()):
        raise ValueError("OWNER_SEQUENCE_GAP_OR_DUPLICATE")
    for positions in sequence_positions.values():
        if [n for _, n in sorted(positions)] != list(range(1, len(positions) + 1)):
            raise ValueError("OWNER_SEQUENCE_REFERENCE_ORDER_MISMATCH")
    for spans in ranges.values():
        ordered = sorted(spans)
        if any(a[1] >= b[0] for a, b in pairwise(ordered)):
            raise ValueError("REFERENCE_CLAIM_RANGES_OVERLAP")
    return (
        {
            "claims": aligned,
            "exact": len(aligned),
            "total": 30,
            "status": "PASS",
            "sequence_basis": owner["mapping_rule"],
            "source_spec_seals_verified": len(inputs["sealed_inputs"]),
            "sequence_contiguous": True,
            "reference_ranges_nonoverlapping": True,
        },
        replayed,
        mappings,
    )


def build(root: Path = ROOT) -> dict:
    local = root / "evaluation_results/governed_30_root_cause"
    frozen = local / "frozen"
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    seals = read(frozen / "run_manifest.local.json")
    for rel, info in seals.items():
        if digest(frozen / info["snapshot"]) != info["sha256"]:
            raise ValueError("FROZEN_AUDIT_INPUT_DRIFT")
        # Compare live immutable observations too; a mutable historical summary may
        # be republished by a watcher, but cannot replace this frozen evidence.
        if (
            rel.endswith(
                (
                    "raw_execution.local.json",
                    "governed_30_reference.local.json",
                    "governed_30_manifest.json",
                )
            )
            and digest(root / rel) != info["sha256"]
        ):
            raise ValueError("ORIGINAL_OBSERVATION_CHANGED")
    manifest = read(frozen / "governed_30_manifest.json")
    reference = read(frozen / "governed_30_reference.local.json")
    execution = read(frozen / "raw_execution.local.json")
    if seal({k: v for k, v in manifest.items() if k != "cohort_hash"}) != manifest["cohort_hash"]:
        raise ValueError("COHORT_SEAL_INVALID")
    raw_seal = read(frozen / "raw_execution_seal.json")
    if raw_seal["raw_execution_sha256"] != digest(frozen / "raw_execution.local.json"):
        raise ValueError("RAW_EXECUTION_SEAL_INVALID")
    inputs = read(frozen / "execution_input.local.json")
    if (
        inputs["candidate_commit_sha"] != execution["candidate_commit_sha"]
        or inputs["cohort_hash"] != manifest["cohort_hash"]
    ):
        raise ValueError("EXECUTION_INPUT_IDENTITY_CHANGED")
    candidate_policy = subprocess.check_output(
        [
            "git",
            "show",
            execution["candidate_commit_sha"] + ":config/field_acceptance_policies.yaml",
        ],
        cwd=root,
    )
    # Git stores LF, while the existing Windows checkout may contain CRLF.
    frozen_policy = (frozen / "field_acceptance_policies.yaml").read_bytes().replace(b"\r\n", b"\n")
    if candidate_policy.replace(b"\r\n", b"\n") != frozen_policy:
        raise ValueError("FROZEN_POLICY_CHANGED")
    policy = FieldPolicyRegistry.load(frozen / "field_acceptance_policies.yaml")
    original, _ = score(manifest, reference, execution, policy)
    if original["raw_accuracy"]["denominator"] != 124 or original["raw_accuracy"]["numerator"] != 1:
        raise ValueError("ORIGINAL_124_FIELD_SCORE_NOT_REPRODUCED")
    mapping_audit = read(root / "docs/qualification/reference_mapping_audit.json")
    # Mapping decisions are explicit audited inputs, never inferred from a failure.
    mapping_index = {(r["form_type"], r["cdp_field"]): r for r in mapping_audit["entries"]}
    alignment, reparsed, catalogs = verify_alignment(root, frozen, manifest, reference, execution)
    claims = {c["claim_alias"]: c for c in execution["claims"]}
    detailed, public = [], []
    for ref_claim in reference["claims"]:
        alias, form = ref_claim["claim_alias"], ref_claim["form_type"]
        claim = claims[alias]
        for name, expected in ref_claim["fields"].items():
            if expected["status"] != "REFERENCE_AVAILABLE":
                continue
            canonical = _canonical(policy, form, name)
            rows = [
                r
                for r in claim["fields"]
                if r.get("service_line_number") is None
                and _canonical(policy, form, r["field_name"]) == canonical
            ]
            correct, keys, expected_key = compare_rows(name, rows, expected["value"])
            mapping = mapping_index[(form, name)]
            parse_valid = reparsed[alias][name] == expected
            eligible = mapping["status"] == "VALID" and parse_valid
            state, route_reason = routing_state(
                claim, rows, canonical, form, policy, eligible=eligible
            )
            effective = [
                {
                    **r,
                    "raw_value": r.get("normalized_value")
                    if r.get("normalized_value") is not None
                    else r.get("raw_value"),
                }
                for r in rows
            ]
            normalized_correct, normalized_keys, _ = compare_rows(
                name, effective, expected["value"]
            )
            alternative_matches = sum(
                comparison_key(name, a["raw_text"]) == expected_key
                for r in rows
                for a in r.get("candidates", [])
                if isinstance(a, dict)
                and isinstance(a.get("raw_text"), str)
                and a["raw_text"].strip()
            )
            category, reason = (
                (None, "EXISTING_GOVERNED_COMPARATOR_MATCH")
                if correct
                else (
                    mismatch_cause(rows, keys, expected_key, name, mapping["status"], parse_valid)
                )
            )
            rule = next(r for r in catalogs[form] if r["cdp_field"] == name)
            selected = payloads(claim, "page.selected")
            item = {
                "claim_alias": alias,
                "form_type": form,
                "cdp_field": name,
                "canonical_field": canonical,
                "reference_field_names": [p["canonical_name"] for p in rule["positions"]],
                "reference_record": rule["source_record"],
                "reference_positions": rule["positions"],
                "mapping_status": mapping["status"],
                "mapping_reason": mapping["reason"],
                "normalized_prediction_match": normalized_correct,
                "matching_alternative_count": alternative_matches,
                "candidate_syntax": [
                    normalize(name, r["raw_value"])[1]
                    if isinstance(r.get("raw_value"), str)
                    else None
                    for r in rows
                ],
                "parse_replay_exact": parse_valid,
                "normalizer": expected["normalization"],
                "comparator": "packages.claim_intelligence.normalization.comparison_key",
                "original_match": correct,
                "reconciled_match": correct if eligible else None,
                "eligible": eligible,
                "critical": policy.for_field(
                    "UB04" if form == "UB" else form, name
                ).criticality.value
                in {"C2", "C3"},
                "primary_classification": category,
                "reason": reason,
                "routing_state": state,
                "routing_evidence": route_reason,
                "candidate_presence": bool(rows),
                "candidate_count": len(rows),
                "source_pages": [r.get("page_number") for r in rows],
                "source_page_when_missing": "NO_CANDIDATE_PAGE" if not rows else None,
                "selected_source_page": selected[-1].get("selected_page_number")
                if selected
                else None,
                "processing_route": selected[-1].get("processing_route") if selected else None,
                "reference_empty_semantics": "NONBLANK_REFERENCE_OBSERVATION",
                "prediction_empty_semantics": "NOT_PRESENT"
                if not rows
                else "NONBLANK"
                if keys
                else "BLANK_EMITTED",
            }
            public.append(item)
            detailed.append(
                {
                    **item,
                    "raw_cdp_values": [r.get("raw_value") for r in rows],
                    "normalized_cdp_values": [r.get("normalized_value") for r in rows],
                    "cdp_comparison_keys": keys,
                    "normalized_cdp_comparison_keys": normalized_keys,
                    "reference_value": expected["value"],
                    "normalized_reference_value": expected_key,
                    "reference_provenance": expected["provenance"],
                    "candidate_observations": rows,
                }
            )
    failures = [r for r in public if not r["original_match"]]
    eligible_rows = [r for r in public if r["eligible"]]
    critical = [r for r in eligible_rows if r["critical"]]
    removed = [r for r in public if not r["eligible"]]
    routes = Counter(r["routing_state"] for r in public)
    categories = Counter(r["primary_classification"] for r in failures)
    if len(public) != 124 or len(failures) != 123 or sum(categories.values()) != 123:
        raise ValueError("EVERY_ORIGINAL_COMPARISON_MUST_RECONCILE")
    if routes["UNKNOWN_BUG"]:
        raise ValueError("UNRESOLVED_FIELD_ROUTING")
    groups = {}
    for dimension in (
        "cdp_field",
        "form_type",
        "reference_record",
        "normalizer",
        "comparator",
        "claim_alias",
    ):
        group: dict[str, Counter] = defaultdict(Counter)
        for row in failures:
            group[str(row[dimension])][row["primary_classification"]] += 1
        groups[dimension] = {k: dict(v) for k, v in group.items()}
    denominator = {
        "original": 124,
        "invalid_semantic_mappings": sum(
            r["mapping_status"] == "WRONG_SEMANTIC_MAPPING" for r in removed
        ),
        "invalid_parsed_references": sum(not r["parse_replay_exact"] for r in removed),
        "not_comparable": sum(
            r["mapping_status"] in {"AMBIGUOUS_MAPPING", "NOT_COMPARABLE"} for r in removed
        ),
        "final_comparable": len(eligible_rows),
        "removed": [
            {k: r[k] for k in ("claim_alias", "cdp_field", "mapping_status", "reason")}
            for r in removed
        ],
        "genuine_missing_candidates_retained": sum(
            r["primary_classification"] == "CANDIDATE_MISSING" for r in eligible_rows
        ),
    }
    summary = {
        "authority": AUTHORITY,
        "release_qualification": False,
        "cohort_hash": manifest["cohort_hash"],
        "original": {
            "raw_accuracy": original["raw_accuracy"],
            "critical_accuracy": original["critical_accuracy"],
        },
        "mismatch_root_causes": {c: categories[c] for c in CATEGORIES},
        "denominator": denominator,
        "raw_accuracy": metric(sum(r["original_match"] for r in eligible_rows), len(eligible_rows)),
        "critical_accuracy": metric(sum(r["original_match"] for r in critical), len(critical)),
        "routing": {r: routes[r] for r in ROUTES},
        "field_hitl_original_scope": metric(routes["HITL"], 124),
        "field_hitl_comparable_scope": metric(
            sum(r["routing_state"] == "HITL" for r in eligible_rows), len(eligible_rows)
        ),
        "field_hitl_emitted_scope": metric(
            sum(r["routing_state"] == "HITL" for r in public if r["candidate_presence"]),
            sum(r["candidate_presence"] for r in public),
        ),
        "field_hitl_note": "NOT_EMITTED is a pipeline failure, not auto-acceptance or STP.",
        "claim_hitl": original["claim_hitl"],
        "true_stp": original["true_stp"],
        "output": {
            "attempts": sum(bool(c.get("claim_decision")) for c in claims.values()),
            "failures": sum(len(c.get("failures", [])) for c in claims.values()),
            "safe_outputs": sum(c.get("output_completed") is True for c in claims.values()),
        },
        "claim_alignment": {"exact": alignment["exact"], "total": alignment["total"]},
        "form_alignment": {
            "cross_reference_form_pairs": 0,
            "production_validated_forms": dict(
                Counter(
                    p.get("form_type", "MISSING")
                    for c in claims.values()
                    for p in payloads(c, "claim.validated")
                )
            ),
        },
        "all_comparisons_explainable": True,
        "normalization_audit": {
            "raw_normalized_outcome_changes": sum(
                r["original_match"] != r["normalized_prediction_match"] for r in public
            ),
            "matching_unselected_alternative_slots": sum(
                not r["original_match"] and r["matching_alternative_count"] > 0 for r in public
            ),
            "reference_parser_exact_slots": sum(r["parse_replay_exact"] for r in public),
        },
        "normalization_or_comparator_repairs": 0,
        "production_behavior_changed": False,
        "status": "MIXED_CAUSES" if removed else "GENUINE_EXTRACTION_DEFECT_CONFIRMED",
        "next_action": "Trace why CLM_A_001's selected CMS page reached unstructured extraction before changing OCR.",
    }
    continuity_path = root / ".runs/track-b-continuity/continuity.local.json"
    if continuity_path.exists():
        continuity = read(continuity_path)
        summary["track_b"] = {
            "checked_at_utc": continuity["checked_at_utc"],
            "membership_confirmed": continuity["owner_confirmations_entered"],
            "membership_remaining": continuity["membership_rows"]
            - continuity["owner_confirmations_entered"],
            "reviewed": continuity["live_progress"]["pages_reviewed"],
            "trusted_fields": continuity["live_progress"]["trusted_fields"],
            "reviewer_registry_configured": continuity["live_progress"][
                "reviewer_registry_configured"
            ],
            "review_ui_http_status": continuity["page"]["status"],
            "prediction_visible": not continuity["page"]["prediction_visible_false"],
            "blind_manifest_sha256": continuity["blind_manifest_sha256"],
        }
        if (
            digest(root / "evaluation_results/cdp2/active_learning_blind_manifest.json")
            != continuity["blind_manifest_sha256"]
        ):
            raise ValueError("BLIND_MANIFEST_CHANGED_DURING_AUDIT")
    else:
        summary["track_b"] = {"status": "CONTINUITY_OBSERVATION_NOT_AVAILABLE"}
    out = root / "docs/qualification"
    dependencies = [
        root / "evaluation/governed_30_reference.py",
        root / "evaluation/governed_30_scorecard.py",
        root / "packages/claim_intelligence/normalization.py",
        root / "packages/evidence/name_agreement.py",
        root / "config/evaluation_field_crosswalk.yaml",
        *sorted((root / "config/output_specs/nsf/compiled").glob("*.yaml")),
        *sorted((root / "config/output_specs/ub92/compiled").glob("*.yaml")),
    ]
    run_manifest = {
        "audit_dependency_hashes": {
            str(p.relative_to(root)).replace(chr(92), "/"): digest(p) for p in dependencies
        },
        "frozen_input_hashes": {Path(k).name: v["sha256"] for k, v in seals.items()},
        "cohort_hash": manifest["cohort_hash"],
        "claims": 30,
        "comparisons": 124,
        "mapping_audit_sha256": digest(out / "reference_mapping_audit.json"),
        "audit_code_sha256": digest(Path(__file__)),
        "candidate_policy_sha256_lf": hashlib.sha256(frozen_policy).hexdigest(),
        "candidate_policy_verified_at_commit": execution["candidate_commit_sha"],
        "source_spec_seals_verified": alignment["source_spec_seals_verified"],
        "sealed_source_spec_hashes": sorted(
            read(frozen / "owner_sequence_input.local.json")["sealed_inputs"].values()
        ),
    }
    run_manifest["audit_run_hash"] = seal(run_manifest)
    freeze(
        local / "runs" / run_manifest["audit_run_hash"] / "field_reconciliation.local.json",
        {"run": run_manifest, "fields": detailed},
    )
    for name, value in {
        "governed_30_root_cause_run_manifest.json": run_manifest,
        "claim_alignment_audit.json": alignment,
        "form_alignment_audit.json": summary["form_alignment"],
        "governed_30_normalization_audit.json": summary["normalization_audit"],
        "governed_30_denominator_reconciliation.json": denominator,
        "governed_30_reconciled_failure_matrix.json": {"fields": public, "patterns": groups},
        "governed_30_root_cause.json": summary,
    }.items():
        (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
