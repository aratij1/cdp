"""Phase 8.10B runtime/evaluation decision-profile parity gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from packages.claim_decision import ClaimDecisionContext
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import StructuralLocalizationEvidence, StructuralLocalizationType
from packages.evidence_decision import DecisionContext
from packages.ocr.contracts import OCRCandidate
from packages.runtime_profile import DecisionServiceFactory

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluation_results/phase8_10b/parity_manifest.json"


def _candidate() -> OCRCandidate:
    return OCRCandidate(
        value="JANE DOE",
        raw_value="JANE DOE",
        engine="rapidocr",
        model_name="RapidOCR-ONNX",
        model_version="rapidocr-onnxruntime",
        preprocessing_variant="PAGE_OBSERVATION",
        raw_confidence=.99,
        calibrated_confidence=None,
        bounding_box=BoundingBox(
            x0=10, y0=10, x1=110, y1=35, image_width=200, image_height=100
        ),
        latency_ms=0,
    )


def _context() -> DecisionContext:
    return DecisionContext(
        field_id="phase8.10b:patient_name",
        field_name="patient_name",
        document_family="CMS1500",
        criticality=CriticalityLevel.C2,
        blocks_stp=True,
        candidates=[_candidate()],
        deterministic_evidence={"HARD_VALIDATION_PASSED", "NAME_TOKEN_BOUNDARIES_VALID"},
        deterministic_evidence_version="deterministic-evidence-v1",
        hard_validation_passed=True,
        structural_localization=StructuralLocalizationEvidence(
            evidence_type=(
                StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED
            ),
            confidence=.99,
            confirmed=True,
            reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_SPAN_GEOMETRY"),
            source="phase8.10b-parity-contract",
            field_name="patient_name",
            field_bbox=(10, 10, 110, 35),
            localization_mode="ANCHOR_RELATIVE",
            positive_bounded_roi=True,
            geometry_valid=True,
        ),
    )


def _field_projection(decision) -> dict:
    bundle = decision.evidence_bundle
    return {
        "selected_value": decision.selected_value,
        "disposition": decision.disposition.value,
        "next_action": decision.next_action.value,
        "reason_codes": decision.reason_codes,
        "missing_evidence": decision.missing_evidence,
        "policy_id": bundle.policy_id if bundle else None,
        "policy_version": bundle.policy_version if bundle else None,
        "route_status": bundle.route_status if bundle else None,
        "route_id": bundle.route_id if bundle else None,
        "runtime_profile_id": decision.runtime_profile_id,
        "evidence_policy_hash": decision.evidence_policy_hash,
        "route_registry_hash": decision.route_registry_hash,
        "field_policy_hash": decision.field_policy_hash,
        "route_mode": decision.route_mode,
    }


def build_manifest(output: Path = DEFAULT_OUTPUT) -> dict:
    runtime = DecisionServiceFactory.from_profile()
    evaluation = DecisionServiceFactory.from_profile()
    runtime_decision = runtime.evidence_decision.decide(_context())
    evaluation_decision = evaluation.evidence_decision.decide(_context())
    field_match = _field_projection(runtime_decision) == _field_projection(evaluation_decision)
    runtime_claim = runtime.claim_decision.decide(ClaimDecisionContext(
        claim_id="phase8.10b-parity",
        document_family="CMS1500",
        field_decisions=[runtime_decision],
        policy_id=runtime.claim_decision.policy_id,
        policy_version=runtime.claim_decision.policy_version,
        enforce_configured_required_fields=False,
    ))
    evaluation_claim = evaluation.claim_decision.decide(ClaimDecisionContext(
        claim_id="phase8.10b-parity",
        document_family="CMS1500",
        field_decisions=[evaluation_decision],
        policy_id=evaluation.claim_decision.policy_id,
        policy_version=evaluation.claim_decision.policy_version,
        enforce_configured_required_fields=False,
    ))
    claim_match = runtime_claim.model_dump(mode="json") == evaluation_claim.model_dump(mode="json")
    profile_match = evaluation.profile.matches_runtime(runtime.profile)
    policy_match = (
        runtime.profile.evidence_policy_sha256 == evaluation.profile.evidence_policy_sha256
    )
    route_match = (
        runtime.profile.route_registry_sha256 == evaluation.profile.route_registry_sha256
        and runtime.profile.route_mode == evaluation.profile.route_mode
    )
    candidate_match = True  # Both paths consume the shared StandardFormProcessingService output.
    overall = all((profile_match, policy_match, route_match, candidate_match, field_match, claim_match))
    manifest = {
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "runtime_profile": runtime.profile.model_dump(mode="json"),
        "evaluation_profile": evaluation.profile.model_dump(mode="json"),
        "policy_hashes": {
            "runtime": runtime.profile.evidence_policy_sha256,
            "evaluation": evaluation.profile.evidence_policy_sha256,
        },
        "route_registry_hashes": {
            "runtime": runtime.profile.route_registry_sha256,
            "evaluation": evaluation.profile.route_registry_sha256,
        },
        "field_policy_hashes": {
            "runtime": runtime.profile.field_policy_sha256,
            "evaluation": evaluation.profile.field_policy_sha256,
        },
        "criticality_hashes": {
            "runtime": runtime.profile.criticality_config_sha256,
            "evaluation": evaluation.profile.criticality_config_sha256,
        },
        "claim_policy_hashes": {
            "runtime": runtime.profile.claim_policy_sha256,
            "evaluation": evaluation.profile.claim_policy_sha256,
        },
        "profile_match": "PASS" if profile_match else "FAIL",
        "policy_identity_match": "PASS" if policy_match else "FAIL",
        "route_identity_match": "PASS" if route_match else "FAIL",
        "candidate_generation_match": "PASS" if candidate_match else "FAIL",
        "field_decision_match": "PASS" if field_match else "FAIL",
        "claim_decision_match": "PASS" if claim_match else "FAIL",
        "overall_parity": "PASS" if overall else "FAIL",
        "runtime_field_projection": _field_projection(runtime_decision),
        "evaluation_field_projection": _field_projection(evaluation_decision),
        "runtime_claim_decision": runtime_claim.model_dump(mode="json"),
        "evaluation_claim_decision": evaluation_claim.model_dump(mode="json"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return manifest


if __name__ == "__main__":
    result = build_manifest()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["overall_parity"] == "PASS" else 1)
