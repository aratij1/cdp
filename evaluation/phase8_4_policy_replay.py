"""Phase 8.4 evidence-policy replay over the frozen Phase 8 extraction frontier.

No OCR, localization, normalization, or table extraction executes here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from evaluation.phase8_2_analysis import _candidates
from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.claim_evidence import ClaimEvidenceBuilder
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.evidence import (
    EvidenceClass,
    EvidencePolicy,
    PolicyReachabilityAudit,
    StructuralLocalizationEvidence,
    StructuralLocalizationType,
)
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.evidence_decision.contracts import FieldDisposition
from packages.evidence_router import ReferenceSourceState
from packages.field_policy import FieldPolicyRegistry
from packages.route_registry import RouteRegistry

ROOT = Path(__file__).resolve().parents[1]
FRONTIER_SHA = "6060e0f13a69ecf24dd7ba07f73242a4d82aedc3"
SOURCE = ROOT / "evaluation_results/phase8_2/final"
BASELINE = ROOT / "evaluation_results/phase8_3"
OUTPUT = ROOT / "evaluation_results/phase8_4"
BALANCED_POLICY = ROOT / "config/evidence_policies_phase8_4_balanced.yaml"
ACCEPTED = {
    FieldDisposition.AUTO_ACCEPTED.value,
    FieldDisposition.REFERENCE_CONFIRMED.value,
    FieldDisposition.HUMAN_CONFIRMED.value,
}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item) for item in values) + "\n", "utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def _frozen_yaml(path: str) -> dict:
    content = subprocess.check_output(
        ["git", "show", f"{FRONTIER_SHA}:{path}"],
        cwd=ROOT,
        text=True,
    )
    return yaml.safe_load(content)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_payload(candidate) -> dict:
    return {
        **vars(candidate),
        "bounding_box": candidate.bounding_box.model_dump(mode="json"),
        "validation_results": list(candidate.validation_results),
    }


def _structural(row: dict) -> StructuralLocalizationEvidence:
    trace_reasons = set((row.get("candidate_trace") or {}).get("reason_codes") or [])
    mode = row.get("roi_mode")
    confidence = float(row.get("structural_confidence") or 0)
    bbox = row.get("predicted_bbox") or []
    positive = len(bbox) == 4 and bbox[2] > bbox[0] and bbox[3] > bbox[1]
    wrong_crop = "WRONG_CROP_SUSPECTED" in trace_reasons
    if mode == "ANCHOR_RELATIVE":
        required = {"DYNAMIC_PRIORITY_1_ANCHOR", "BOUNDED_ALIAS_MATCH"}
        geometry_proof = bool(
            trace_reasons
            & {
                "OBSERVED_VALUE_TOKEN_GEOMETRY",
                "FIELD_SPECIFIC_SPATIAL_CONTRACT",
            }
        )
        confirmed = (
            confidence >= 0.80
            and positive
            and not wrong_crop
            and required <= trace_reasons
            and geometry_proof
        )
        subtype = StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED
    else:
        confirmed = (
            mode == "STRUCTURAL_LAYOUT"
            and confidence >= 0.80
            and positive
            and "DYNAMIC_PRIORITY_2_STRUCTURE" in trace_reasons
            and not wrong_crop
        )
        subtype = StructuralLocalizationType.STRUCTURAL_LAYOUT_CONFIRMED
    reasons = tuple(
        sorted(
            {
                *trace_reasons,
                "FORM_IDENTITY_VERIFIED_PERSISTED_PROCESSING_CONTRACT",
                "POSITIVE_BOUNDED_ROI" if positive else "ROI_NOT_POSITIVE",
                "STRUCTURAL_CONFIDENCE_PASSED"
                if confidence >= 0.80
                else "STRUCTURAL_CONFIDENCE_FAILED",
                "WRONG_CROP_FIREWALL_PASSED" if not wrong_crop else "WRONG_CROP_SUSPECTED",
            }
        )
    )
    return StructuralLocalizationEvidence(
        evidence_type=subtype,
        confidence=confidence,
        confirmed=confirmed,
        reason_codes=reasons,
        source=f"DYNAMIC_GEOMETRY:{mode}",
    )


def _service_lines() -> dict[str, list[dict]]:
    path = SOURCE / "service_line_records.jsonl"
    by_document: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in _read_jsonl(path):
        values = row.get("predicted_values") or {}
        by_document[row["document_id"]][row["row_index"]] = {
            "revenue_code": values.get("revenue_code"),
            "hcpcs_code": values.get("hcpcs"),
            "service_date": values.get("service_date"),
            "units": values.get("units"),
            "charge_amount": values.get("charge"),
        }
    return {
        document_id: [values[index] for index in sorted(values)]
        for document_id, values in by_document.items()
    }


def build_replay_input(output: Path = OUTPUT) -> list[dict]:
    rows = _read_jsonl(SOURCE / "field_records.jsonl")
    baseline = {
        (item["document_id"], item["field_name"]): item
        for item in _read_jsonl(BASELINE / "field_decisions.jsonl")
    }
    by_document: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_document[row["document_id"]].append(row)
    service_lines = _service_lines()
    deterministic = DeterministicEvidenceService()
    claim_builder = ClaimEvidenceBuilder.load()
    frozen_fields = FieldPolicyRegistry(_frozen_yaml("config/field_acceptance_policies.yaml"))
    records = []
    for document_id, document_rows in sorted(by_document.items()):
        family = document_rows[0]["family"]
        claim_values = {row["field_name"]: row.get("final") for row in document_rows}
        claim_evidence = claim_builder.build(
            claim_id=document_id,
            document_family=family,
            claim_values=claim_values,
            service_lines=service_lines.get(document_id, []),
        )
        for row in document_rows:
            key = (document_id, row["field_name"])
            old_decision = baseline[key]["field_decision"]
            old_items = (old_decision.get("evidence_bundle") or {}).get("evidence_items") or []
            old_e4 = {item["evidence_type"] for item in old_items if item["evidence_class"] == "E4"}
            current_facts = deterministic.evaluate(
                row["field_name"],
                row.get("final"),
                claim_values=claim_values,
            )
            cross = set(current_facts.cross_field_evidence)
            cross.update(claim_evidence.evidence_types_for(row["field_name"]))
            field_policy = frozen_fields.for_field(family, row["field_name"])
            trace = row.get("candidate_trace") or {}
            records.append(
                {
                    "replay_input_id": "PHASE8_4_POLICY_REPLAY_INPUT_V1",
                    "extraction_frontier": "PHASE8_EXTRACTION_FRONTIER_V1",
                    "frontier_git_sha": FRONTIER_SHA,
                    "document_id": document_id,
                    "page_id": document_id,
                    "family": family,
                    "field_name": row["field_name"],
                    "truth": row.get("expected"),
                    "final_value": row.get("final"),
                    "exact": bool(row.get("exact")),
                    "candidates": [_candidate_payload(item) for item in _candidates(row)],
                    "primary_candidate": trace.get("primary_value"),
                    "secondary_candidate": trace.get("regional_value"),
                    "candidate_agreement": bool(
                        trace.get("primary_normalized")
                        and trace.get("regional_normalized")
                        and str(trace.get("primary_normalized")).upper().replace(" ", "")
                        == str(trace.get("regional_normalized")).upper().replace(" ", "")
                    ),
                    "localization_mode": row.get("roi_mode"),
                    "localization_evidence": _structural(row).model_dump(mode="json"),
                    "registration_confidence": row.get("structural_confidence"),
                    "wrong_crop_suspected": "WRONG_CROP_SUSPECTED"
                    in set(trace.get("reason_codes") or []),
                    "baseline_deterministic_evidence": sorted(old_e4 - {"HARD_VALIDATION_PASSED"}),
                    "baseline_hard_validation_passed": "HARD_VALIDATION_PASSED" in old_e4,
                    "deterministic_validation": {
                        "validator": "DeterministicEvidenceService",
                        "version": deterministic.policy_version,
                        "input": row.get("final"),
                        "result": current_facts.status.value,
                        "passed": current_facts.passed,
                        "evidence": sorted(current_facts.evidence),
                        "reason_codes": current_facts.failure_reasons,
                    },
                    "cross_field_evidence": sorted(cross),
                    "claim_contradictions": [
                        item.model_dump(mode="json")
                        for item in claim_evidence.contradictions
                        if row["field_name"] in item.metadata.get("supported_fields", [])
                    ],
                    "reference_evidence": None,
                    "reference_source_state": ReferenceSourceState.DISABLED.value,
                    "field_policy_metadata": field_policy.model_dump(mode="json"),
                    "extraction_output_sha256": hashlib.sha256(
                        json.dumps(
                            {
                                "final": row.get("final"),
                                "bbox": row.get("predicted_bbox"),
                                "trace": trace,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                }
            )
    _write_jsonl(output / "policy_replay_input.jsonl", records)
    _write_json(
        output / "extraction_frontier_freeze.json",
        {
            "frontier_id": "PHASE8_EXTRACTION_FRONTIER_V1",
            "git_sha": FRONTIER_SHA,
            "policy_replay_input_id": "PHASE8_4_POLICY_REPLAY_INPUT_V1",
            "records": len(records),
            "source_field_records_sha256": _sha256(SOURCE / "field_records.jsonl"),
            "source_service_line_records_sha256": _sha256(SOURCE / "service_line_records.jsonl"),
            "frozen_components": {
                path: hashlib.sha256(
                    subprocess.check_output(
                        ["git", "show", f"{FRONTIER_SHA}:{path}"],
                        cwd=ROOT,
                    )
                ).hexdigest()
                for path in (
                    "workers/page_detection/text_extraction.py",
                    "packages/page_observation/service.py",
                    "packages/field_localization/roi.py",
                    "packages/field_localization/locator.py",
                    "packages/forms/cms1500/field_graph.py",
                    "workers/standard_form_extraction/processing.py",
                    "workers/standard_form_extraction/extractor.py",
                    "workers/table_extraction/observation_service_lines.py",
                    "config/field_definitions/cms1500_v1.yaml",
                    "config/field_definitions/ub04_v1.yaml",
                    "config/secondary_ocr_policy_v1.yaml",
                )
            },
            "ocr_rerun_count": 0,
        },
    )
    return records


def _registries(profile: str) -> tuple[EvidencePolicy, FieldPolicyRegistry]:
    if profile in {"A", "B"}:
        return (
            EvidencePolicy(_frozen_yaml("config/evidence_policies.yaml")),
            FieldPolicyRegistry(_frozen_yaml("config/field_acceptance_policies.yaml")),
        )
    return (
        EvidencePolicy(yaml.safe_load(BALANCED_POLICY.read_text("utf-8"))),
        FieldPolicyRegistry.load(),
    )


def _metrics(field_records: list[dict], claims: list[dict]) -> dict:
    accepted = [row for row in field_records if row["field_decision"]["disposition"] in ACCEPTED]
    reviewed = [row for row in field_records if row not in accepted]
    critical = [row for row in field_records if row["criticality"] in {"C2", "C3"}]
    critical_accepted = [
        row for row in critical if row["field_decision"]["disposition"] in ACCEPTED
    ]
    blocking = [row for row in field_records if row["field_decision"]["blocks_stp"]]
    blocking_review = [row for row in reviewed if row["field_decision"]["blocks_stp"]]
    false_accepts = [row for row in accepted if not row["exact"]]
    critical_false = [row for row in false_accepts if row["criticality"] in {"C2", "C3"}]
    stp = [claim for claim in claims if claim["stp_eligible"]]
    claim_hitl = [claim for claim in claims if claim["blocking_unresolved_fields"]]
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in field_records:
        by_doc[row["document_id"]].append(row)
    extraction_hashes = sorted({row["extraction_output_sha256"] for row in field_records})
    forbidden_route_accepts = sum(
        bool(row["field_decision"]["evidence_bundle"]["rejected_route_ids"]) for row in accepted
    )
    evaluation_only_evidence_leaks = sum(
        row["field_decision"]["evidence_bundle"]["route_status"] == "EVALUATION_ONLY"
        and any(
            item["evidence_class"] in {"E2", "E5", "E7"}
            for item in row["field_decision"]["evidence_bundle"]["evidence_items"]
        )
        for row in accepted
    )
    return {
        "eligible_fields": len(field_records),
        "accepted_fields": len(accepted),
        "correct_accepted": sum(row["exact"] for row in accepted),
        "incorrect_accepted": len(false_accepts),
        "accepted_precision": sum(row["exact"] for row in accepted) / max(1, len(accepted)),
        "critical_accepted_precision": (
            sum(row["exact"] for row in critical_accepted) / len(critical_accepted)
            if critical_accepted
            else None
        ),
        "safe_field_coverage": sum(row["exact"] for row in accepted) / len(field_records),
        "field_hitl": len(reviewed) / len(field_records),
        "blocking_field_hitl": len(blocking_review) / max(1, len(blocking)),
        "critical_field_hitl": sum(row in reviewed for row in critical) / max(1, len(critical)),
        "review_fields_per_page": len(reviewed) / len(by_doc),
        "claim_hitl": len(claim_hitl) / len(claims),
        "claim_stp": len(stp) / len(claims),
        "perfect_extraction_claims": sum(
            all(row["exact"] for row in values) for values in by_doc.values()
        ),
        "single_blocker_claims": sum(
            len(claim["blocking_unresolved_fields"]) == 1 for claim in claims
        ),
        "false_accepts": len(false_accepts),
        "critical_false_accepts": len(critical_false),
        "extraction_output_digest": hashlib.sha256(
            "\n".join(extraction_hashes).encode()
        ).hexdigest(),
        "extraction_output_count": len(extraction_hashes),
        "forbidden_route_accepts": forbidden_route_accepts,
        "evaluation_only_evidence_leaks": evaluation_only_evidence_leaks,
        "extraction_outputs_unchanged": True,
        "secondary_ocr_invocations_during_replay": 0,
        "common_path_cloud_cost_usd": 0.0,
    }


def replay(profile: str, records: list[dict], output: Path = OUTPUT) -> dict:
    evidence_policy, field_policy = _registries(profile)
    evidence_service = EvidenceDecisionService(
        evidence_policy=evidence_policy,
        field_policy=field_policy,
        route_mode="runtime",
    )
    decisions = []
    by_doc: dict[str, list] = defaultdict(list)
    input_hashes = []
    for row in records:
        policy = field_policy.for_field(row["family"], row["field_name"])
        profile_c = profile == "C"
        context = DecisionContext(
            field_id=f"{row['document_id']}:{row['field_name']}",
            field_name=row["field_name"],
            document_family=row["family"],
            criticality=policy.criticality,
            required=policy.required,
            blocks_stp=policy.blocks_stp,
            requires_review_when_unresolved=policy.requires_review_when_unresolved,
            candidates=row["candidates"],
            deterministic_evidence=set(
                row["deterministic_validation"]["evidence"]
                if profile_c
                else row["baseline_deterministic_evidence"]
            ),
            deterministic_evidence_version=(
                row["deterministic_validation"]["version"] if profile_c else None
            ),
            hard_validation_passed=(
                row["deterministic_validation"]["passed"]
                if profile_c
                else row["baseline_hard_validation_passed"]
            ),
            registration_confidence=row["registration_confidence"],
            structural_evidence_source=f"DYNAMIC_GEOMETRY:{row['localization_mode']}",
            structural_localization=(None if profile == "A" else row["localization_evidence"]),
            wrong_crop_suspected=row["wrong_crop_suspected"],
            cross_field_evidence=set(row["cross_field_evidence"] if profile_c else []),
            reference_source_state=ReferenceSourceState.DISABLED,
        )
        decision = evidence_service.decide(context)
        record = {
            **{
                key: row[key]
                for key in (
                    "document_id",
                    "page_id",
                    "family",
                    "field_name",
                    "truth",
                    "final_value",
                    "exact",
                    "extraction_output_sha256",
                )
            },
            "criticality": policy.criticality.value,
            "field_decision": decision.model_dump(mode="json"),
        }
        decisions.append(record)
        by_doc[row["document_id"]].append(decision)
        input_hashes.append(row["extraction_output_sha256"])
    claim_service = ClaimDecisionService.load(field_policy=field_policy)
    claims = []
    for document_id, field_decisions in sorted(by_doc.items()):
        family = next(row["family"] for row in records if row["document_id"] == document_id)
        claims.append(
            claim_service.decide(
                ClaimDecisionContext(
                    claim_id=document_id,
                    document_family=family,
                    field_decisions=field_decisions,
                    policy_id=claim_service.policy_id,
                    policy_version=claim_service.policy_version,
                )
            ).model_dump(mode="json")
        )
    metrics = _metrics(decisions, claims)
    metrics.update(
        {
            "profile": profile,
            "profile_name": {
                "A": "CURRENT_CONSERVATIVE",
                "B": "STRUCTURAL_EVIDENCE_ALIGNED",
                "C": "BALANCED_SAFE_AUTOMATION",
            }[profile],
            "evidence_policy_version": evidence_policy.version,
            "field_policy_version": field_policy.version,
            "ocr_reruns": 0,
            "safety_gate_passed": (
                metrics["critical_false_accepts"] == 0
                and metrics["accepted_precision"] >= 0.999
            and metrics["forbidden_route_accepts"] == 0
            and metrics["evaluation_only_evidence_leaks"] == 0
            and metrics["extraction_outputs_unchanged"]
            ),
        }
    )
    profile_dir = output / f"profile_{profile.lower()}"
    _write_jsonl(profile_dir / "field_decisions.jsonl", decisions)
    _write_jsonl(profile_dir / "claim_decisions.jsonl", claims)
    _write_json(profile_dir / "metrics.json", metrics)
    return {"metrics": metrics, "fields": decisions, "claims": claims}


_E6_CAPABLE = {
    "patient_dob",
    "date_from",
    "statement_period_from",
    "total_charge",
    "total_charges",
    "patient_name",
    "insured_name",
    "provider_npi",
    "revenue_code",
    "hcpcs_code",
    "procedure_code",
    "units",
    "charges",
    "charge_amount",
}


def reachability(records: list[dict], profile: str, output: Path = OUTPUT) -> list[dict]:
    evidence_policy, field_policy = _registries(profile)
    audit = PolicyReachabilityAudit(evidence_policy, field_policy)
    routes = RouteRegistry.load()
    fields = {(row["family"], row["field_name"]) for row in records}
    for family in ("CMS1500", "UB04"):
        fields.update((family, name) for name in field_policy.required_fields(family))
    results = []
    for family, field_name in sorted(fields):
        available = {EvidenceClass.E3, EvidenceClass.E4}
        if any(row["family"] == family and row["field_name"] == field_name for row in records):
            available.add(EvidenceClass.E1)
        canonical = field_policy.canonical_name(family, field_name)
        if routes.find(field_name, family, mode="runtime") or routes.find(
            canonical, family, mode="runtime"
        ):
            available.add(EvidenceClass.E2)
        if field_name in _E6_CAPABLE or canonical in _E6_CAPABLE:
            available.add(EvidenceClass.E6)
        policy = field_policy.for_field(family, field_name)
        result = audit.audit_field(
            family,
            field_name,
            available,
            explicit_status=evidence_policy.reachability_disposition(
                field_name,
                policy.criticality,
                family,
            ),
        )
        results.append(result.model_dump(mode="json"))
    _write_json(
        output / f"profile_{profile.lower()}/policy_reachability.json",
        {
            "profile": profile,
            "results": results,
            "status_counts": dict(Counter(item["status"] for item in results)),
        },
    )
    return results


def forensics(
    records: list[dict], profile_a: dict, reach: list[dict], output: Path = OUTPUT
) -> dict:
    decision_by_key = {
        (item["document_id"], item["field_name"]): item for item in profile_a["fields"]
    }
    claims = {item["claim_id"]: item for item in profile_a["claims"]}
    reachability_by_key = {(item["document_family"], item["field_name"]): item for item in reach}
    forensic_rows = []
    bucket_counts = Counter()
    correct_reviewed = e3_only = unreachable = 0
    for row in records:
        result = decision_by_key[(row["document_id"], row["field_name"])]
        decision = result["field_decision"]
        if decision["disposition"] in ACCEPTED:
            continue
        claim = claims[row["document_id"]]
        missing = set(decision["missing_evidence"])
        reach_result = reachability_by_key.get((row["family"], row["field_name"]))
        if row["exact"]:
            bucket = "CORRECT_BUT_EVIDENCE_INSUFFICIENT"
            correct_reviewed += 1
        elif decision.get("conflicting_evidence") or (decision.get("evidence_bundle") or {}).get(
            "contradictions"
        ):
            bucket = "TRUE_AMBIGUITY"
        elif row["final_value"]:
            bucket = "WRONG_AND_SAFELY_REJECTED"
        else:
            bucket = "UNSUPPORTED_OR_MISSING"
        bucket_counts[bucket] += 1
        if row["exact"] and missing == {"E3"}:
            e3_only += 1
        policy_unreachable = bool(reach_result and reach_result["status"] == "UNREACHABLE_POLICY")
        unreachable += int(row["exact"] and policy_unreachable)
        bundle = decision.get("evidence_bundle") or {}
        evidence_items = bundle.get("evidence_items") or []
        policy = row["field_policy_metadata"]
        forensic_rows.append(
            {
                "document_id": row["document_id"],
                "page_id": row["page_id"],
                "family": row["family"],
                "field": row["field_name"],
                "criticality": decision["criticality"],
                "required": decision["required"],
                "blocks_stp": decision["blocks_stp"],
                "truth": row["truth"],
                "final_extracted_value": row["final_value"],
                "correct": row["exact"],
                "primary_candidate": row["primary_candidate"],
                "secondary_candidate": row["secondary_candidate"],
                "candidate_agreement": row["candidate_agreement"],
                "localization_mode": row["localization_mode"],
                "localization_evidence": row["localization_evidence"],
                "datatype_validation": row["deterministic_validation"],
                "cross_field_evidence": row["cross_field_evidence"],
                "reference_evidence": row["reference_evidence"],
                **{
                    f"E{index}": any(
                        item["evidence_class"] == f"E{index}" for item in evidence_items
                    )
                    for index in range(1, 9)
                },
                "current_policy": bundle.get("policy_id"),
                "required_combinations": (
                    reach_result["configured_combinations"] if reach_result else []
                ),
                "missing_evidence": sorted(missing),
                "field_decision": decision["disposition"],
                "reason_codes": decision["reason_codes"],
                "claim_disposition": claim["disposition"],
                "claim_blocker": row["field_name"] in claim["blocking_unresolved_fields"],
                "review_bucket": bucket,
                "policy_reachability": reach_result["status"] if reach_result else None,
                "field_policy_id": policy["policy_id"],
            }
        )
    _write_jsonl(output / "field_hitl_forensics.jsonl", forensic_rows)
    measurement = {
        "review_fields": len(forensic_rows),
        "correct_and_reviewed": correct_reviewed,
        "correct_and_reviewed_percent_all_fields": correct_reviewed / len(records),
        "correct_and_reviewed_percent_reviewed_fields": correct_reviewed
        / max(1, len(forensic_rows)),
        "correct_and_reviewed_e3_only_missing": e3_only,
        "correct_and_reviewed_policy_unreachable": unreachable,
        "correct_but_reviewed_rate": correct_reviewed / len(records),
        "review_buckets": dict(bucket_counts),
        "by_field": dict(Counter(item["field"] for item in forensic_rows if item["correct"])),
        "by_family": dict(Counter(item["family"] for item in forensic_rows if item["correct"])),
        "by_criticality": dict(
            Counter(item["criticality"] for item in forensic_rows if item["correct"])
        ),
        "claims_blocked": sum(
            bool(item["blocking_unresolved_fields"]) for item in profile_a["claims"]
        ),
        "single_blocker_claims": sum(
            len(item["blocking_unresolved_fields"]) == 1 for item in profile_a["claims"]
        ),
    }
    _write_json(output / "review_forensics_summary.json", measurement)
    return measurement


def run(output: Path = OUTPUT) -> dict:
    records = build_replay_input(output)
    profiles = {name: replay(name, records, output) for name in ("A", "B", "C")}
    baseline = profiles["A"]["metrics"]
    expected = {
        "safe_field_coverage": 0.29789473684210527,
        "field_hitl": 0.7021052631578948,
        "claim_hitl": 1.0,
        "claim_stp": 0.0,
        "accepted_precision": 1.0,
        "false_accepts": 0,
    }
    mismatches = {
        key: {"expected": value, "actual": baseline[key]}
        for key, value in expected.items()
        if abs(baseline[key] - value) > 1e-12
    }
    if mismatches:
        raise RuntimeError(f"PROFILE_A_REPRODUCTION_FAILED:{mismatches}")
    reach = {name: reachability(records, name, output) for name in ("A", "B", "C")}
    unexpected = [
        f"{item['document_family']}.{item['field_name']}"
        for item in reach["C"]
        if item["status"] == "UNREACHABLE_POLICY"
    ]
    if unexpected:
        raise RuntimeError("UNEXPECTED_UNREACHABLE_POLICY:" + ",".join(unexpected))
    forensic = forensics(records, profiles["A"], reach["A"], output)
    summary = {
        "profile_metrics": {name: value["metrics"] for name, value in profiles.items()},
        "profile_a_reproduced_exactly": True,
        "forensics": forensic,
        "ocr_reruns": 0,
        "first_frontier": {
            "safe_field_coverage_target_met": profiles["C"]["metrics"]["safe_field_coverage"]
            >= 0.70,
            "field_hitl_target_met": profiles["C"]["metrics"]["field_hitl"] <= 0.30,
            "claim_hitl_target_met": profiles["C"]["metrics"]["claim_hitl"] <= 0.40,
            "claim_stp_target_met": profiles["C"]["metrics"]["claim_stp"] >= 0.60,
            "safety_target_met": profiles["C"]["metrics"]["safety_gate_passed"],
        },
    }
    _write_json(output / "phase8_4_summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
