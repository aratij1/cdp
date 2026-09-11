"""Wire real OCR predictions through EvidenceDecisionService and
ClaimDecisionService so claim-level STP/HITL become computable for the
`claims/` dataset -- rather than reporting only raw/normalized field
accuracy with no decision-layer authority.

Reads an `evaluation.schemas.PredictionDataset` (as produced by
`evaluation/run_atomic_ocr.py`, which already records per-candidate OCR
evidence in each field's `metadata.ocr_candidates`) and the matching
`GroundTruthDataset`, replays each field through the real
`EvidenceDecisionService.decide()` using genuine OCR candidates and
deterministic validation (`packages.deterministic_evidence`), then rolls
per-claim field decisions up through the real `ClaimDecisionService.decide()`.

This does not invent evidence: registration confidence comes from the real
`crop_manifest.json` alignment_score/reprojection_error already produced by
`evaluation/build_field_crops.py`; there is no reference-data lookup (all
providers are disabled in config/reference_enrichment.yaml). Calibration is
loaded from the real, shipped config/calibration/field_models_v1.json (the
same file config/runtime_profiles/canonical_runtime_v1.yaml pins) via an
explicit EvidenceReconciler(calibration=...), matching the pattern in
packages/runtime_profile/decision_factory.py -- an earlier version of this
script left EvidenceDecisionService to default to an empty
EvidenceReconciler(), which silently ignored the shipped calibration file
and made every field register as "uncalibrated-v0" regardless of what was
configured. Fields that genuinely have no calibration model still hit the
intentional fail-closed CALIBRATION_REQUIRED_FOR_CRITICAL_ACCEPTANCE gate;
this script does not work around that gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.claim_evidence import ClaimEvidenceBuilder
from packages.confidence import CalibrationRegistry
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.evidence import StructuralLocalizationEvidence, StructuralLocalizationType
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.evidence_router import ReferenceSourceState
from packages.field_policy import FieldPolicyRegistry
from packages.ocr.contracts import OCRCandidate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATION_REGISTRY_PATH = ROOT / "config" / "calibration" / "field_models_v1.json"
ACCEPTED = {
    FieldDisposition.AUTO_ACCEPTED,
    FieldDisposition.REFERENCE_CONFIRMED,
    FieldDisposition.HUMAN_CONFIRMED,
}


def _registration_confidence(crop_manifest: dict, document_id: str, field_name: str) -> float | None:
    entry = crop_manifest.get(f"{document_id}/{field_name}")
    if entry is None:
        return None
    # alignment_score is a homography inlier ratio in [0, 1]; a huge
    # reprojection_error means the homography degenerated even if the
    # inlier ratio looks plausible, so treat that case as zero confidence
    # rather than silently trusting a bad warp.
    if entry.get("reprojection_error", 0.0) > 10.0:
        return 0.0
    return max(0.0, min(1.0, float(entry.get("alignment_score", 0.0))))


def _structural_localization(
    crop_manifest: dict, document_id: str, field_name: str,
) -> StructuralLocalizationEvidence | None:
    """Build real E3 evidence from the same fields production's
    REGISTERED_FIXED branch checks (workers/validation/consumer.py
    qualified_structural_localization) -- not fabricated confidence.
    Confirmation requires: template/document compatibility not INCOMPATIBLE,
    the homography accepted, valid transformed corners, a real alignment
    score >= 0.80 (production's own structural-confidence floor, distinct
    from and stricter than the 0.60 registration-confidence gate used for
    wrong-crop suspicion), and no wrong-crop signal. Anything missing or
    unmeasured returns unconfirmed evidence rather than skipping E3 --
    EvidenceDecisionService still requires positive confirmation to count
    it, so an honestly-unconfirmed record cannot inflate acceptance."""
    entry = crop_manifest.get(f"{document_id}/{field_name}")
    if entry is None:
        return None
    confidence = _registration_confidence(crop_manifest, document_id, field_name) or 0.0
    registration_accepted = entry.get("registration_accepted")
    corner_validity = entry.get("corner_validity")
    compatibility_status = entry.get("compatibility_status")
    confirmed = bool(
        compatibility_status != "INCOMPATIBLE"
        and registration_accepted is True
        and corner_validity is True
        and confidence >= 0.80
    )
    reasons = [
        "STRUCTURAL_CONFIDENCE_PASSED" if confidence >= 0.80 else "STRUCTURAL_CONFIDENCE_FAILED",
        "REGISTRATION_ACCEPTED" if registration_accepted else "REGISTRATION_NOT_ACCEPTED",
        "CORNER_VALIDITY_PASSED" if corner_validity else "CORNER_VALIDITY_FAILED",
        f"COMPATIBILITY:{compatibility_status or 'UNKNOWN'}",
    ]
    # packages.evidence.builder.build_evidence_bundle only counts E3 for a
    # critical field when it is FIELD-specific (field_bbox, positive_bounded_roi
    # and geometry_valid all truthy) -- a page-level registration score alone
    # is not enough, by design. `local.box`/`local.accepted` from
    # align_field_crop's real per-field template-match search (persisted as
    # crop_box/local_alignment_accepted) are genuine, field-specific
    # measurements, not derived from the page-level score, so they are used
    # here rather than left unset.
    crop_box = entry.get("crop_box")
    positive_bbox = bool(
        crop_box and len(crop_box) == 4 and crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]
    )
    local_alignment_accepted = entry.get("local_alignment_accepted")
    return StructuralLocalizationEvidence(
        evidence_type=StructuralLocalizationType.TEMPLATE_REGISTRATION_CONFIRMED,
        confidence=confidence,
        confirmed=confirmed,
        reason_codes=tuple(reasons),
        source="evaluation.build_field_crops:sift_flann_ransac_homography",
        field_name=field_name,
        field_bbox=tuple(float(v) for v in crop_box) if positive_bbox else None,
        positive_bounded_roi=positive_bbox,
        geometry_valid=bool(local_alignment_accepted) if local_alignment_accepted is not None else None,
    )


def _build_candidates(field: dict) -> list[OCRCandidate]:
    box = BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1)
    raw_candidates = (field.get("metadata") or {}).get("ocr_candidates") or []
    if not raw_candidates:
        return []
    return [
        OCRCandidate(
            value=item.get("value"),
            raw_value=str(item.get("raw") or item.get("value") or ""),
            engine=str(item.get("engine") or "unknown"),
            model_name=str(item.get("engine") or "ocr"),
            model_version="claims-replay-v1",
            preprocessing_variant=str(item.get("preprocessing") or "unknown"),
            raw_confidence=float(item.get("confidence") or 0.0),
            calibrated_confidence=None,
            bounding_box=box,
            latency_ms=0.0,
        )
        for item in raw_candidates
    ]


def replay(
    predictions: dict, ground_truth: dict, crop_manifest: dict,
    service_line_totals: dict | None = None,
    calibration_registry_path: Path = DEFAULT_CALIBRATION_REGISTRY_PATH,
) -> tuple[list[dict], dict]:
    calibration = (
        CalibrationRegistry.load(calibration_registry_path)
        if calibration_registry_path.is_file() else CalibrationRegistry()
    )
    evidence_service = EvidenceDecisionService(
        route_mode="evaluation", reconciler=EvidenceReconciler(calibration=calibration),
    )
    deterministic_service = DeterministicEvidenceService()
    claim_evidence_builder = ClaimEvidenceBuilder.load()
    claim_decision_service = ClaimDecisionService.load()
    field_policy_registry = FieldPolicyRegistry.load()

    truth_by_id = {doc["document_id"]: doc for doc in ground_truth["documents"]}
    claim_rows: list[dict] = []

    for document in predictions["documents"]:
        document_id = document["document_id"]
        truth_doc = truth_by_id.get(document_id)
        if truth_doc is None:
            continue
        form_type = truth_doc["form_type"]
        expected_by_field = {f["field_name"]: f for f in truth_doc["fields"]}

        field_decisions = []
        field_rows = []
        claim_values: dict[str, object] = {}
        line_total = (service_line_totals or {}).get(document_id)
        if line_total is not None:
            # `_cross_field` in packages.deterministic_evidence splits on
            # "," and sums each token as a Decimal; a single pre-summed
            # value is one token, matching that parsing contract exactly.
            claim_values["service_line_charges"] = line_total
        for field in document["fields"]:
            field_name = field["field_name"]
            candidates = _build_candidates(field)
            claim_values[field_name] = field.get("normalized_value") or field.get("raw_value")
            deterministic = deterministic_service.evaluate(
                field_name, field.get("raw_value"), claim_values=claim_values,
            )
            registration_confidence = _registration_confidence(
                crop_manifest, document_id, field_name,
            )
            structural_localization = _structural_localization(
                crop_manifest, document_id, field_name,
            )
            expected_field = expected_by_field.get(field_name)
            criticality = field_policy_registry.for_field(form_type, field_name).criticality
            decision = evidence_service.decide(DecisionContext(
                field_name=field_name,
                document_family=form_type,
                criticality=criticality,
                candidates=candidates,
                deterministic_evidence=deterministic.evidence,
                cross_field_evidence=deterministic.cross_field_evidence,
                hard_validation_passed=deterministic.passed,
                registration_confidence=registration_confidence,
                structural_localization=structural_localization,
                wrong_crop_suspected=registration_confidence is not None and registration_confidence < 0.60,
                reference=None,
                reference_source_state=ReferenceSourceState.DISABLED,
            ))
            field_decisions.append(decision)
            accepted = decision.disposition in ACCEPTED
            actual_value = field.get("normalized_value") or field.get("raw_value")
            # A field absent from ground truth (e.g. patient_name, which the
            # source fixed-width records never carry as a combined name --
            # see evaluation/build_claims_manifest_and_truth.py's
            # CMS1500_FIELD_MAP) is architecturally unscoreable: there is no
            # expected value to compare against, correct or not. Governance
            # (decision/accepted/false_accept) still evaluates the field
            # normally -- only accuracy scoring excludes it, so it cannot
            # silently count as an automatic wrong answer in the denominator.
            scoreable = expected_field is not None
            correct = (
                scoreable
                and (actual_value or "").strip().casefold()
                == (expected_field.get("expected_normalized") or "").strip().casefold()
            )
            field_rows.append({
                "field_name": field_name,
                "critical": bool(expected_field.get("critical")) if expected_field else False,
                "disposition": decision.disposition.value,
                "reason_codes": decision.reason_codes,
                "registration_confidence": registration_confidence,
                "accepted": accepted,
                "scoreable": scoreable,
                "correct": correct,
                "false_accept": accepted and scoreable and not correct,
            })

        claim_evidence = claim_evidence_builder.build(
            claim_id=document_id,
            document_family=form_type,
            claim_values=claim_values,
            service_lines=[],
        )
        claim_decision = claim_decision_service.decide(ClaimDecisionContext(
            claim_id=document_id,
            document_family=form_type,
            field_decisions=field_decisions,
            claim_evidence=claim_evidence.evidence_items,
            contradictions=claim_evidence.contradictions,
            policy_id=claim_decision_service.policy_id,
            policy_version=claim_decision_service.policy_version,
            dependent_field_groups=(
                [["total_charge", "charges", "charge_amount"]] if form_type == "CMS1500"
                else [["revenue_code", "hcpcs_code", "units", "charges", "charge_amount"]]
            ),
        ))
        claim_rows.append({
            "document_id": document_id,
            "form_type": form_type,
            "stp_eligible": claim_decision.stp_eligible,
            "disposition": claim_decision.disposition.value,
            "blocking_unresolved_fields": claim_decision.blocking_unresolved_fields,
            "reason_codes": claim_decision.reason_codes,
            "fields": field_rows,
        })

    total = len(claim_rows)
    stp_count = sum(row["stp_eligible"] for row in claim_rows)
    all_field_rows = [f for row in claim_rows for f in row["fields"]]
    # Accuracy (correct/false-accept) is only meaningful over fields that
    # ground truth actually labels; a field like patient_name that the
    # source fixed-width records never carry as a combined value has no
    # expected answer to be right or wrong about, and must not silently
    # count as an automatic 0% in the denominator. Acceptance-rate/field
    # counts intentionally still cover every field, since those describe
    # what the decision pipeline did, not whether it matched ground truth.
    scoreable_field_rows = [f for f in all_field_rows if f["scoreable"]]
    critical_field_rows = [f for f in scoreable_field_rows if f["critical"]]
    metrics = {
        "total_claims": total,
        "claim_stp_count": stp_count,
        "claim_stp_rate": stp_count / total if total else 0.0,
        "claim_hitl_count": total - stp_count,
        "claim_hitl_rate": (total - stp_count) / total if total else 0.0,
        "field_count": len(all_field_rows),
        "field_accepted_rate": (
            sum(f["accepted"] for f in all_field_rows) / len(all_field_rows)
            if all_field_rows else 0.0
        ),
        "scoreable_field_count": len(scoreable_field_rows),
        "field_correct_rate": (
            sum(f["correct"] for f in scoreable_field_rows) / len(scoreable_field_rows)
            if scoreable_field_rows else 0.0
        ),
        "critical_field_count": len(critical_field_rows),
        "critical_field_correct_rate": (
            sum(f["correct"] for f in critical_field_rows) / len(critical_field_rows)
            if critical_field_rows else None
        ),
        "false_accepts": sum(f["false_accept"] for f in all_field_rows),
        "critical_false_accepts": sum(f["false_accept"] for f in critical_field_rows),
        "critical_false_accept_rate": (
            sum(f["false_accept"] for f in critical_field_rows) / len(critical_field_rows)
            if critical_field_rows else None
        ),
    }
    return claim_rows, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument(
        "--crop-manifest", type=Path,
        default=ROOT / "evaluation_results" / "field_crops" / "crop_manifest.json",
    )
    parser.add_argument(
        "--service-line-totals", type=Path,
        default=ROOT / "evaluation_data" / "service_line_totals.json",
    )
    parser.add_argument(
        "--calibration-registry", type=Path, default=DEFAULT_CALIBRATION_REGISTRY_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    crop_manifest = (
        json.loads(args.crop_manifest.read_text(encoding="utf-8"))
        if args.crop_manifest.is_file() else {}
    )
    service_line_totals = (
        json.loads(args.service_line_totals.read_text(encoding="utf-8"))
        if args.service_line_totals.is_file() else {}
    )

    claim_rows, metrics = replay(
        predictions, ground_truth, crop_manifest, service_line_totals,
        args.calibration_registry,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"claims": claim_rows, "metrics": metrics}, indent=2), encoding="utf-8",
    )
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
