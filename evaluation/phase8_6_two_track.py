"""Phase 8.6: UB benchmark correction and independent local CMS evidence.

OCR is confined to the two benchmark functions. ``targeted_replay`` consumes
their persisted predictions and never invokes an OCR adapter.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.evidence import EvidencePolicy
from packages.evidence.normalization import normalize_agreement_value
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDecision
from packages.evidence_decision.adapters import ocr_candidates_from_field
from packages.extraction_geometry import FormIdentityDecision, FormIdentityStatus
from packages.field_localization import FieldLocator
from packages.field_policy import FieldPolicyRegistry
from packages.page_observation import PageObservationService
from packages.templates import TemplateRegistry
from workers.page_detection.text_extraction import (
    PaddleOCRTextExtractor,
    RapidOCRFullPageTextExtractor,
    RapidOCRTextExtractor,
)
from workers.standard_form_extraction import (
    StandardFormExtractionService,
    StandardFormProcessingService,
)

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
V2 = ROOT / "evaluation_data/phase8_6_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V2"
P84 = ROOT / "evaluation_results/phase8_4"
PHASE8_FIELDS = ROOT / "evaluation_results/phase8_2/final/field_records.jsonl"
OUTPUT = ROOT / "evaluation_results/phase8_6"
BALANCED_POLICY = ROOT / "config/evidence_policies_phase8_4_balanced.yaml"
TARGET_FIELDS = {"member_id", "provider_npi", "total_charge"}
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


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _tax_value(document_id: str) -> str:
    return f"98{int(document_id.removeprefix('UB')):07d}"


def render_tax_field(image: Image.Image, document_id: str, variant: str) -> tuple[str, list[int]]:
    """Add an explicit, truth-measurable UB tax field without changing V1."""
    field_box = (890, 370, 1329, 460)
    patch = Image.new("RGB", (field_box[2] - field_box[0], field_box[3] - field_box[1]), "white")
    draw = ImageDraw.Draw(patch)
    ink = 75 if variant == "low_contrast" else 0
    draw.rectangle((0, 0, patch.width - 1, patch.height - 1), outline=(ink, ink, ink), width=2)
    draw.text((8, 5), "FEDERAL TAX NO", fill=(ink, ink, ink), font=_font(18))
    value = _tax_value(document_id)
    value_position = (10, 40)
    value_font = _font(24)
    draw.text(value_position, value, fill=(ink, ink, ink), font=value_font)
    if variant == "blur":
        patch = patch.filter(ImageFilter.GaussianBlur(0.65))
    elif variant == "low_contrast":
        patch = ImageEnhance.Contrast(patch).enhance(0.55)
    elif variant == "noise":
        pixels = patch.load()
        rng = random.Random(int(document_id.removeprefix("UB")))
        for _ in range(450):
            x, y = rng.randrange(patch.width), rng.randrange(patch.height)
            level = rng.choice((80, 120, 180, 220))
            pixels[x, y] = (level, level, level)
    image.paste(patch, field_box[:2])
    box = ImageDraw.Draw(image).textbbox(
        (field_box[0] + value_position[0], field_box[1] + value_position[1]),
        value,
        font=value_font,
    )
    return value, list(box)


def build_ub_corrected_pack(source: Path = V1, target: Path = V2) -> dict:
    if target.exists():
        manifest = _read_json(target / "manifest.json")
        if manifest.get("dataset_id") != "CDP_GOLDEN_ENGINEERING_PACK_V2":
            raise RuntimeError(f"refusing to overwrite unexpected dataset: {target}")
        return manifest
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest = _read_json(target / "manifest.json")
    with (target / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    documents = {row["document_id"]: row for row in manifest["documents"]}
    added = []
    for document_id in sorted(name for name in documents if name.startswith("UB")):
        document = documents[document_id]
        path = target / document["file"]
        with Image.open(path) as source_image:
            image = source_image.convert("RGB")
        value, bbox = render_tax_field(image, document_id, document["variant"])
        image.save(path, optimize=True)
        document["sha256"] = _sha(path)
        added.append(
            {
                "document_id": document_id,
                "page_id": "1",
                "form_type": "UB04_MOCK",
                "field_name": "federal_tax_no",
                "expected_value": value,
                "bbox_json": json.dumps(bbox),
            }
        )
    columns = [
        "document_id",
        "page_id",
        "form_type",
        "field_name",
        "expected_value",
        "bbox_json",
    ]
    with (target / "field_truth.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows([*truth, *added])
    manifest.update(
        {
            "dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V2",
            "parent_dataset_id": "CDP_GOLDEN_ENGINEERING_PACK_V1",
            "field_truth_rows": len(truth) + len(added),
            "schema_correction": {
                "field": "UB04.federal_tax_no",
                "documents_corrected": len(added),
                "reason": "V1 policy required the field but images and truth omitted it",
                "production_promotion_authority": False,
            },
        }
    )
    _write_json(target / "manifest.json", manifest)
    _write_json(
        target / "phase8_6_provenance.json",
        {
            "dataset_id": manifest["dataset_id"],
            "parent_dataset_id": manifest["parent_dataset_id"],
            "parent_manifest_sha256": _sha(source / "manifest.json"),
            "generator": "evaluation.phase8_6_two_track.build_ub_corrected_pack",
            "synthetic": True,
            "contains_real_phi": False,
            "added_truth_rows": len(added),
            "unchanged_cms_documents": 50,
        },
    )
    (target / "README_PHASE8_6.md").write_text(
        "# Golden Engineering Pack V2\n\n"
        "V2 preserves V1 and adds an explicitly rendered, truth-labeled "
        "`UB04.federal_tax_no` to all 50 UB engineering mocks. It remains "
        "synthetic engineering data without production-promotion authority.\n",
        "utf-8",
    )
    return manifest


def archive_corrected_pack(dataset: Path = V2, output: Path = OUTPUT) -> dict:
    archive = output / "CDP_GOLDEN_ENGINEERING_PACK_V2.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(dataset.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(dataset.name) / path.relative_to(dataset))
    result = {"path": str(archive.relative_to(ROOT)), "sha256": _sha(archive), "bytes": archive.stat().st_size}
    _write_json(output / "dataset_archive.json", result)
    return result


def _truth_rows(dataset: Path) -> list[dict]:
    with (dataset / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _extract_paddle(extractor, image: Image.Image, bbox) -> tuple[str | None, float, float]:
    crop = image.crop(tuple(round(value) for value in bbox))
    started = time.perf_counter()
    lines = extractor.extract_region(crop, 0, 0, crop.width, crop.height)
    latency = (time.perf_counter() - started) * 1000
    value = " ".join(line.text for line in lines).strip() or None
    confidence = statistics.fmean(line.confidence for line in lines) if lines else 0.0
    return value, confidence, latency


def _candidate_payload(candidate) -> dict:
    return {
        **vars(candidate),
        "bounding_box": candidate.bounding_box.model_dump(mode="json"),
        "validation_results": list(candidate.validation_results),
        "provenance": (
            candidate.provenance.model_dump(mode="json") if candidate.provenance else None
        ),
    }


def benchmark_ub_tax(dataset: Path = V2, output: Path = OUTPUT) -> dict:
    manifest = _read_json(dataset / "manifest.json")
    documents = [row for row in manifest["documents"] if row["document_id"].startswith("UB")]
    truth = {
        row["document_id"]: row
        for row in _truth_rows(dataset)
        if row["field_name"] == "federal_tax_no"
    }
    observation_service = PageObservationService(
        RapidOCRFullPageTextExtractor(), preprocessing_version="phase8.6-ub-correction-v1"
    )
    extractor = StandardFormExtractionService(RapidOCRTextExtractor())
    processor = StandardFormProcessingService(observation_service, extractor)
    paddle = PaddleOCRTextExtractor()
    template = TemplateRegistry.load_from_directory().get("ub04", "2014")
    rows = []
    for index, document in enumerate(documents, 1):
        with Image.open(dataset / document["file"]) as source_image:
            image = source_image.convert("RGB")
        processing = processor.process(
            image,
            template,
            1,
            FormIdentityDecision(
                family=DocumentClass.UB04,
                status=FormIdentityStatus.VERIFIED,
                score=1,
            ),
            page_id=document["document_id"],
            page_sha256=document["sha256"],
        )
        expected = truth[document["document_id"]]["expected_value"]
        truth_box = json.loads(truth[document["document_id"]]["bbox_json"])
        roi = processing.roi_results["federal_tax_no"]
        location = FieldLocator().locate(
            processing.observation, processing.field_definitions["federal_tax_no"]
        )
        field = next(item for item in processing.fields if item.field_name == "federal_tax_no")
        paddle_value, paddle_confidence, paddle_latency = _extract_paddle(
            paddle, image, roi.bbox
        )
        rapid_value = field.normalized_value or field.raw_value
        expected_norm = normalize_agreement_value("federal_tax_no", expected)
        rapid_norm = normalize_agreement_value("federal_tax_no", rapid_value)
        paddle_norm = normalize_agreement_value("federal_tax_no", paddle_value)
        bbox = roi.bbox
        intersection = max(0, min(bbox[2], truth_box[2]) - max(bbox[0], truth_box[0])) * max(
            0, min(bbox[3], truth_box[3]) - max(bbox[1], truth_box[1])
        )
        truth_area = max(1, (truth_box[2] - truth_box[0]) * (truth_box[3] - truth_box[1]))
        rows.append(
            {
                "document_id": document["document_id"],
                "variant": document["variant"],
                "expected": expected,
                "truth_bbox": truth_box,
                "predicted_bbox": bbox,
                "localization_success": intersection / truth_area >= 0.95,
                "localization_mode": roi.mode.value,
                "localization_confidence": location.confidence,
                "localization_reason_codes": list(roi.reason_codes),
                "rapid_value": rapid_value,
                "rapid_confidence": field.confidence,
                "rapid_exact": rapid_norm == expected_norm,
                "paddle_value": paddle_value,
                "paddle_confidence": paddle_confidence,
                "paddle_latency_ms": paddle_latency,
                "paddle_exact": paddle_norm == expected_norm,
                "independent_agreement": bool(rapid_norm and rapid_norm == paddle_norm),
                "false_agreement": bool(rapid_norm and rapid_norm == paddle_norm != expected_norm),
                "secondary_invoked": True,
                "rapid_candidates": [
                    _candidate_payload(candidate) for candidate in ocr_candidates_from_field(field)
                ],
            }
        )
        print(f"phase8.6 UB tax: {index}/{len(documents)}", flush=True)
    agreements = [row for row in rows if row["independent_agreement"]]
    metrics = {
        "dataset_id": manifest["dataset_id"],
        "observations": len(rows),
        "truth_rows": len(truth),
        "localization_success": sum(row["localization_success"] for row in rows) / len(rows),
        "rapid_accuracy": sum(row["rapid_exact"] for row in rows) / len(rows),
        "paddle_accuracy": sum(row["paddle_exact"] for row in rows) / len(rows),
        "independent_agreement_coverage": len(agreements) / len(rows),
        "agreement_precision": (
            sum(not row["false_agreement"] for row in agreements) / len(agreements)
            if agreements
            else None
        ),
        "false_agreements": sum(row["false_agreement"] for row in rows),
        "secondary_ocr_rate": 1.0,
        "p50_secondary_latency_ms": statistics.median(
            row["paddle_latency_ms"] for row in rows
        ),
        "cloud_cost_usd": 0.0,
        "promotion_gate_passed": bool(
            len(agreements) >= 30
            and not any(row["false_agreement"] for row in rows)
            and all(row["localization_success"] for row in rows)
        ),
    }
    _write_jsonl(output / "ub_federal_tax_predictions.jsonl", rows)
    _write_json(output / "ub_federal_tax_metrics.json", metrics)
    return metrics


def benchmark_cms_local_evidence(dataset: Path = V1, output: Path = OUTPUT) -> dict:
    manifest = _read_json(dataset / "manifest.json")
    documents = {row["document_id"]: row for row in manifest["documents"]}
    frozen = [
        row
        for row in _read_jsonl(P84 / "policy_replay_input.jsonl")
        if row["family"] == "CMS1500" and row["field_name"] in TARGET_FIELDS
    ]
    frozen_boxes = {
        (row["document_id"], row["field_name"]): row["predicted_bbox"]
        for row in _read_jsonl(PHASE8_FIELDS)
    }
    paddle = PaddleOCRTextExtractor()
    rows = []
    for index, row in enumerate(frozen, 1):
        document = documents[row["document_id"]]
        with Image.open(dataset / document["file"]) as source_image:
            image = source_image.convert("RGB")
        predicted_bbox = frozen_boxes[(row["document_id"], row["field_name"])]
        value, confidence, latency = _extract_paddle(paddle, image, predicted_bbox)
        expected_norm = normalize_agreement_value(row["field_name"], row["truth"])
        current_norm = normalize_agreement_value(row["field_name"], row["final_value"])
        paddle_norm = normalize_agreement_value(row["field_name"], value)
        rows.append(
            {
                "document_id": row["document_id"],
                "family": row["family"],
                "field_name": row["field_name"],
                "truth": row["truth"],
                "current_value": row["final_value"],
                "current_exact": current_norm == expected_norm,
                "paddle_value": value,
                "paddle_confidence": confidence,
                "paddle_latency_ms": latency,
                "paddle_exact": paddle_norm == expected_norm,
                "independent_agreement": bool(current_norm and current_norm == paddle_norm),
                "false_agreement": bool(current_norm and current_norm == paddle_norm != expected_norm),
                "predicted_bbox": predicted_bbox,
                "engine": "paddleocr_regional",
                "model_name": "PP-OCRv4",
                "model_version": "paddleocr-2.x",
                "preprocessing_variant": "recorded-canonical-field-crop-v1",
            }
        )
        print(f"phase8.6 CMS local evidence: {index}/{len(frozen)}", flush=True)
    by_field = {}
    for field_name in sorted(TARGET_FIELDS):
        values = [row for row in rows if row["field_name"] == field_name]
        agreements = [row for row in values if row["independent_agreement"]]
        false = sum(row["false_agreement"] for row in values)
        by_field[field_name] = {
            "observations": len(values),
            "paddle_accuracy": sum(row["paddle_exact"] for row in values) / len(values),
            "agreement_count": len(agreements),
            "agreement_coverage": len(agreements) / len(values),
            "agreement_precision": (
                sum(not row["false_agreement"] for row in agreements) / len(agreements)
                if agreements
                else None
            ),
            "false_agreements": false,
            "p50_latency_ms": statistics.median(row["paddle_latency_ms"] for row in values),
            "promotion_gate_passed": bool(len(agreements) >= 30 and false == 0),
        }
    metrics = {
        "dataset_id": manifest["dataset_id"],
        "engine_family": "PADDLE_FAMILY",
        "independent_from_current_family": "RAPID_ONNX_FAMILY",
        "cloud_cost_usd": 0.0,
        "by_field": by_field,
    }
    _write_jsonl(output / "cms_local_evidence_predictions.jsonl", rows)
    _write_json(output / "cms_local_evidence_metrics.json", metrics)
    return metrics


def _paddle_candidate(row: dict, replay_row: dict) -> dict:
    bbox = replay_row.get("predicted_bbox") or row["predicted_bbox"]
    return {
        "value": row["paddle_value"],
        "raw_value": row["paddle_value"],
        "engine": "paddleocr_regional",
        "model_name": row.get("model_name", "PP-OCRv4"),
        "model_version": row.get("model_version", "paddleocr-2.x"),
        "preprocessing_variant": row.get(
            "preprocessing_variant", "recorded-canonical-field-crop-v1"
        ),
        "raw_confidence": row["paddle_confidence"],
        "calibrated_confidence": None,
        "bounding_box": {
            "x0": bbox[0],
            "y0": bbox[1],
            "x1": bbox[2],
            "y1": bbox[3],
            "image_width": max(1, bbox[2]),
            "image_height": max(1, bbox[3]),
        },
        "latency_ms": row["paddle_latency_ms"],
        "validation_results": [],
        "evidence_reference": f"{row['document_id']}:{row.get('field_name', 'federal_tax_no')}:paddle",
    }


def _profile_metrics(fields: list[dict], claims: list[dict]) -> dict:
    accepted = [row for row in fields if row["field_decision"]["disposition"] in ACCEPTED]
    incorrect = [row for row in accepted if not row["exact"]]
    stp = [row for row in claims if row["stp_eligible"]]
    page_count = len({row["document_id"] for row in fields})
    review_fields_per_page = (len(fields) - len(accepted)) / page_count
    field_review_cost = review_fields_per_page * (25 / 3600) * 5
    claim_review_cost = (1 - len(stp) / len(claims)) * (25 / 3600) * 30 / 3
    machine_and_shared_cost = 0.0005907903458333426 + 0.0001
    return {
        "eligible_fields": len(fields),
        "accepted_fields": len(accepted),
        "safe_field_coverage": sum(row["exact"] for row in accepted) / len(fields),
        "field_hitl": 1 - len(accepted) / len(fields),
        "accepted_precision": sum(row["exact"] for row in accepted) / max(1, len(accepted)),
        "false_accepts": len(incorrect),
        "critical_false_accepts": sum(
            row["criticality"] in {"C2", "C3"} for row in incorrect
        ),
        "claim_stp": len(stp) / len(claims),
        "claim_hitl": 1 - len(stp) / len(claims),
        "claims_unlocked": len(stp),
        "review_fields_per_page": review_fields_per_page,
        "illustrative_hitl_cost_per_page_usd": field_review_cost + claim_review_cost,
        "illustrative_fully_loaded_cost_per_page_usd": (
            field_review_cost + claim_review_cost + machine_and_shared_cost
        ),
        "ocr_invocations_during_replay": 0,
        "cloud_cost_usd": 0.0,
    }


def targeted_replay(output: Path = OUTPUT) -> dict:
    cms_predictions = {
        (row["document_id"], row["field_name"]): row
        for row in _read_jsonl(output / "cms_local_evidence_predictions.jsonl")
    }
    ub_predictions = {
        row["document_id"]: row
        for row in _read_jsonl(output / "ub_federal_tax_predictions.jsonl")
    }
    replay_rows = _read_jsonl(P84 / "policy_replay_input.jsonl")
    replay_by_key = {(row["document_id"], row["field_name"]): row for row in replay_rows}
    frozen_fields = _read_jsonl(P84 / "profile_c/field_decisions.jsonl")
    policies = FieldPolicyRegistry.load()
    evidence = EvidenceDecisionService(
        evidence_policy=EvidencePolicy.load(BALANCED_POLICY),
        field_policy=policies,
        route_mode="runtime",
    )
    deterministic = DeterministicEvidenceService()
    replacements = {}
    for key, prediction in cms_predictions.items():
        row = replay_by_key[key]
        policy = policies.for_field(row["family"], row["field_name"])
        candidates = [*row["candidates"]]
        if prediction["paddle_value"]:
            candidates.append(_paddle_candidate(prediction, row))
        decision = evidence.decide(
            DecisionContext(
                field_id=f"{row['document_id']}:{row['field_name']}",
                field_name=row["field_name"],
                document_family=row["family"],
                criticality=policy.criticality,
                required=policy.required,
                blocks_stp=policy.blocks_stp,
                requires_review_when_unresolved=policy.requires_review_when_unresolved,
                candidates=candidates,
                deterministic_evidence=set(row["deterministic_validation"]["evidence"]),
                deterministic_evidence_version=row["deterministic_validation"]["version"],
                hard_validation_passed=row["deterministic_validation"]["passed"],
                structural_localization=row["localization_evidence"],
                wrong_crop_suspected=row["wrong_crop_suspected"],
                cross_field_evidence=set(row["cross_field_evidence"]),
            )
        )
        replacements[key] = decision.model_dump(mode="json")
    fields_b = list(frozen_fields)
    fields_c = []
    for row in frozen_fields:
        key = (row["document_id"], row["field_name"])
        fields_c.append({**row, "field_decision": replacements.get(key, row["field_decision"])})
    for document_id, prediction in ub_predictions.items():
        policy = policies.for_field("UB04", "federal_tax_no")
        synthetic_replay = {
            "document_id": document_id,
            "field_name": "federal_tax_no",
            "predicted_bbox": prediction["predicted_bbox"],
        }
        candidates = [*prediction["rapid_candidates"]]
        if prediction["paddle_value"]:
            candidates.append(_paddle_candidate(prediction, synthetic_replay))
        facts = deterministic.evaluate("federal_tax_no", prediction["rapid_value"])
        localization = {
            "evidence_type": "ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED",
            "confidence": prediction["localization_confidence"],
            "confirmed": prediction["localization_success"],
            "reason_codes": prediction["localization_reason_codes"],
            "source": "DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
            "version": "structural-localization-evidence-v1",
        }
        decision = evidence.decide(
            DecisionContext(
                field_id=f"{document_id}:federal_tax_no",
                field_name="federal_tax_no",
                document_family="UB04",
                criticality=policy.criticality,
                required=policy.required,
                blocks_stp=policy.blocks_stp,
                requires_review_when_unresolved=policy.requires_review_when_unresolved,
                candidates=candidates,
                deterministic_evidence=facts.evidence,
                deterministic_evidence_version=deterministic.policy_version,
                hard_validation_passed=facts.passed,
                structural_localization=localization,
            )
        )
        new_row = {
            "document_id": document_id,
            "page_id": document_id,
            "family": "UB04",
            "field_name": "federal_tax_no",
            "truth": prediction["expected"],
            "final_value": prediction["rapid_value"],
            "exact": prediction["rapid_exact"],
            "criticality": policy.criticality.value,
            "field_decision": decision.model_dump(mode="json"),
        }
        fields_b.append(new_row)
        fields_c.append(new_row)

    def claim_replay(field_rows: list[dict]) -> list[dict]:
        by_document: dict[str, list[FieldDecision]] = defaultdict(list)
        family_by_document = {}
        for row in field_rows:
            by_document[row["document_id"]].append(
                FieldDecision.model_validate(row["field_decision"])
            )
            family_by_document[row["document_id"]] = row["family"]
        service = ClaimDecisionService.load(field_policy=policies)
        return [
            service.decide(
                ClaimDecisionContext(
                    claim_id=document_id,
                    document_family=family_by_document[document_id],
                    field_decisions=decisions,
                    policy_id=service.policy_id,
                    policy_version=service.policy_version,
                )
            ).model_dump(mode="json")
            for document_id, decisions in sorted(by_document.items())
        ]

    claims_b = claim_replay(fields_b)
    claims_c = claim_replay(fields_c)
    remaining_blockers = Counter(
        field_name
        for claim in claims_c
        for field_name in claim["blocking_unresolved_fields"]
    )
    profile_a = {
        **_read_json(P84 / "profile_c/metrics.json"),
        "profile_name": "PHASE8_5_FROZEN_BASELINE",
        "claims_unlocked": 0,
        "ocr_invocations_during_replay": 0,
    }
    profile_b = {
        **_profile_metrics(fields_b, claims_b),
        "profile_name": "UB_SCHEMA_CORRECTION_AND_LOCAL_EVIDENCE",
    }
    profile_c = {
        **_profile_metrics(fields_c, claims_c),
        "profile_name": "UB_AND_CMS_INDEPENDENT_LOCAL_EVIDENCE",
    }
    _write_json(output / "profile_a.json", profile_a)
    _write_json(output / "profile_b.json", profile_b)
    _write_json(output / "profile_c.json", profile_c)
    _write_jsonl(output / "field_decisions.jsonl", fields_c)
    _write_jsonl(output / "claim_decisions.jsonl", claims_c)
    _write_json(
        output / "decision.json",
        {
            "profile_b": profile_b,
            "profile_c": profile_c,
            "safety_gate_passed": profile_c["false_accepts"] == 0
            and profile_c["critical_false_accepts"] == 0
            and profile_c["accepted_precision"] >= 0.999,
            "policy_weakened": False,
            "reference_data_added": False,
            "cloud_cost_usd": 0.0,
            "ocr_invocations_during_policy_replay": 0,
            "remaining_blocker_pareto": dict(remaining_blockers.most_common()),
            "claim_stp_not_activated_reason": (
                "Remaining fields do not meet existing evidence and deterministic "
                "validation requirements; policy was not weakened."
            ),
        },
    )
    return {"profile_a": profile_a, "profile_b": profile_b, "profile_c": profile_c}


def finalize(output: Path = OUTPUT) -> dict:
    archive = archive_corrected_pack(output=output)
    ub = _read_json(output / "ub_federal_tax_metrics.json")
    cms = _read_json(output / "cms_local_evidence_metrics.json")
    profiles = targeted_replay(output)
    summary = {
        "phase": "8.6",
        "tracks": {
            "ub_benchmark_schema_correction": ub,
            "cms_independent_local_evidence": cms,
        },
        "profiles": profiles,
        "dataset_archive": archive,
    }
    _write_json(output / "summary.json", summary)
    docs = ROOT / "docs"
    (docs / "CDP_PHASE8_6_UB_BENCHMARK_CORRECTION.md").write_text(
        "# Phase 8.6 UB Benchmark Correction\n\n"
        f"Golden Pack V2 contains 50 rendered and truth-labeled federal tax numbers. "
        f"Localization: **{ub['localization_success']:.2%}**; Rapid accuracy: "
        f"**{ub['rapid_accuracy']:.2%}**; independent agreement coverage: "
        f"**{ub['independent_agreement_coverage']:.2%}**; false agreements: "
        f"**{ub['false_agreements']}**. The archive SHA256 is `{archive['sha256']}`.\n",
        "utf-8",
    )
    cms_lines = "\n".join(
        f"- `{name}`: Paddle accuracy {row['paddle_accuracy']:.2%}, agreement coverage "
        f"{row['agreement_coverage']:.2%}, false agreements {row['false_agreements']}, "
        f"promotion gate {'PASS' if row['promotion_gate_passed'] else 'FAIL'}"
        for name, row in cms["by_field"].items()
    )
    (docs / "CDP_PHASE8_6_CMS_LOCAL_EVIDENCE.md").write_text(
        "# Phase 8.6 CMS Independent Local Evidence\n\n"
        "PaddleOCR regional candidates are a distinct engine family from the existing "
        "RapidOCR candidates. Agreement is exact after field-aware normalization.\n\n"
        f"{cms_lines}\n",
        "utf-8",
    )
    c = profiles["profile_c"]
    decision = _read_json(output / "decision.json")
    blocker_text = ", ".join(
        f"`{name}` ({count})"
        for name, count in decision["remaining_blocker_pareto"].items()
    )
    (docs / "CDP_PHASE8_6_FINAL_REPORT.md").write_text(
        "# CDP Phase 8.6 Final Report\n\n"
        "Phase 8.6 kept UB benchmark repair separate from CMS evidence acquisition. "
        "No policy threshold or blocking flag was weakened.\n\n"
        f"Combined safe coverage: **{c['safe_field_coverage']:.2%}**; field HITL: "
        f"**{c['field_hitl']:.2%}**; claim STP: **{c['claim_stp']:.2%}**; claim HITL: "
        f"**{c['claim_hitl']:.2%}**; false accepts: **{c['false_accepts']}**; "
        f"critical false accepts: **{c['critical_false_accepts']}**; cloud cost: **$0**.\n"
        f"\nIllustrative fully loaded cost is **${c['illustrative_fully_loaded_cost_per_page_usd']:.4f} per page** "
        "under the frozen Phase 8.3 labor and infrastructure assumptions. "
        f"Remaining claim blockers: {blocker_text}. Claim STP remains disabled because "
        "those fields do not yet satisfy the unchanged evidence and validation policy.\n",
        "utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("build-ub", "benchmark-ub", "benchmark-cms", "replay", "finalize")
    )
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "build-ub":
        value = build_ub_corrected_pack(target=args.dataset or V2)
    elif args.action == "benchmark-ub":
        value = benchmark_ub_tax(dataset=args.dataset or V2, output=args.output)
    elif args.action == "benchmark-cms":
        value = benchmark_cms_local_evidence(dataset=args.dataset or V1, output=args.output)
    elif args.action == "replay":
        value = targeted_replay(args.output)
    else:
        value = finalize(args.output)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
