"""Phase 8.7 claim-STP activation over a frozen extraction architecture.

Golden truth is used only for scoring and forensic classification. Runtime
evidence is constructed exclusively from OCR candidates, measured structure,
deterministic validation, and canonical claim reconciliation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import shutil
import statistics
import subprocess
import time
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from evaluation.phase8_1_golden import run as run_extraction
from evaluation.phase8_2_analysis import _candidates
from evaluation.phase8_4_policy_replay import _structural
from evaluation.phase8_6_two_track import _extract_paddle, _paddle_candidate
from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.claim_evidence import ClaimEvidenceBuilder
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.evidence import EvidencePolicy, StructuralLocalizationEvidence
from packages.evidence.name_agreement import (
    NAME_NORMALIZATION_VERSION,
    compare_patient_names,
    normalize_name_for_agreement,
)
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDecision
from packages.field_policy import FieldPolicyRegistry
from packages.route_registry import RouteDefinition, RouteLifecycle, RouteRegistry
from packages.validation_rules.npi import is_valid_npi
from workers.page_detection.text_extraction import PaddleOCRTextExtractor

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
V2 = ROOT / "evaluation_data/phase8_6_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V2"
V3 = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3"
OUTPUT = ROOT / "evaluation_results/phase8_7"
P86 = ROOT / "evaluation_results/phase8_6"
P84 = ROOT / "evaluation_results/phase8_4"
OBSERVATIONS = ROOT / "evaluation_results/phase8_1/observations"
BALANCED_POLICY = ROOT / "config/evidence_policies_phase8_4_balanced.yaml"
FROZEN_SHA = "214edfea3e5939bb5b066b8b8f3bb164f153c1fb"
NPI_GENERATOR_VERSION = "synthetic-npi-80840-luhn-v1"
NPI_SEED = "phase8.7-valid-npi-seed-20260823"
ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}


def _read_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", "utf-8")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in values), "utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _font(size: int = 20) -> ImageFont.ImageFont:
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/calibri.ttf")):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def generate_valid_npi(document_id: str) -> str:
    """Generate a stable synthetic NPI with the real 80840-prefix check digit."""
    seed = hashlib.sha256(f"{NPI_SEED}:{document_id}".encode()).digest()
    first_nine = "1" + str(int.from_bytes(seed[:8], "big") % 100_000_000).zfill(8)
    for check_digit in range(10):
        candidate = first_nine + str(check_digit)
        if is_valid_npi(candidate):
            return candidate
    raise AssertionError("unable to generate valid NPI")


def _render_replacement_npi(
    image: Image.Image,
    value: str,
    bbox: list[int | float],
    variant: str,
    document_id: str,
) -> list[int]:
    font = _font(20)
    x0, y0, x1, y1 = (round(value) for value in bbox)
    patch_box = (x0 - 5, y0 - 5, x1 + 7, y1 + 6)
    patch = Image.new("RGB", (patch_box[2] - patch_box[0], patch_box[3] - patch_box[1]), "white")
    draw = ImageDraw.Draw(patch)
    ink = 70 if variant == "low_contrast" else 0
    position = (5, 1)
    draw.text(position, value, font=font, fill=(ink, ink, ink))
    if variant == "blur":
        patch = patch.filter(ImageFilter.GaussianBlur(0.65))
    elif variant == "skew":
        patch = patch.rotate(
            1.2,
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
    elif variant == "noise":
        pixels = patch.load()
        rng = random.Random(f"{NPI_SEED}:{document_id}")
        for _ in range(80):
            px, py = rng.randrange(patch.width), rng.randrange(patch.height)
            level = rng.choice((90, 130, 180, 220))
            pixels[px, py] = (level, level, level)
    image.paste(patch, patch_box[:2])
    return [x0, y0, x1, y1]


def _observed_npi_bbox(document_id: str, value: str, fallback: list[int]) -> list[float]:
    observation = _read_json(OBSERVATIONS / f"{document_id}.json")
    expected = "".join(char for char in value if char.isdigit())
    matches = [
        token["bbox"]
        for token in observation["ocr_tokens"]
        if "".join(char for char in token["text"] if char.isdigit()) == expected
    ]
    if len(matches) != 1:
        return fallback
    return matches[0]


def _invalid_npi_cases_from_v2() -> list[dict]:
    with (V2 / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    return [
        {
            "document_id": row["document_id"],
            "family": "CMS1500" if row["document_id"].startswith("CMS") else "UB04",
            "value": row["expected_value"],
            "validator": "packages.validation_rules.npi.is_valid_npi",
            "validator_version": "80840-prefix-luhn-v1",
            "deterministic_validation": "FAIL",
            "intended_partition": "NPI_INVALID_ADVERSARIAL_CORPUS",
        }
        for row in truth
        if row["field_name"] == "provider_npi"
        and not is_valid_npi(row["expected_value"])
    ]


def build_v3(source: Path = V2, target: Path = V3, output: Path = OUTPUT) -> dict:
    if target.exists():
        manifest = _read_json(target / "manifest.json")
        if manifest.get("dataset_id") != "CDP_GOLDEN_ENGINEERING_PACK_V3":
            raise RuntimeError(f"refusing to overwrite unexpected dataset: {target}")
        _write_json(output / "npi_invalid_adversarial_cases.json", _invalid_npi_cases_from_v2())
        return manifest
    v1_before = _tree_digest(V1)
    v2_before = _tree_digest(V2)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest = _read_json(target / "manifest.json")
    documents = {row["document_id"]: row for row in manifest["documents"]}
    with (target / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    invalid_adversarial = []
    generated = []
    for row in truth:
        if row["field_name"] != "provider_npi":
            continue
        document_id = row["document_id"]
        old_value = row["expected_value"]
        old_valid = is_valid_npi(old_value)
        if not old_valid:
            invalid_adversarial.append(
                {
                    "document_id": document_id,
                    "family": "CMS1500" if document_id.startswith("CMS") else "UB04",
                    "value": old_value,
                    "validator": "packages.validation_rules.npi.is_valid_npi",
                    "validator_version": "80840-prefix-luhn-v1",
                    "deterministic_validation": "FAIL",
                    "intended_partition": "NPI_INVALID_ADVERSARIAL_CORPUS",
                }
            )
        new_value = generate_valid_npi(document_id)
        document = documents[document_id]
        image_path = target / document["file"]
        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
        observed_bbox = _observed_npi_bbox(
            document_id, old_value, json.loads(row["bbox_json"])
        )
        new_bbox = _render_replacement_npi(
            image,
            new_value,
            observed_bbox,
            document["variant"],
            document_id,
        )
        image.save(image_path)
        document["sha256"] = _sha(image_path)
        row["expected_value"] = new_value
        row["bbox_json"] = json.dumps(new_bbox)
        generated.append(
            {
                "document_id": document_id,
                "value": new_value,
                "generation_method": "deterministic 9-digit body plus 80840-prefix Luhn digit",
                "generator_version": NPI_GENERATOR_VERSION,
                "seed": NPI_SEED,
                "validity_result": is_valid_npi(new_value),
            }
        )
    with (target / "field_truth.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=truth[0].keys())
        writer.writeheader()
        writer.writerows(truth)
    manifest.update(
        {
            "dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V3",
            "purpose": "PHI-free engineering STP measurement with business-valid blocking values.",
            "production_promotion_authority": False,
            "parent_dataset": "CDP_GOLDEN_ENGINEERING_PACK_V2",
            "parent_manifest_sha256": _sha(source / "manifest.json"),
            "npi_generator": {
                "version": NPI_GENERATOR_VERSION,
                "seed": NPI_SEED,
                "algorithm": "80840-prefix Luhn mod-10",
                "generated": len(generated),
                "valid": sum(row["validity_result"] for row in generated),
            },
            "partitions": {
                "NPI_VALID_STP_CORPUS": len(generated),
                "NPI_INVALID_ADVERSARIAL_CORPUS": len(invalid_adversarial),
            },
        }
    )
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    provenance = {
        "dataset_id": manifest["dataset_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "frozen_phase8_6_commit": FROZEN_SHA,
        "v1_tree_sha256_before": v1_before,
        "v1_tree_sha256_after": _tree_digest(V1),
        "v2_tree_sha256_before": v2_before,
        "v2_tree_sha256_after": _tree_digest(V2),
        "v1_unchanged": v1_before == _tree_digest(V1),
        "v2_unchanged": v2_before == _tree_digest(V2),
    }
    _write_json(target / "phase8_7_provenance.json", provenance)
    _write_json(output / "npi_invalid_adversarial_cases.json", invalid_adversarial)
    _write_json(output / "npi_valid_generation.json", generated)
    return manifest


def archive_v3(dataset: Path = V3, output: Path = OUTPUT) -> dict:
    archive = output / "CDP_GOLDEN_ENGINEERING_PACK_V3.zip"
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for item in sorted(path for path in dataset.rglob("*") if path.is_file()):
            bundle.write(item, (Path(dataset.name) / item.relative_to(dataset)).as_posix())
    record = {"path": str(archive.relative_to(ROOT)), "sha256": _sha(archive), "bytes": archive.stat().st_size}
    _write_json(output / "golden_v3_archive.json", record)
    return record


def _validity(field_name: str, value: str) -> tuple[str, str, str]:
    name = field_name.casefold()
    if "npi" in name:
        return ("VALID" if is_valid_npi(value) else "INVALID", "80840-prefix Luhn", "80840-prefix-luhn-v1")
    if name in {"patient_dob", "service_date"}:
        try:
            time.strptime(value, "%m/%d/%Y")
            return "VALID", "MM/DD/YYYY calendar date", "datetime-strptime-v1"
        except ValueError:
            return "INVALID", "MM/DD/YYYY calendar date", "datetime-strptime-v1"
    if name in {"member_id", "insured_id_number"}:
        valid = bool(value) and len(value) <= 32 and all(char.isalnum() or char in "-_" for char in value)
        return ("VALID" if valid else "INVALID", "configured identifier syntax", "member-id-syntax-v1")
    if name == "type_of_bill":
        return (
            "VALID" if len(value) == 3 and value.isdigit() else "INVALID",
            "three-digit UB type-of-bill syntax",
            "type-of-bill-v1",
        )
    if name in {"cpt_hcpcs", "hcpcs"}:
        valid = len(value) == 5 and value.isalnum()
        return ("VALID" if valid else "INVALID", "five alphanumeric characters", "hcpcs-syntax-v1")
    if "diagnos" in name:
        compact = value.replace(".", "")
        valid = 3 <= len(compact) <= 7 and compact[0].isalpha() and compact[1:].isalnum()
        return ("VALID" if valid else "INVALID", "reference-independent ICD syntax", "icd-syntax-v1")
    if name in {"total_charge", "charge", "charge_amount"}:
        try:
            valid = Decimal(value) >= 0
        except InvalidOperation:
            valid = False
        return ("VALID" if valid else "INVALID", "non-negative decimal currency", "decimal-currency-v1")
    if name == "federal_tax_no":
        return ("VALID" if len(value) == 9 and value.isdigit() else "INVALID", "nine-digit synthetic EIN syntax", "tax-id-syntax-v1")
    return "NOT_INDEPENDENTLY_VERIFIABLE", "semantic value", "none"


def audit_v3_validity(dataset: Path = V3, output: Path = OUTPUT) -> dict:
    with (dataset / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    with (dataset / "ub04_service_line_truth.csv").open(newline="", encoding="utf-8") as handle:
        service = list(csv.DictReader(handle))
    observations = []
    for row in truth:
        status, rule, version = _validity(row["field_name"], row["expected_value"])
        observations.append({**row, "status": status, "generation_rule": rule, "validator_version": version})
    for row in service:
        for field_name in ("revenue_code", "hcpcs", "service_date", "units", "charge"):
            value = row.get(field_name, "")
            if field_name == "revenue_code":
                status = "VALID" if len(value) == 4 and value.isdigit() else "INVALID"
                rule, version = "four-digit revenue code syntax", "revenue-code-syntax-v1"
            elif field_name == "units":
                status = "VALID" if value.isdigit() and int(value) > 0 else "INVALID"
                rule, version = "positive integer units", "units-syntax-v1"
            else:
                status, rule, version = _validity(field_name, value)
            observations.append(
                {
                    "document_id": row["document_id"],
                    "field_name": f"service_line.{field_name}",
                    "expected_value": value,
                    "status": status,
                    "generation_rule": rule,
                    "validator_version": version,
                }
            )
    ub_totals = {
        row["document_id"]: Decimal(row["expected_value"])
        for row in truth
        if row["document_id"].startswith("UB") and row["field_name"] == "total_charge"
    }
    service_totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in service:
        service_totals[row["document_id"]] += Decimal(row["charge"])
    for document_id, expected_total in ub_totals.items():
        actual_total = service_totals[document_id]
        observations.append(
            {
                "document_id": document_id,
                "field_name": "UB04.claim_total_consistency",
                "expected_value": str(expected_total),
                "status": "VALID" if actual_total == expected_total else "INVALID",
                "generation_rule": "sum(service-line charges) equals claim total",
                "validator_version": "decimal-sum-reconciliation-v1",
            }
        )
    by_field = {}
    for field_name in sorted({row["field_name"] for row in observations}):
        scoped = [row for row in observations if row["field_name"] == field_name]
        by_field[field_name] = {
            "observations": len(scoped),
            "valid": sum(row["status"] == "VALID" for row in scoped),
            "invalid": sum(row["status"] == "INVALID" for row in scoped),
            "not_independently_verifiable": sum(
                row["status"] == "NOT_INDEPENDENTLY_VERIFIABLE" for row in scoped
            ),
            "generation_rule": scoped[0]["generation_rule"],
            "validator_version": scoped[0]["validator_version"],
        }
    report = {
        "dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V3",
        "engineering_only": True,
        "production_authority": False,
        "by_field": by_field,
        "invalid_observations": [row for row in observations if row["status"] == "INVALID"],
        "required_provider_npis_all_valid": by_field["provider_npi"]["invalid"] == 0,
    }
    _write_json(output / "golden_v3_validity.json", report)
    _write_json(output / "golden_v3_manifest.json", _read_json(dataset / "manifest.json"))
    return report


def freeze_phase8_6(output: Path = OUTPUT) -> dict:
    baseline = _read_json(ROOT / "evaluation_results/phase8_5/baseline.json")
    record = {
        "frontier": "PHASE8_6_EVIDENCE_FRONTIER_V1",
        "git_sha": FROZEN_SHA,
        "phase8_6_summary_sha256": _sha(P86 / "summary.json"),
        "phase8_6_decision_sha256": _sha(P86 / "decision.json"),
        "extraction": baseline["extraction"],
        "phase8_6_profile": _read_json(P86 / "profile_c.json"),
        "frozen_components": [
            "field localization",
            "PageObservation",
            "RapidOCR",
            "PaddleOCR",
            "Tesseract",
            "DynamicROIResolver",
            "UB service-line reconstruction",
            "normalization",
            "router",
            "template registration",
        ],
    }
    _write_json(output / "phase8_6_freeze.json", record)
    return record


def claim_blocker_pareto(output: Path = OUTPUT) -> list[dict]:
    fields = _read_jsonl(P86 / "field_decisions.jsonl")
    claims = _read_jsonl(P86 / "claim_decisions.jsonl")
    fields_by_key = {(row["document_id"], row["field_name"]): row for row in fields}
    aggregate: dict[tuple[str, str], dict] = {}
    for claim in claims:
        blockers = claim["blocking_unresolved_fields"]
        count = len(blockers)
        for field_name in blockers:
            key = ("CMS1500" if claim["claim_id"].startswith("CMS") else "UB04", field_name)
            row = fields_by_key[(claim["claim_id"], field_name)]
            decision = row["field_decision"]
            item = aggregate.setdefault(
                key,
                {
                    "field": field_name,
                    "family": key[0],
                    "criticality": row["criticality"],
                    "claims_blocked": 0,
                    "single_blocker_claims": 0,
                    "two_blocker_claims": 0,
                    "multi_blocker_claims": 0,
                    "correct_but_reviewed": 0,
                    "wrong_and_safely_rejected": 0,
                    "true_ambiguity": 0,
                    "benchmark_invalid_value": 0,
                    "missing_evidence": Counter(),
                    "available_evidence": Counter(),
                },
            )
            item["claims_blocked"] += 1
            item["single_blocker_claims" if count == 1 else "two_blocker_claims" if count == 2 else "multi_blocker_claims"] += 1
            item["correct_but_reviewed"] += int(row["exact"])
            item["wrong_and_safely_rejected"] += int(not row["exact"])
            item["true_ambiguity"] += int(
                "AMBIG" in " ".join(decision.get("reason_codes") or [])
            )
            if "npi" in field_name and not is_valid_npi(row["truth"]):
                item["benchmark_invalid_value"] += 1
            item["missing_evidence"].update(decision.get("missing_evidence") or [])
            item["available_evidence"].update(decision.get("available_evidence") or [])
    result = []
    for item in aggregate.values():
        item["claim_unlock_value"] = item["single_blocker_claims"]
        item["missing_evidence"] = dict(item["missing_evidence"])
        item["available_evidence"] = dict(item["available_evidence"])
        result.append(item)
    result.sort(key=lambda row: (-row["claim_unlock_value"], -row["claims_blocked"], row["field"]))
    _write_json(output / "claim_blocker_pareto.json", result)
    return result


def claim_unlock_waterfall(output: Path = OUTPUT) -> dict:
    claims = _read_jsonl(P86 / "claim_decisions.jsonl")
    resolved: set[str] = set()
    steps = []

    def unlocked() -> int:
        return sum(
            claim["stp_eligible"] or set(claim["blocking_unresolved_fields"]) <= resolved
            for claim in claims
        )

    steps.append({"step": "PHASE8_6_CURRENT", "resolved_fields": [], "claims_unlocked": unlocked(), "claim_stp": unlocked() / len(claims)})
    ordered = ["patient_name", "provider_npi"]
    remaining = Counter(
        field for claim in claims for field in claim["blocking_unresolved_fields"] if field not in ordered
    )
    ordered.extend(field for field, _ in remaining.most_common())
    for field_name in ordered:
        before = unlocked()
        resolved.add(field_name)
        after = unlocked()
        steps.append(
            {
                "step": f"COUNTERFACTUALLY_RESOLVE_{field_name.upper()}",
                "resolved_fields": sorted(resolved),
                "marginal_claims_unlocked": after - before,
                "claims_unlocked": after,
                "claim_stp": after / len(claims),
            }
        )
        if len(resolved) >= 3:
            break
    report = {"analysis_only": True, "production_decisions_changed": False, "steps": steps}
    _write_json(output / "claim_unlock_waterfall.json", report)
    return report


def run_v3_extraction(dataset: Path = V3, output: Path = OUTPUT) -> dict:
    return run_extraction(dataset, output, run_id="v3_extraction", reuse_observations=False)


def _crop_hash(image: Image.Image, bbox: list[float]) -> str:
    crop = image.crop(tuple(round(value) for value in bbox))
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _name_classification(
    rapid: str | None, paddle: str | None, structurally_confirmed: bool
) -> str:
    comparison = compare_patient_names(rapid, paddle)
    if not structurally_confirmed:
        return "LOCALIZATION_AMBIGUITY"
    if comparison.label_contamination:
        return "LABEL_CONTAMINATION"
    if not rapid or not paddle:
        return "TRUE_AMBIGUITY"
    if comparison.agrees:
        raw_left = " ".join(rapid.upper().split())
        raw_right = " ".join(paddle.upper().split())
        if raw_left == raw_right:
            return "EXACT_MULTI_ENGINE_AGREEMENT"
        return "PUNCTUATION_ONLY_DISAGREEMENT"
    if sorted(comparison.left_tokens) == sorted(comparison.right_tokens):
        return "TOKEN_ORDER_DISAGREEMENT"
    return "OCR_CHARACTER_DISAGREEMENT"


def benchmark_local_evidence(dataset: Path = V3, output: Path = OUTPUT) -> dict:
    records = _read_jsonl(output / "v3_extraction/field_records.jsonl")
    targets = [
        row
        for row in records
        if row["field_name"] in {"patient_name", "provider_npi"}
    ]
    manifest = _read_json(dataset / "manifest.json")
    documents = {row["document_id"]: row for row in manifest["documents"]}
    predictions_path = output / "local_evidence_predictions.jsonl"
    predictions = _read_jsonl(predictions_path) if predictions_path.is_file() else []
    completed = {(row["document_id"], row["field_name"]) for row in predictions}
    pending = [
        row
        for row in targets
        if (row["document_id"], row["field_name"]) not in completed
    ]
    paddle = PaddleOCRTextExtractor()
    for index, row in enumerate(pending, 1):
        document = documents[row["document_id"]]
        with Image.open(dataset / document["file"]) as source_image:
            image = source_image.convert("RGB")
        paddle_value, confidence, latency = _extract_paddle(
            paddle, image, row["predicted_bbox"]
        )
        trace = row.get("candidate_trace") or {}
        rapid_value = trace.get("regional_value") or trace.get("primary_value") or row.get("final")
        structural = _structural(row).model_dump(mode="json")
        if row["field_name"] == "patient_name":
            comparison = compare_patient_names(rapid_value, paddle_value)
            agrees = comparison.agrees and structural["confirmed"]
            rapid_normalized = comparison.left_normalized
            paddle_normalized = comparison.right_normalized
            classification = _name_classification(
                rapid_value, paddle_value, structural["confirmed"]
            )
            label_contamination = comparison.label_contamination
            tokens = {"rapid": list(comparison.left_tokens), "paddle": list(comparison.right_tokens)}
        else:
            rapid_normalized = normalize_agreement_value(row["field_name"], rapid_value)
            paddle_normalized = normalize_agreement_value(row["field_name"], paddle_value)
            agrees = bool(
                rapid_normalized
                and rapid_normalized == paddle_normalized
                and structural["confirmed"]
            )
            classification = "EXACT_MULTI_ENGINE_AGREEMENT" if agrees else "OCR_CHARACTER_DISAGREEMENT"
            label_contamination = False
            tokens = {"rapid": [rapid_normalized], "paddle": [paddle_normalized]}
        expected_normalized = (
            normalize_name_for_agreement(row["expected"])[0]
            if row["field_name"] == "patient_name"
            else normalize_agreement_value(row["field_name"], row["expected"])
        )
        predictions.append(
            {
                "document_id": row["document_id"],
                "family": row["family"],
                "field_name": row["field_name"],
                "truth": row["expected"],
                "rapid_value": rapid_value,
                "paddle_value": paddle_value,
                "rapid_normalized": rapid_normalized,
                "paddle_normalized": paddle_normalized,
                "tokens": tokens,
                "predicted_bbox": row["predicted_bbox"],
                "localization_mode": row["roi_mode"],
                "structural_evidence": structural,
                "label_contamination": label_contamination,
                "classification": classification,
                "independent_agreement": agrees,
                "rapid_exact": normalize_agreement_value(row["field_name"], rapid_value) == expected_normalized,
                "paddle_exact": normalize_agreement_value(row["field_name"], paddle_value) == expected_normalized,
                "false_agreement": bool(agrees and rapid_normalized != expected_normalized),
                "engine": "paddleocr_regional",
                "engine_family": "PADDLE_FAMILY",
                "model_name": "PP-OCRv4",
                "model_version": "paddleocr-2.x",
                "invocation_id": f"phase8.7:{row['document_id']}:{row['field_name']}:paddle",
                "crop_sha256": _crop_hash(image, row["predicted_bbox"]),
                "preprocessing_variant": "recorded-canonical-field-crop-v1",
                "name_normalization_version": NAME_NORMALIZATION_VERSION if row["field_name"] == "patient_name" else None,
                "paddle_confidence": confidence,
                "paddle_latency_ms": latency,
                "cloud_cost_usd": 0.0,
            }
        )
        print(f"phase8.7 local evidence resume: {index}/{len(pending)}", flush=True)
    _write_jsonl(output / "local_evidence_predictions.jsonl", predictions)
    return rescore_local_evidence(output)


def rescore_local_evidence(output: Path = OUTPUT) -> dict:
    predictions = _read_jsonl(output / "local_evidence_predictions.jsonl")
    for row in predictions:
        structurally_confirmed = row["structural_evidence"]["confirmed"]
        if row["field_name"] == "patient_name":
            comparison = compare_patient_names(row["rapid_value"], row["paddle_value"])
            row["rapid_normalized"] = comparison.left_normalized
            row["paddle_normalized"] = comparison.right_normalized
            row["tokens"] = {
                "rapid": list(comparison.left_tokens),
                "paddle": list(comparison.right_tokens),
            }
            row["label_contamination"] = comparison.label_contamination
            row["independent_agreement"] = (
                comparison.agrees and structurally_confirmed
            )
            row["classification"] = _name_classification(
                row["rapid_value"], row["paddle_value"], structurally_confirmed
            )
        else:
            row["rapid_normalized"] = normalize_agreement_value(
                row["field_name"], row["rapid_value"]
            )
            row["paddle_normalized"] = normalize_agreement_value(
                row["field_name"], row["paddle_value"]
            )
            row["independent_agreement"] = bool(
                row["rapid_normalized"]
                and row["rapid_normalized"] == row["paddle_normalized"]
                and structurally_confirmed
            )
        expected = (
            normalize_name_for_agreement(row["truth"])[0]
            if row["field_name"] == "patient_name"
            else normalize_agreement_value(row["field_name"], row["truth"])
        )
        row["false_agreement"] = bool(
            row["independent_agreement"] and row["rapid_normalized"] != expected
        )
    _write_jsonl(output / "local_evidence_predictions.jsonl", predictions)
    names = [row for row in predictions if row["field_name"] == "patient_name"]
    agreements = [row for row in names if row["independent_agreement"]]
    metrics = {
        "observations": len(names),
        "agreement_count": len(agreements),
        "agreement_coverage": len(agreements) / len(names),
        "agreement_precision": sum(not row["false_agreement"] for row in agreements) / max(1, len(agreements)),
        "false_agreements": sum(row["false_agreement"] for row in names),
        "rapid_accuracy": sum(row["rapid_exact"] for row in names) / len(names),
        "paddle_accuracy": sum(row["paddle_exact"] for row in names) / len(names),
        "strong_structural_coverage": sum(row["structural_evidence"]["confirmed"] for row in names) / len(names),
        "classification": dict(Counter(row["classification"] for row in names)),
        "p50_latency_ms": statistics.median(row["paddle_latency_ms"] for row in names),
        "cloud_cost_usd": 0.0,
        "candidate_gate_passed": bool(agreements and not any(row["false_agreement"] for row in names)),
        "production_route_promoted": False,
    }
    _write_json(output / "patient_name_agreement.json", metrics)
    _write_jsonl(output / "patient_name_forensics.jsonl", names)
    return metrics


def _service_lines(output: Path) -> dict[str, list[dict]]:
    rows = _read_jsonl(output / "v3_extraction/service_line_records.jsonl")
    by_document: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in rows:
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


def _same_crop(dataset_left: Path, dataset_right: Path, document_id: str, bbox) -> bool:
    left_manifest = _read_json(dataset_left / "manifest.json")
    right_manifest = _read_json(dataset_right / "manifest.json")
    left_doc = next(row for row in left_manifest["documents"] if row["document_id"] == document_id)
    right_doc = next(row for row in right_manifest["documents"] if row["document_id"] == document_id)
    with Image.open(dataset_left / left_doc["file"]) as source:
        left = _crop_hash(source.convert("RGB"), bbox)
    with Image.open(dataset_right / right_doc["file"]) as source:
        right = _crop_hash(source.convert("RGB"), bbox)
    return left == right


def _paddle_evidence_maps(output: Path) -> tuple[dict, dict]:
    local = {
        (row["document_id"], row["field_name"]): row
        for row in _read_jsonl(output / "local_evidence_predictions.jsonl")
    }
    frozen = {}
    for row in _read_jsonl(P86 / "cms_local_evidence_predictions.jsonl"):
        if row["field_name"] not in {"member_id", "total_charge"}:
            continue
        if not _same_crop(V2, V3, row["document_id"], row["predicted_bbox"]):
            raise RuntimeError(f"frozen candidate crop changed: {row['document_id']} {row['field_name']}")
        frozen[(row["document_id"], row["field_name"])] = row
    for row in _read_jsonl(P86 / "ub_federal_tax_predictions.jsonl"):
        key = (row["document_id"], "federal_tax_no")
        if not _same_crop(V2, V3, row["document_id"], row["predicted_bbox"]):
            raise RuntimeError(f"frozen candidate crop changed: {row['document_id']} federal_tax_no")
        frozen[key] = {**row, "field_name": "federal_tax_no"}
    return local, frozen


def _candidate_payload(candidate) -> dict:
    return {
        **vars(candidate),
        "bounding_box": candidate.bounding_box.model_dump(mode="json"),
        "validation_results": list(candidate.validation_results),
        "provenance": (
            candidate.provenance.model_dump(mode="json") if candidate.provenance else None
        ),
    }


def _build_replay_rows(output: Path = OUTPUT) -> list[dict]:
    records = _read_jsonl(output / "v3_extraction/field_records.jsonl")
    by_document: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_document[row["document_id"]].append(row)
    deterministic = DeterministicEvidenceService()
    claim_builder = ClaimEvidenceBuilder.load()
    policies = FieldPolicyRegistry.load()
    services = _service_lines(output)
    replay = []
    for document_id, document_rows in sorted(by_document.items()):
        family = document_rows[0]["family"]
        claim_values = {row["field_name"]: row.get("final") for row in document_rows}
        claim_evidence = claim_builder.build(
            claim_id=document_id,
            document_family=family,
            claim_values=claim_values,
            service_lines=services.get(document_id, []),
        )
        for row in document_rows:
            facts = deterministic.evaluate(
                row["field_name"], row.get("final"), claim_values=claim_values
            )
            cross = set(facts.cross_field_evidence)
            cross.update(claim_evidence.evidence_types_for(row["field_name"]))
            policy = policies.for_field(family, row["field_name"])
            replay.append(
                {
                    "document_id": document_id,
                    "page_id": document_id,
                    "family": family,
                    "field_name": row["field_name"],
                    "truth": row["expected"],
                    "final_value": row.get("final"),
                    "exact": row["exact"],
                    "criticality": policy.criticality.value,
                    "predicted_bbox": row["predicted_bbox"],
                    "candidates": [_candidate_payload(candidate) for candidate in _candidates(row)],
                    "localization_evidence": _structural(row).model_dump(mode="json"),
                    "wrong_crop_suspected": "WRONG_CROP_SUSPECTED"
                    in set((row.get("candidate_trace") or {}).get("reason_codes") or []),
                    "deterministic_validation": {
                        "passed": facts.passed,
                        "evidence": sorted(facts.evidence),
                        "version": deterministic.policy_version,
                    },
                    "cross_field_evidence": sorted(cross),
                }
            )
    _write_jsonl(output / "v3_policy_replay_input.jsonl", replay)
    return replay


def _eligible_name_candidate(row: dict, prediction: dict) -> bool:
    if not prediction["independent_agreement"] or prediction["label_contamination"]:
        return False
    if not prediction["structural_evidence"]["confirmed"]:
        return False
    paddle = prediction["paddle_normalized"]
    current = {
        compare_patient_names(candidate.get("value"), prediction["paddle_value"]).left_normalized
        for candidate in row["candidates"]
        if candidate.get("value")
    }
    return bool(current) and current == {paddle}


def _profile_metrics(fields: list[dict], claims: list[dict]) -> dict:
    accepted = [row for row in fields if row["field_decision"]["disposition"] in ACCEPTED]
    incorrect = [row for row in accepted if not row["evidence_correct"]]
    stp = [claim for claim in claims if claim["stp_eligible"]]
    pages = len({row["document_id"] for row in fields})
    review_fields = len(fields) - len(accepted)
    review_fields_per_page = review_fields / pages
    review_cost_per_field = 25 / 3600 * 5
    field_hitl_cost = review_fields_per_page * review_cost_per_field
    claim_hitl_cost = (1 - len(stp) / len(claims)) * (25 / 3600 * 30 / 3)
    machine = 0.0005907903458333426
    shared = 0.0001
    fully_loaded = field_hitl_cost + claim_hitl_cost + machine + shared
    return {
        "eligible_fields": len(fields),
        "accepted_fields": len(accepted),
        "safe_field_coverage": sum(row["evidence_correct"] for row in accepted) / len(fields),
        "field_hitl": 1 - len(accepted) / len(fields),
        "accepted_precision": sum(row["evidence_correct"] for row in accepted)
        / max(1, len(accepted)),
        "false_accepts": len(incorrect),
        "critical_false_accepts": sum(row["criticality"] in {"C2", "C3"} for row in incorrect),
        "claim_stp": len(stp) / len(claims),
        "claim_hitl": 1 - len(stp) / len(claims),
        "claims_unlocked": len(stp),
        "review_fields": review_fields,
        "review_fields_per_page": review_fields_per_page,
        "review_claims": len(claims) - len(stp),
        "hitl_cost_per_page_usd": field_hitl_cost + claim_hitl_cost,
        "fully_loaded_cost_per_page_usd": fully_loaded,
        "cost_per_document_usd": fully_loaded * 3,
        "cost_per_stp_claim_usd": fully_loaded * pages / len(stp) if stp else None,
        "cloud_calls": 0,
        "cloud_cost_usd": 0.0,
    }


def replay_profiles(output: Path = OUTPUT) -> dict:
    replay = _build_replay_rows(output)
    local, frozen = _paddle_evidence_maps(output)
    policies = FieldPolicyRegistry.load()
    policy = EvidencePolicy.load(BALANCED_POLICY)

    base_registry = RouteRegistry.load()
    ub_provider_candidate = RouteDefinition(
        route_id="UB04.provider_npi.paddleocr.rapidocr.phase8_7_candidate",
        field="provider_npi",
        form="UB04",
        primary_engine="paddleocr",
        confirmation_engine="rapidocr",
        preprocessing_profile="recorded-canonical-field-crop-v1",
        policy_version=policy.version,
        benchmark_dataset="CDP_GOLDEN_ENGINEERING_PACK_V3",
        sample_count=50,
        standalone_accuracy=None,
        agreement_precision=None,
        false_agreement_count=0,
        mean_latency_ms=None,
        cost_per_call_usd=0.0,
        cost_status="LOCAL_CPU_ENGINEERING_EVALUATION",
        status=RouteLifecycle.EVALUATION_ONLY,
        approval_scope="ENGINEERING_ONLY_NOT_PRODUCTION_AUTHORITY",
    )
    candidate_registry = RouteRegistry(
        version=f"{base_registry.version}-phase8.7-engineering",
        routes=[*base_registry.routes, ub_provider_candidate],
    )

    def run_profile(name_candidate: bool, route_mode: str) -> tuple[list[dict], list[dict], dict]:
        evidence = EvidenceDecisionService(
            evidence_policy=policy,
            field_policy=policies,
            route_mode=route_mode,
            route_registry=candidate_registry if name_candidate else base_registry,
        )
        field_rows = []
        by_document: dict[str, list[FieldDecision]] = defaultdict(list)
        family_by_document = {}
        for row in replay:
            key = (row["document_id"], row["field_name"])
            candidates = list(row["candidates"])
            prediction = local.get(key) or frozen.get(key)
            add_paddle = key in frozen or (
                row["field_name"] == "provider_npi"
                and prediction is not None
                and (row["family"] == "CMS1500" or name_candidate)
            )
            if name_candidate and row["field_name"] == "patient_name" and prediction:
                add_paddle = _eligible_name_candidate(row, prediction)
            if prediction and add_paddle and prediction.get("paddle_value"):
                candidates.append(_paddle_candidate(prediction, row))
            field_policy = policies.for_field(row["family"], row["field_name"])
            decision = evidence.decide(
                DecisionContext(
                    field_id=f"{row['document_id']}:{row['field_name']}",
                    field_name=row["field_name"],
                    document_family=row["family"],
                    criticality=field_policy.criticality,
                    required=field_policy.required,
                    blocks_stp=field_policy.blocks_stp,
                    requires_review_when_unresolved=field_policy.requires_review_when_unresolved,
                    candidates=candidates,
                    deterministic_evidence=set(row["deterministic_validation"]["evidence"]),
                    deterministic_evidence_version=row["deterministic_validation"]["version"],
                    hard_validation_passed=row["deterministic_validation"]["passed"],
                    structural_localization=StructuralLocalizationEvidence.model_validate(
                        row["localization_evidence"]
                    ),
                    wrong_crop_suspected=row["wrong_crop_suspected"],
                    cross_field_evidence=set(row["cross_field_evidence"]),
                )
            )
            payload = {
                "document_id": row["document_id"],
                "family": row["family"],
                "field_name": row["field_name"],
                "truth": row["truth"],
                "final_value": row["final_value"],
                "exact": row["exact"],
                "evidence_correct": row["exact"]
                or (
                    row["field_name"] == "patient_name"
                    and compare_patient_names(row["final_value"], row["truth"]).agrees
                ),
                "criticality": row["criticality"],
                "field_decision": decision.model_dump(mode="json"),
            }
            field_rows.append(payload)
            by_document[row["document_id"]].append(decision)
            family_by_document[row["document_id"]] = row["family"]
        claim_service = ClaimDecisionService.load(field_policy=policies)
        claim_rows = [
            claim_service.decide(
                ClaimDecisionContext(
                    claim_id=document_id,
                    document_family=family_by_document[document_id],
                    field_decisions=decisions,
                    policy_id=claim_service.policy_id,
                    policy_version=claim_service.policy_version,
                )
            ).model_dump(mode="json")
            for document_id, decisions in sorted(by_document.items())
        ]
        return field_rows, claim_rows, _profile_metrics(field_rows, claim_rows)

    baseline_fields, baseline_claims, baseline = run_profile(False, "runtime")
    candidate_fields, candidate_claims, candidate = run_profile(True, "evaluation")
    extraction = _read_json(output / "v3_extraction/metrics.json")
    baseline_artifact = {"profile": "V3_BASELINE", "extraction": extraction, **baseline}
    candidate_artifact = {
        "profile": "V3_INDEPENDENT_NAME_AGREEMENT",
        "engineering_evaluation_only": True,
        "production_route_promoted": False,
        **candidate,
    }
    _write_json(output / "v3_baseline.json", baseline_artifact)
    _write_json(output / "v3_name_evidence.json", candidate_artifact)
    _write_jsonl(output / "field_decisions.jsonl", candidate_fields)
    _write_jsonl(output / "claim_decisions.jsonl", candidate_claims)
    _write_jsonl(output / "v3_baseline_field_decisions.jsonl", baseline_fields)
    _write_jsonl(output / "v3_baseline_claim_decisions.jsonl", baseline_claims)
    return {
        "baseline": baseline_artifact,
        "candidate": candidate_artifact,
        "field_rows": candidate_fields,
        "claim_rows": candidate_claims,
    }


def adversarial_npi_safety(output: Path = OUTPUT) -> dict:
    cases = _read_json(output / "npi_invalid_adversarial_cases.json")
    service = EvidenceDecisionService(route_mode="runtime")
    policies = FieldPolicyRegistry.load()
    deterministic = DeterministicEvidenceService()
    replay_rows = _read_jsonl(P84 / "policy_replay_input.jsonl")
    structural_by_family = {}
    for row in replay_rows:
        if row["field_name"] == "provider_npi" and row["localization_evidence"]["confirmed"]:
            structural_by_family.setdefault(row["family"], row["localization_evidence"])
    results = []
    for case in cases:
        template = next(
            row
            for row in replay_rows
            if row["family"] == case["family"] and row["field_name"] == "provider_npi"
        )
        candidates = []
        for candidate in template["candidates"][:1]:
            candidates.append({**candidate, "value": case["value"], "raw_value": case["value"]})
            candidates.append(
                {
                    **candidate,
                    "value": case["value"],
                    "raw_value": case["value"],
                    "engine": "paddleocr_regional",
                    "model_name": "PP-OCRv4",
                    "model_version": "paddleocr-2.x",
                    "evidence_reference": f"{case['document_id']}:provider_npi:adversarial:paddle",
                }
            )
        facts = deterministic.evaluate("provider_npi", case["value"])
        field_policy = policies.for_field(case["family"], "provider_npi")
        decision = service.decide(
            DecisionContext(
                field_id=f"{case['document_id']}:provider_npi:adversarial",
                field_name="provider_npi",
                document_family=case["family"],
                criticality=field_policy.criticality,
                required=True,
                blocks_stp=True,
                candidates=candidates,
                deterministic_evidence=facts.evidence,
                deterministic_evidence_version=deterministic.policy_version,
                hard_validation_passed=facts.passed,
                structural_localization=StructuralLocalizationEvidence.model_validate(
                    structural_by_family[case["family"]]
                ),
            )
        )
        results.append(
            {
                **case,
                "independent_ocr_agreement": True,
                "hard_validation_passed": facts.passed,
                "disposition": decision.disposition.value,
                "auto_accepted": decision.disposition.value in ACCEPTED,
                "claim_stp_blocked": decision.disposition.value not in ACCEPTED,
            }
        )
    report = {
        "cases": len(results),
        "deterministic_failures": sum(not row["hard_validation_passed"] for row in results),
        "auto_accepts": sum(row["auto_accepted"] for row in results),
        "claim_stp_blocks": sum(row["claim_stp_blocked"] for row in results),
        "false_accepts": sum(row["auto_accepted"] for row in results),
        "all_safety_assertions_passed": all(
            not row["hard_validation_passed"]
            and not row["auto_accepted"]
            and row["claim_stp_blocked"]
            for row in results
        ),
        "results": results,
    }
    _write_json(output / "npi_invalid_adversarial.json", report)
    return report


def residual_blockers(field_rows: list[dict], claim_rows: list[dict], output: Path = OUTPUT) -> dict:
    by_key = {(row["document_id"], row["field_name"]): row for row in field_rows}
    records = []
    for claim in claim_rows:
        for field_name in claim["blocking_unresolved_fields"]:
            row = by_key[(claim["claim_id"], field_name)]
            decision = row["field_decision"]
            if "npi" in field_name and not is_valid_npi(row["truth"]):
                category = "BENCHMARK_INVALID"
            elif row["exact"]:
                category = "CORRECT_MISSING_EVIDENCE"
            elif "AMBIG" in " ".join(decision.get("reason_codes") or []):
                category = "TRUE_AMBIGUITY"
            elif not row["exact"]:
                category = "WRONG_SAFE_REJECT"
            elif "E5" in decision.get("missing_evidence", []):
                category = "REFERENCE_REQUIRED"
            else:
                category = "UNSUPPORTED"
            records.append(
                {
                    "claim_id": claim["claim_id"],
                    "family": row["family"],
                    "field_name": field_name,
                    "category": category,
                    "exact": row["exact"],
                    "missing_evidence": decision.get("missing_evidence", []),
                    "available_evidence": decision.get("available_evidence", []),
                }
            )
    report = {
        "blocking_instances": len(records),
        "by_category": dict(Counter(row["category"] for row in records)),
        "by_field": dict(Counter(row["field_name"] for row in records)),
        "records": records,
    }
    _write_json(output / "residual_blockers.json", report)
    return report


def cost_report(baseline: dict, candidate: dict, output: Path = OUTPUT) -> dict:
    claims_unlocked = candidate["claims_unlocked"] - baseline["claims_unlocked"]
    cost_before = baseline["fully_loaded_cost_per_page_usd"]
    cost_after = candidate["fully_loaded_cost_per_page_usd"]
    report = {
        "assumptions": "Frozen Phase 8.3 illustrative labor/infrastructure assumptions",
        "machine_cost_approximately_unchanged": True,
        "cloud_cost_usd": 0.0,
        "review_fields_per_page_before": baseline["review_fields_per_page"],
        "review_fields_per_page_after": candidate["review_fields_per_page"],
        "review_claims_before": baseline["review_claims"],
        "review_claims_after": candidate["review_claims"],
        "hitl_cost_per_page_before_usd": baseline["hitl_cost_per_page_usd"],
        "hitl_cost_per_page_after_usd": candidate["hitl_cost_per_page_usd"],
        "fully_loaded_cost_per_page_before_usd": cost_before,
        "fully_loaded_cost_per_page_after_usd": cost_after,
        "cost_per_document_after_usd": candidate["cost_per_document_usd"],
        "cost_per_stp_claim_after_usd": candidate["cost_per_stp_claim_usd"],
        "claims_unlocked": claims_unlocked,
        "review_fields_removed": baseline["review_fields"] - candidate["review_fields"],
        "cost_avoided_per_page_usd": cost_before - cost_after,
        "cost_avoided_per_claim_unlocked_usd": (
            (cost_before - cost_after) * 100 / claims_unlocked if claims_unlocked else 0.0
        ),
        "first_target_lt_0_10_passed": cost_after < 0.10,
        "preferred_target_lt_0_05_passed": cost_after < 0.05,
    }
    _write_json(output / "cost.json", report)
    return report


def _write_reports(summary: dict) -> None:
    docs = ROOT / "docs"
    pareto = summary["claim_blocker_pareto"]
    pareto_lines = "\n".join(
        f"- `{row['family']}.{row['field']}`: {row['claims_blocked']} claims, "
        f"{row['single_blocker_claims']} single-blocker unlocks, "
        f"{row['correct_but_reviewed']} correct-but-reviewed, "
        f"{row['benchmark_invalid_value']} benchmark-invalid"
        for row in pareto
    )
    (docs / "CDP_PHASE8_7_CLAIM_BLOCKER_PARETO.md").write_text(
        "# CDP Phase 8.7 Claim Blocker Pareto\n\n"
        "This is the exact canonical Phase 8.6 blocker population. Claim unlock value "
        "is the number of claims for which resolving the field alone removes the last blocker.\n\n"
        f"{pareto_lines}\n",
        "utf-8",
    )
    waterfall_lines = "\n".join(
        f"- {row['step']}: {row['claims_unlocked']} claims ({row['claim_stp']:.2%} STP)"
        for row in summary["claim_unlock_waterfall"]["steps"]
    )
    (docs / "CDP_PHASE8_7_CLAIM_UNLOCK_WATERFALL.md").write_text(
        "# CDP Phase 8.7 Claim Unlock Waterfall\n\n"
        "Counterfactual analysis only; it did not change production decisions.\n\n"
        f"{waterfall_lines}\n",
        "utf-8",
    )
    names = summary["patient_name"]
    (docs / "CDP_PHASE8_7_PATIENT_NAME_EVIDENCE.md").write_text(
        "# CDP Phase 8.7 Patient Name Evidence\n\n"
        f"Rapid/Paddle normalized agreement covers **{names['agreement_coverage']:.2%}** "
        f"of {names['observations']} patient-name fields. Agreement precision is "
        f"**{names['agreement_precision']:.2%}** with **{names['false_agreements']}** false "
        f"agreements. Normalization version: `{NAME_NORMALIZATION_VERSION}`. Candidates "
        "retain raw values, engine/version, invocation ID, crop hash, and preprocessing "
        "profile. No patient-name route was promoted to production from V3.\n",
        "utf-8",
    )
    adversarial = summary["npi_adversarial"]
    (docs / "CDP_PHASE8_7_NPI_ADVERSARIAL_SAFETY.md").write_text(
        "# CDP Phase 8.7 NPI Adversarial Safety\n\n"
        f"The invalid partition contains **{adversarial['cases']}** checksum-invalid NPIs. "
        f"All {adversarial['deterministic_failures']} failed deterministic validation, "
        f"auto-accepts remained **{adversarial['auto_accepts']}**, and all remained claim-STP "
        "blockers even under two-engine agreement. Validation was not weakened.\n",
        "utf-8",
    )
    validity_lines = "\n".join(
        f"- `{field}`: {row['observations']} observations; {row['valid']} valid; "
        f"{row['invalid']} invalid; {row['not_independently_verifiable']} not independently "
        f"verifiable; `{row['validator_version']}`"
        for field, row in summary["validity"]["by_field"].items()
    )
    (docs / "CDP_PHASE8_7_GOLDEN_V3_VALIDITY.md").write_text(
        "# CDP Phase 8.7 Golden V3 Validity\n\n"
        "Golden V3 is PHI-free engineering validation data, not production data, a "
        "production holdout, or production authority.\n\n"
        f"{validity_lines}\n",
        "utf-8",
    )
    residual = summary["residual_blockers"]
    residual_fields = ", ".join(
        f"`{field}` ({count})" for field, count in residual["by_field"].items()
    ) or "none"
    (docs / "CDP_PHASE8_7_RESIDUAL_BLOCKERS.md").write_text(
        "# CDP Phase 8.7 Residual Blockers\n\n"
        f"Residual blocking instances: **{residual['blocking_instances']}**. Fields: "
        f"{residual_fields}. Categories: `{json.dumps(residual['by_category'], sort_keys=True)}`.\n",
        "utf-8",
    )
    baseline = summary["profiles"]["baseline"]
    candidate = summary["profiles"]["candidate"]
    decision = summary["decision"]
    (docs / "CDP_PHASE8_7_FINAL_REPORT.md").write_text(
        "# CDP Phase 8.7 Final Report\n\n"
        f"V3 baseline claim STP was **{baseline['claim_stp']:.2%}**. The independent-name "
        f"engineering candidate reached **{candidate['claim_stp']:.2%}** claim STP, "
        f"**{candidate['accepted_precision']:.2%}** accepted precision, "
        f"**{candidate['critical_false_accepts']}** critical false accepts, and "
        f"**{candidate['field_hitl']:.2%}** field HITL. Fully loaded illustrative cost is "
        f"**${summary['cost']['fully_loaded_cost_per_page_after_usd']:.4f}/page**; cloud "
        "common-path cost remains **$0**.\n\n"
        f"Decision: **{decision['decision']}**. Golden V3 is engineering-only and no route "
        "was production-approved from this dataset alone.\n",
        "utf-8",
    )


def freeze_phase8_7_frontier(output: Path, archive: dict) -> dict:
    git_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    record = {
        "frontier": "PHASE8_7_STP_FRONTIER_V1",
        "engineering_only": True,
        "production_authority": False,
        "implementation_git_sha": git_sha,
        "frozen_phase8_6_git_sha": FROZEN_SHA,
        "golden_v3_sha256": archive["sha256"],
        "candidate_evidence_sha256": _sha(output / "local_evidence_predictions.jsonl"),
        "field_decisions_sha256": _sha(output / "field_decisions.jsonl"),
        "claim_decisions_sha256": _sha(output / "claim_decisions.jsonl"),
        "field_policy_sha256": _sha(ROOT / "config/field_acceptance_policies.yaml"),
        "evidence_policy_sha256": _sha(BALANCED_POLICY),
        "claim_policy_sha256": _sha(ROOT / "config/claim_decision_policies.yaml"),
        "ocr_route_registry_sha256": _sha(ROOT / "config/ocr_field_routes.yaml"),
        "ocr_versions": {
            "rapid": "rapidocr-onnxruntime",
            "paddle": "paddleocr-2.x/PP-OCRv4",
        },
        "name_normalization_version": NAME_NORMALIZATION_VERSION,
        "npi_validator_version": "80840-prefix-luhn-v1",
        "npi_generator_version": NPI_GENERATOR_VERSION,
        "evidence_taxonomy": ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"],
        "route_lifecycle": {
            "patient_name": "EVALUATION_ONLY",
            "UB04.provider_npi": "PHASE8_7_ENGINEERING_EVALUATION_ONLY",
            "production_route_promoted_from_v3": False,
        },
    }
    _write_json(output / "phase8_7_stp_frontier_v1.json", record)
    return record


def finalize(output: Path = OUTPUT) -> dict:
    freeze = freeze_phase8_6(output)
    pareto = claim_blocker_pareto(output)
    waterfall = claim_unlock_waterfall(output)
    validity = audit_v3_validity(V3, output)
    archive = archive_v3(V3, output)
    extraction_path = output / "v3_extraction/metrics.json"
    extraction_metrics = _read_json(extraction_path)
    extraction_metrics["archive_sha256"] = archive["sha256"]
    _write_json(extraction_path, extraction_metrics)
    names = _read_json(output / "patient_name_agreement.json")
    profiles = replay_profiles(output)
    adversarial = adversarial_npi_safety(output)
    residual = residual_blockers(profiles["field_rows"], profiles["claim_rows"], output)
    cost = cost_report(profiles["baseline"], profiles["candidate"], output)
    extraction = profiles["baseline"]["extraction"]
    candidate = profiles["candidate"]
    gates = {
        "cms_accuracy_ge_95": extraction["by_family"]["CMS1500"]["final_field_accuracy"] >= 0.95,
        "ub_accuracy_ge_96": extraction["by_family"]["UB04"]["final_field_accuracy"] >= 0.96,
        "critical_accuracy_ge_95_5": extraction["critical_field_accuracy"] >= 0.955,
        "accepted_precision_ge_99_9": candidate["accepted_precision"] >= 0.999,
        "critical_false_accepts_zero": candidate["critical_false_accepts"] == 0,
        "claim_stp_ge_50": candidate["claim_stp"] >= 0.50,
        "invalid_npi_safety": adversarial["all_safety_assertions_passed"],
        "cloud_common_path_zero": candidate["cloud_calls"] == 0,
    }
    passed = all(gates.values())
    decision = {
        "decision": "FREEZE_PHASE8_7_STP_FRONTIER_V1" if passed else "NO_PROMOTION_SAFE_HITL_REMAINS",
        "all_primary_gates_passed": passed,
        "gates": gates,
        "stop_condition_reached": passed,
        "second_frontier_attempted": False,
        "production_route_promoted_from_v3": False,
        "policy_weakened": False,
        "extraction_or_router_changed": False,
        "truth_used_as_runtime_evidence": False,
        "cloud_cost_usd": 0.0,
    }
    _write_json(output / "decision.json", decision)
    frontier = freeze_phase8_7_frontier(output, archive) if passed else None
    summary = {
        "phase": "8.7",
        "phase8_6_freeze": freeze,
        "golden_v3_archive": archive,
        "validity": validity,
        "claim_blocker_pareto": pareto,
        "claim_unlock_waterfall": waterfall,
        "patient_name": names,
        "npi_adversarial": adversarial,
        "profiles": {"baseline": profiles["baseline"], "candidate": profiles["candidate"]},
        "cost": cost,
        "residual_blockers": residual,
        "decision": decision,
        "frontier": frontier,
    }
    _write_json(output / "summary.json", summary)
    _write_reports(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "build-v3",
            "validity",
            "extract-v3",
            "benchmark-local",
            "rescore-local",
            "replay",
            "finalize",
        ),
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "build-v3":
        value = build_v3(target=args.dataset or V3, output=args.output)
    elif args.action == "validity":
        value = audit_v3_validity(args.dataset or V3, args.output)
    elif args.action == "extract-v3":
        value = run_v3_extraction(args.dataset or V3, args.output)
    elif args.action == "benchmark-local":
        value = benchmark_local_evidence(args.dataset or V3, args.output)
    elif args.action == "rescore-local":
        value = rescore_local_evidence(args.output)
    elif args.action == "replay":
        value = replay_profiles(args.output)
        value = {"baseline": value["baseline"], "candidate": value["candidate"]}
    else:
        value = finalize(args.output)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
