"""Truth-blind Tesseract confirmation experiment for Phase 8 validation fields."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from copy import deepcopy
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

from evaluation.phase8_8_generalization import DATA_ROOT, SOURCE_IDS
from packages.claim_decision import ClaimDecisionContext
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.evidence import EvidencePolicy, StructuralLocalizationEvidence
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.field_localization import FieldDefinitionRegistry
from packages.local_evidence_cascade import decide_local_candidate
from packages.runtime_profile import DecisionServiceFactory
from workers.cascade.tesseract_adapter import for_field_type

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "evaluation_results/phase8_11/candidate/extraction_records.jsonl"
OUTPUT = ROOT / "evaluation_results/phase8_12/tesseract_confirmation"
PROFILES = ("original", "upscale_2x")
REVIEW_DISPOSITIONS = {"ESCALATE", "HUMAN_REVIEW_REQUIRED", "INSUFFICIENT_EVIDENCE"}
ACCEPTED_DISPOSITIONS = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _canonical(datatype: str, value: object) -> str:
    decision = decide_local_candidate(str(value or ""), datatype)
    selected = decision.normalized_value or value or ""
    return re.sub(r"[^A-Z0-9]", "", str(selected).upper())


def _engine_type(field: str, datatype: str) -> str:
    lowered = datatype.casefold()
    if "date" in lowered or "date" in field or "dob" in field:
        return "date"
    if "npi" in field:
        return "npi"
    if any(token in field for token in ("charge", "amount", "paid")):
        return "currency"
    if any(token in lowered for token in ("code", "identifier")):
        return "code"
    return "text"


def _registries() -> dict[str, FieldDefinitionRegistry]:
    return {
        family: FieldDefinitionRegistry.load(
            ROOT / f"config/field_definitions/{'cms1500' if family == 'CMS1500' else 'ub04'}_v1.yaml"
        )
        for family in ("CMS1500", "UB04")
    }


def _decision_correct(
    registries: dict[str, FieldDefinitionRegistry], row: dict, selected: str | None
) -> bool:
    datatype = str(registries[row["family"]].get(row["family"], row["field_name"]).datatype)
    return _canonical(datatype, selected) == _canonical(datatype, row["truth"])


def generate(output: Path = OUTPUT) -> dict:
    """Generate candidates without loading expected values or field decisions."""
    registries = _registries()
    manifests = {
        source: {
            row["document_id"]: row
            for row in json.loads((DATA_ROOT / source / "manifest.json").read_text("utf-8"))["documents"]
        }
        for source in SOURCE_IDS
    }
    records = []
    for row in _rows(INPUT):
        # INPUT is the Phase 8.11 validation-only consolidation (140 fields
        # from each development source); the locked-holdout directory is not
        # an input to this experiment.
        bbox_values = (row.get("localization_evidence") or {}).get("bbox")
        if not bbox_values:
            continue
        source, family, field = row["source"], row["family"], row["field_name"]
        document = manifests[source][row["document_id"]]
        definition = registries[family].get(family, field)
        datatype = str(definition.datatype)
        bbox = tuple(round(float(value)) for value in bbox_values)
        with Image.open(DATA_ROOT / source / document["file"]) as opened:
            crop = opened.convert("RGB").crop(bbox)
        engine = for_field_type(_engine_type(field, datatype))
        for profile in PROFILES:
            prepared = crop if profile == "original" else ImageOps.grayscale(crop).resize(
                (crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS
            )
            started = time.perf_counter()
            try:
                tokens = engine.extract(prepared)
                raw = " ".join(token.text for token in tokens).strip()
                confidence = sum(token.confidence for token in tokens) / len(tokens) if tokens else 0.0
                failure = None
            except Exception as exc:  # noqa: BLE001 - provider failure is evidence
                raw, confidence, failure = "", 0.0, f"{type(exc).__name__}: {exc}"
            records.append({
                "document_id": row["document_id"], "source": source, "family": family,
                "field_name": field, "datatype": datatype, "profile": profile,
                "raw_value": raw or None, "normalized_value": _canonical(datatype, raw),
                "confidence": confidence, "latency_ms": (time.perf_counter() - started) * 1000,
                "failure": failure or ("NO_EVIDENCE" if not raw else None),
                "crop_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
                "candidate_authority": "REVIEW_ONLY", "evaluation_truth_loaded": False,
            })
    output.mkdir(parents=True, exist_ok=True)
    candidate_path = output / "candidates.jsonl"
    candidate_path.write_text("".join(json.dumps(row) + "\n" for row in records), "utf-8")
    report = {
        "fields": len({(r["document_id"], r["field_name"]) for r in records}),
        "candidate_records": len(records), "profiles": list(PROFILES),
        "fields_with_response": len({(r["document_id"], r["field_name"]) for r in records if r["raw_value"]}),
        "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "evaluation_truth_loaded": False, "locked_holdout_accessed": False,
    }
    (output / "generation.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def evaluate(
    output: Path = OUTPUT,
    minimum_confidence: float = 0.85,
    minimum_profile_agreement: int = 2,
) -> dict:
    candidates = _rows(output / "candidates.jsonl")
    extraction = {
        (row["document_id"], row["field_name"]): row for row in _rows(INPUT)
    }
    decisions = {}
    for source in SOURCE_IDS:
        for row in _rows(ROOT / f"evaluation_results/phase8_11/candidate/{source.lower()}/field_decisions.jsonl"):
            decisions[(row["document_id"], row["field_name"])] = row["field_decision"]["disposition"]
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in candidates:
        grouped.setdefault((row["document_id"], row["field_name"]), []).append(row)
    evaluated = []
    for key, options in grouped.items():
        base = extraction[key]
        datatype = options[0]["datatype"]
        selected = _canonical(datatype, base.get("final"))
        expected = _canonical(datatype, base.get("expected"))
        agreeing = [row for row in options if row["normalized_value"] == selected and row["confidence"] >= minimum_confidence]
        reviewed = decisions.get(key) in REVIEW_DISPOSITIONS
        agreeing_profiles = {row["profile"] for row in agreeing}
        eligible = bool(
            selected
            and len(agreeing_profiles) >= minimum_profile_agreement
            and reviewed
            and base["field_name"] != "hcpcs_rate_hipps_code"
        )
        alternative_groups: dict[str, set[str]] = {}
        for option in options:
            if option["normalized_value"] and option["confidence"] >= minimum_confidence:
                alternative_groups.setdefault(option["normalized_value"], set()).add(option["profile"])
        alternatives = [
            value for value, profiles in alternative_groups.items()
            if len(profiles) >= minimum_profile_agreement and value != selected
        ]
        baseline_valid = decide_local_candidate(str(base.get("final") or ""), datatype).accepted
        recovery_value = alternatives[0] if not baseline_valid and len(alternatives) == 1 else None
        evaluated.append({
            "document_id": key[0], "field_name": key[1], "source": base["source"],
            "critical": base["critical"], "reviewed": reviewed, "eligible": eligible,
            "correct": bool(base["exact"]), "tesseract_confidence": max((r["confidence"] for r in agreeing), default=0),
            "recovery_value": recovery_value,
            "recovery_correct": recovery_value == expected if recovery_value else None,
            "baseline_normalized_correct": selected == expected,
        })
    accepted = [row for row in evaluated if row["eligible"]]
    reviewed = [row for row in evaluated if row["reviewed"]]
    false = [row for row in accepted if not row["correct"]]
    recoveries = [row for row in evaluated if row["recovery_value"]]
    before_correct = sum(row["baseline_normalized_correct"] for row in evaluated)
    after_correct = before_correct + sum(
        int(row["recovery_correct"]) - int(row["baseline_normalized_correct"])
        for row in recoveries
    )
    report = {
        "minimum_confidence": minimum_confidence,
        "minimum_profile_agreement": minimum_profile_agreement,
        "validation_fields": len(evaluated),
        "reviewed_fields": len(reviewed), "projected_promotions": len(accepted),
        "projected_field_hitl_before": len(reviewed) / len(evaluated),
        "projected_field_hitl_after": (len(reviewed) - len(accepted)) / len(evaluated),
        "accepted_precision": sum(row["correct"] for row in accepted) / len(accepted) if accepted else None,
        "false_accepts": len(false),
        "critical_false_accepts": sum(row["critical"] for row in false),
        "promotions_by_field": dict(sorted(Counter(row["field_name"] for row in accepted).items())),
        "promotions_by_source": dict(sorted(Counter(row["source"] for row in accepted).items())),
        "normalized_accuracy_before": before_correct / len(evaluated),
        "normalized_accuracy_after_review_suggestion": after_correct / len(evaluated),
        "review_suggestion_recoveries": len(recoveries),
        "review_suggestion_correct": sum(bool(row["recovery_correct"]) for row in recoveries),
        "review_suggestion_regressions": sum(
            bool(row["baseline_normalized_correct"] and not row["recovery_correct"])
            for row in recoveries
        ),
        "production_accuracy_changed": False, "locked_holdout_accessed": False,
        "false_accept_records": false,
    }
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def _eligible_confirmations(
    output: Path, minimum_confidence: float, minimum_profile_agreement: int,
    extraction_input: Path = INPUT,
) -> dict[tuple[str, str], dict]:
    if not (output / "candidates.jsonl").is_file():
        return {}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in _rows(output / "candidates.jsonl"):
        grouped.setdefault((row["document_id"], row["field_name"]), []).append(row)
    extraction = {
        (row["document_id"], row["field_name"]): row for row in _rows(extraction_input)
    }
    eligible = {}
    for key, options in grouped.items():
        base = extraction[key]
        selected = _canonical(options[0]["datatype"], base.get("final"))
        agreeing = [
            row for row in options
            if row["normalized_value"] == selected and row["confidence"] >= minimum_confidence
        ]
        if (
            selected
            and len({row["profile"] for row in agreeing}) >= minimum_profile_agreement
            and base["field_name"] != "hcpcs_rate_hipps_code"
        ):
            eligible[key] = max(agreeing, key=lambda row: row["confidence"])
    return eligible


def canonical_replay(
    output: Path = OUTPUT,
    minimum_confidence: float = 0.95,
    minimum_profile_agreement: int = 2,
    candidate_policy: bool = False,
    replay_root: Path | None = None,
    candidate_policy_path: Path | None = None,
    as_of_date: date | None = None,
    extraction_input: Path = INPUT,
    validation_ids_path: Path | None = None,
) -> dict:
    """Replay frozen confirmations through the canonical runtime decision services."""
    output.mkdir(parents=True, exist_ok=True)
    confirmations = _eligible_confirmations(
        output, minimum_confidence, minimum_profile_agreement, extraction_input
    )
    if validation_ids_path:
        validation_document_ids = set(json.loads(validation_ids_path.read_text("utf-8")))
    else:
        validation_document_ids = {
            item["document_id"]
            for source in SOURCE_IDS
            for item in json.loads(
                (ROOT / f"evaluation_data/phase8_8_generalization/{source}/manifest.json")
                .read_text("utf-8")
            )["documents"]
            if item["dataset_role"] == "VALIDATION"
        }
    bundle = DecisionServiceFactory.from_profile()
    registries = _registries()
    evidence_service = bundle.evidence_decision
    if candidate_policy:
        policy = EvidencePolicy.load(
            candidate_policy_path
            or ROOT / "config/evaluation/evidence_policies_phase8_12_candidate.yaml"
        )
        identity = dict(bundle.evidence_decision.configuration_identity)
        identity["evidence_policy_version"] = policy.version
        identity["runtime_profile_id"] = "phase8.12-validation-candidate"
        evidence_service = EvidenceDecisionService(
            evidence_policy=policy,
            field_policy=bundle.field_policy,
            route_mode=bundle.profile.route_mode,
            route_registry=bundle.route_registry,
            configuration_identity=identity,
        )
    decision_rows = []
    deterministic_service = DeterministicEvidenceService(as_of_date=as_of_date)
    by_claim = {}
    family_by_claim = {}
    for source in SOURCE_IDS:
        base = replay_root or ROOT / "evaluation_results/phase8_11/candidate"
        path = base / source.lower() / "policy_replay_input.jsonl"
        for row in _rows(path):
            key = (row["document_id"], row["field_name"])
            if row["document_id"] not in validation_document_ids:
                continue
            policy = bundle.field_policy.for_field(row["family"], row["field_name"])
            candidates = deepcopy(row["candidates"])
            # Mirror ocr_candidates_from_field: the winning candidate carries
            # the extraction layer's validated normalized/span-selected value,
            # while raw_value remains unchanged for audit.
            if candidates and row.get("final_value") is not None:
                selected_confidence = row.get("selected_confidence")
                winner = (
                    min(
                        candidates,
                        key=lambda item: abs(
                            float(item.get("raw_confidence") or 0)
                            - float(selected_confidence)
                        ),
                    )
                    if selected_confidence is not None
                    else max(
                        candidates,
                        key=lambda item: float(item.get("raw_confidence") or 0),
                    )
                )
                winner["value"] = row["final_value"]
            confirmation = confirmations.get(key)
            if confirmation and candidates:
                tesseract = deepcopy(candidates[0])
                tesseract.update({
                    "value": confirmation["raw_value"],
                    "raw_value": confirmation["raw_value"],
                    "engine": "tesseract_psm_7",
                    "model_name": "tesseract-eng",
                    "model_version": "5.x",
                    "preprocessing_variant": confirmation["profile"],
                    "raw_confidence": confirmation["confidence"],
                    "calibrated_confidence": None,
                    "evidence_reference": f"phase8.12:{confirmation['crop_sha256']}",
                })
                provenance = deepcopy(tesseract.get("provenance") or {})
                provenance.update({
                    "engine_family": "TESSERACT_FAMILY",
                    "engine_name": "tesseract_psm_7",
                    "engine_version": "5.x",
                    "model_family": "TESSERACT",
                    "model_name": "tesseract-eng",
                    "model_version": "5.x",
                    "preprocessing_profile": confirmation["profile"],
                    "preprocessing_sha256": confirmation["crop_sha256"],
                    "source_candidate_id": f"phase8.12:{key[0]}:{key[1]}",
                    "invocation_id": f"phase8.12:{key[0]}:{key[1]}:{confirmation['profile']}",
                })
                tesseract["provenance"] = provenance
                candidates.append(tesseract)
            deterministic = deterministic_service.evaluate(
                row["field_name"], row.get("final_value")
            )
            decision = evidence_service.decide(DecisionContext(
                field_id=f"{row['document_id']}:{row['field_name']}",
                field_name=row["field_name"], document_family=row["family"],
                criticality=policy.criticality, required=policy.required,
                blocks_stp=policy.blocks_stp,
                requires_review_when_unresolved=policy.requires_review_when_unresolved,
                candidates=candidates,
                deterministic_evidence=set(deterministic.evidence),
                deterministic_evidence_version=deterministic_service.policy_version,
                hard_validation_passed=deterministic.passed,
                structural_localization=StructuralLocalizationEvidence.model_validate(row["localization_evidence"]),
                wrong_crop_suspected=row["wrong_crop_suspected"],
                cross_field_evidence=(set(row["cross_field_evidence"]) if deterministic.passed else set()),
            ))
            correct = _decision_correct(registries, row, decision.selected_value)
            decision_rows.append({
                "document_id": row["document_id"], "source": source,
                "family": row["family"], "field_name": row["field_name"],
                "truth": row["truth"], "confirmation_attached": confirmation is not None,
                "correct": correct, "field_decision": decision.model_dump(mode="json"),
            })
            by_claim.setdefault(row["document_id"], []).append(decision)
            family_by_claim[row["document_id"]] = row["family"]
    claims = [
        bundle.claim_decision.decide(ClaimDecisionContext(
            claim_id=claim_id, document_family=family_by_claim[claim_id],
            field_decisions=field_decisions,
            policy_id=bundle.claim_decision.policy_id,
            policy_version=bundle.claim_decision.policy_version,
        ))
        for claim_id, field_decisions in sorted(by_claim.items())
    ]
    accepted = [row for row in decision_rows if FieldDisposition(row["field_decision"]["disposition"]) in ACCEPTED_DISPOSITIONS]
    false = [row for row in accepted if not row["correct"]]
    metrics = {
        "runtime_profile_id": bundle.profile.decision_identity()["runtime_profile_id"],
        "candidate_policy": candidate_policy,
        "evidence_policy_version": evidence_service.policy_version,
        "validation_fields": len(decision_rows), "claims": len(claims),
        "confirmations_attached": sum(row["confirmation_attached"] for row in decision_rows),
        "accepted_fields": len(accepted),
        "field_hitl": 1 - len(accepted) / len(decision_rows),
        "claim_stp": sum(claim.stp_eligible for claim in claims) / len(claims),
        "claim_hitl": sum(not claim.stp_eligible for claim in claims) / len(claims),
        "accepted_precision": sum(row["correct"] for row in accepted) / len(accepted) if accepted else None,
        "false_accepts": len(false),
        "critical_false_accepts": sum(
            row["field_decision"]["criticality"] in {"C2", "C3"} for row in false
        ),
        "locked_holdout_accessed": False,
        "evaluation_as_of_date": as_of_date.isoformat() if as_of_date else None,
    }
    (output / "canonical_field_decisions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in decision_rows), "utf-8"
    )
    (output / "canonical_claim_decisions.jsonl").write_text(
        "".join(claim.model_dump_json() + "\n" for claim in claims), "utf-8"
    )
    (output / "canonical_replay.json").write_text(json.dumps(metrics, indent=2) + "\n", "utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("generate", "evaluate", "replay"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--minimum-confidence", type=float, default=0.85)
    parser.add_argument("--minimum-profile-agreement", type=int, default=2)
    parser.add_argument("--candidate-policy", action="store_true")
    parser.add_argument("--replay-root", type=Path)
    parser.add_argument("--candidate-policy-path", type=Path)
    parser.add_argument("--as-of-date", type=date.fromisoformat)
    parser.add_argument("--extraction-input", type=Path, default=INPUT)
    parser.add_argument("--validation-ids", type=Path)
    args = parser.parse_args()
    if args.action == "generate":
        result = generate(args.output)
    elif args.action == "evaluate":
        result = evaluate(args.output, args.minimum_confidence, args.minimum_profile_agreement)
    else:
        result = canonical_replay(output=args.output, minimum_confidence=args.minimum_confidence,
                                  minimum_profile_agreement=args.minimum_profile_agreement,
                                  candidate_policy=args.candidate_policy,
                                  replay_root=args.replay_root,
                                  candidate_policy_path=args.candidate_policy_path,
                                  as_of_date=args.as_of_date,
                                  extraction_input=args.extraction_input,
                                  validation_ids_path=args.validation_ids)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
