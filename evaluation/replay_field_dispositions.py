"""Re-evaluate saved field decisions without OCR, source images, labels, or publication."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from evaluation.validation_blockers import CATEGORIES, classify_validation
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.extraction import ExtractedField
from packages.evidence_decision import DecisionContext
from packages.evidence_decision.adapters import ocr_candidates_from_field
from packages.runtime_policy_coverage import policy_coverage
from packages.runtime_profile import DecisionServiceFactory


def replay(directory: Path, output: Path, *, as_of_date: date) -> dict:
    bundle = DecisionServiceFactory.from_profile()
    coverage = policy_coverage(bundle.field_policy, bundle.evidence_decision.evidence_policy)
    if coverage["status"] != "READY":
        raise ValueError("CONFIGURATION_INCOMPLETE")
    path = directory / "raw_execution.local.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    data = json.loads(path.read_text(encoding="utf-8"))
    validator = DeterministicEvidenceService(as_of_date=as_of_date)
    rows = []
    for claim in data["claims"]:
        validations = [e["envelope"]["payload"] for e in claim["events"]
                       if e["topic"] == "claim.validated"]
        if claim["fields"] and not validations:
            raise ValueError("RECORDED_VALIDATION_FAMILY_REQUIRED")
        if not claim["fields"]:
            continue
        family: str = validations[-1]["form_type"]
        for saved in claim["fields"]:
            field = ExtractedField.model_validate({key:value for key,value in saved.items()
                                                   if key in ExtractedField.model_fields})
            policy = bundle.field_policy.for_field(family, field.field_name)
            if not policy.configured:
                raise ValueError("CONFIGURATION_INCOMPLETE: observed field")
            validation = validator.evaluate(policy.canonical_field_name,
                                            field.normalized_value or field.raw_value)
            decision = bundle.evidence_decision.decide(DecisionContext(
                field_id=str(field.field_id), field_name=field.field_name, document_family=family,
                criticality=policy.criticality, required=policy.required, blocks_stp=policy.blocks_stp,
                candidates=ocr_candidates_from_field(field), deterministic_evidence=validation.evidence,
                hard_validation_passed=validation.passed,
                claim_id=validations[-1].get("claim_id"),
                document_id=str(claim["document_id"]),
                form_identity_authority=validations[-1].get("form_identity_authority") or {},
                claim_membership_authority=validations[-1].get("claim_membership") or {},
            ))
            semantic = [r for r in decision.reason_codes if r in {
                "EXPLICIT_SAME_REFERENCE_REVIEW_REQUIRED", "PRINTED_FIELD_SOURCE_AUTHORITY_REQUIRED",
                "ATTACHMENT_CANNOT_OVERRIDE_CLAIM_FORM", "PRINTED_DERIVED_DISAGREEMENT"}]
            rows.append({"document_id":claim["document_id"], "field_id":str(field.field_id),
                         "field":field.field_name, "family":family, "canonical_field":policy.canonical_field_name,
                         "criticality":policy.criticality.value, "required":policy.required,
                         "disposition_policy":policy.disposition_mode,
                         "validation_rule":policy.validation_rule, "validation_status":validation.status.value,
                         "validation_blocker":not validation.passed, "validation_reasons":validation.failure_reasons,
                         "evidence_requirements":list(policy.evidence_requirements),
                         "semantic_blockers":semantic,
                         "authority_state":decision.authority.state.value,
                         "authority_blockers":decision.authority.blockers,
                         "semantic_authority_verified":decision.authority.state.value == "AUTHORITY_VERIFIED",
                         "validation_categories":classify_validation(validation.failure_reasons) if not validation.passed else [],
                         "consensus_required":"INDEPENDENT_CONFIRMATION" in policy.evidence_requirements,
                         "authority_required":bool(set(policy.evidence_requirements) & {
                             "FORM_IDENTITY_AUTHORITY", "OWNER_MEMBERSHIP", "AUTHORITATIVE_REFERENCE"}),
                         "reference_required":"AUTHORITATIVE_REFERENCE" in policy.evidence_requirements,
                         "auto_eligible":decision.disposition.value in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"},
                         "disposition":decision.disposition.value, "reason_codes":decision.reason_codes})
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError("SAVED_OCR_CHANGED_DURING_REPLAY")
    aggregate = {
        "scope":"SAVED_OCR_DISPOSITION_REPLAY_ONLY", "scans":len(data["claims"]), "fields":len(rows),
        "auto_eligible":sum(r["auto_eligible"] for r in rows),
        "validation_blocked_fields":sum(r["validation_blocker"] for r in rows),
        "semantic_blocked_fields":sum(bool(r["semantic_blockers"]) for r in rows),
        "semantic_authority_unverified_fields":sum(not r["semantic_authority_verified"] for r in rows),
        "consensus_required_fields":sum(r["consensus_required"] for r in rows),
        "authority_required_fields":sum(r["authority_required"] for r in rows),
        "reference_required_fields":sum(r["reference_required"] for r in rows),
        "hitl_required_fields":sum(r["disposition"] == "HUMAN_REVIEW_REQUIRED" for r in rows),
        "unconfigured_fields":sum("FIELD_POLICY_NOT_CONFIGURED" in r["reason_codes"] for r in rows),
        "authority_state_counts":dict(Counter(row["authority_state"] for row in rows)),
        "authority_blocker_counts":dict(Counter(reason for row in rows for reason in row["authority_blockers"])),
        "validation_categories":{category:sum(category in row["validation_categories"] for row in rows) for category in CATEGORIES},
        "validation_reason_counts":dict(Counter(reason for row in rows for reason in row["validation_reasons"])),
        "reason_counts":dict(Counter(reason for row in rows for reason in row["reason_codes"])),
        "source_execution_sha256":before, "saved_ocr_bytes_unchanged":True,
        "ocr_calls":0, "models_changed":False, "accuracy":"NOT_EVALUABLE",
        "accepted_precision":"NOT_EVALUABLE", "production_stp_safe":"NOT_EVALUABLE",
        "as_of_date":as_of_date.isoformat(), "runtime_profile":bundle.profile.decision_identity(),
        "counter_interpretation":"Blocker categories overlap. No detected semantic blocker is not verified semantic authority.",
    }
    (directory / "disposition_replay_authority_v1.local.json").write_text(
        json.dumps({"aggregate":aggregate, "fields":rows},indent=2)+"\n",encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    (output / "disposition_replay.json").write_text(json.dumps(aggregate,indent=2)+"\n",encoding="utf-8")
    (output / "policy_coverage.json").write_text(json.dumps(coverage,indent=2)+"\n",encoding="utf-8")
    return aggregate
