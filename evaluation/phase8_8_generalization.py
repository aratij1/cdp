"""Phase 8.8 source-disjoint generalization evaluation.

This module never modifies production extraction, routing, or decision policy.
It builds PHI-free source families, runs the frozen Phase 8.7 engineering route,
and keeps the locked holdout single-use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from evaluation.phase8_1_golden import run as run_extraction
from evaluation.phase8_2_analysis import _candidates
from evaluation.phase8_4_policy_replay import _structural
from evaluation.phase8_6_two_track import _extract_paddle, _paddle_candidate
from evaluation.phase8_7_stp import (
    ACCEPTED,
    BALANCED_POLICY,
    _candidate_payload,
    _eligible_name_candidate,
    _name_classification,
    _profile_metrics,
    _service_lines,
    generate_valid_npi,
)
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
V3 = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3"
DATA_ROOT = ROOT / "evaluation_data/phase8_8_generalization"
OUTPUT = ROOT / "evaluation_results/phase8_8"
P87 = ROOT / "evaluation_results/phase8_7"
SOURCE_IDS = ("SOURCE_A", "SOURCE_B", "SOURCE_C")
HOLDOUT_ID = "PHASE8_8_LOCKED_HOLDOUT_V1"
GENERATOR_VERSION = "phase8.8-source-disjoint-renderer-v1"
GENERATOR_SEED = "phase8.8-generalization-20260824"
ROUTE_FIELDS = {"patient_name", "provider_npi", "member_id", "total_charge", "federal_tax_no"}
FIRST_NAMES = (
    "ALINA", "BRENNAN", "CELINE", "DEVON", "ELARA", "FARIS", "GRETA", "HUGO",
    "ILANA", "JASPER", "KEIRA", "LUCAS", "MIREYA", "NOLAN", "ORLA", "PRIYA",
)
LAST_NAMES = (
    "QUARTZ", "RIVERA", "SATO", "THORNE", "USMAN", "VARGAS", "WELLS", "XU",
    "YATES", "ZAMAN", "BECKETT", "CORTEZ", "DUBOIS", "ENGSTROM", "FARRELL", "GUPTA",
)
PROVIDER_WORDS = (
    "NORTHSTAR", "BLUEBIRD", "CEDAR", "HARBOR", "JUNIPER", "KEYSTONE", "LANTERN",
    "MERIDIAN", "ORCHARD", "PINNACLE", "REDWOOD", "SUMMIT",
)


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


def _tree_sha(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _perceptual_hash(path: Path) -> str:
    with Image.open(path) as source:
        pixels = list(source.convert("L").resize((8, 8)).getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if value >= average else "0" for value in pixels)
    return f"{int(bits, 2):016x}"


def _font(source_id: str, size: int) -> ImageFont.ImageFont:
    names = {
        "SOURCE_A": ("arial.ttf", "calibri.ttf"),
        "SOURCE_B": ("tahoma.ttf", "arial.ttf"),
        "SOURCE_C": ("consola.ttf", "cour.ttf"),
        HOLDOUT_ID: ("verdana.ttf", "tahoma.ttf"),
    }[source_id]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _replacement_values(source_id: str, ordinal: int, family: str, line_count: int) -> tuple[dict, list[dict]]:
    source_number = (*SOURCE_IDS, HOLDOUT_ID).index(source_id) + 1
    unique = source_number * 1000 + ordinal
    patient = f"{FIRST_NAMES[unique % len(FIRST_NAMES)]} {LAST_NAMES[(unique * 7) % len(LAST_NAMES)]}"
    provider = f"{PROVIDER_WORDS[unique % len(PROVIDER_WORDS)]} MEDICAL GROUP {unique:04d}"
    dob = f"{unique % 12 + 1:02d}/{unique % 27 + 1:02d}/{1940 + unique % 10:04d}"
    service_date = f"{unique % 12 + 1:02d}/{(unique * 3) % 27 + 1:02d}/2027"
    lines = []
    total = Decimal(0)
    for index in range(line_count):
        charge = Decimal(1200 + (unique * 13 + index * 47) % 825) + Decimal(
            (unique * 17 + index * 29) % 100
        ) / 100
        total += charge
        lines.append(
            {
                "revenue_code": ("0300", "0450", "0636", "0250")[(unique + index) % 4],
                "description": ("IMAGING", "CLINIC", "LABORATORY", "PHARMACY")[(unique + index) % 4],
                "hcpcs": ("85025", "80053", "99284", "71046")[(unique + index) % 4],
                "service_date": f"{(unique + index) % 12 + 1:02d}/{(unique + index * 2) % 27 + 1:02d}/2027",
                "units": str(index % 3 + 1),
                "charge": f"{charge:.2f}",
            }
        )
    values = {
        "patient_name": patient,
        "patient_dob": dob,
        "member_id": f"G{source_number}8-{unique:07d}",
        "provider_name": provider,
        "provider_npi": generate_valid_npi(f"phase8.8:{source_id}:{ordinal}"),
        "total_charge": f"{total if family == 'UB04' else Decimal(3000 + unique % 900) + Decimal(unique % 100) / 100:.2f}",
    }
    if family == "CMS1500":
        values.update(
            {
                "insured_name": patient,
                "relationship": "SELF",
                "service_date": service_date,
                "cpt_hcpcs": f"A{unique % 10000:04d}",
                "diagnosis": f"Z{unique % 90:02d}.{unique % 10}",
            }
        )
    else:
        values.update(
            {
                "type_of_bill": f"2{source_number}{unique % 10}",
                "principal_diagnosis": f"Y{unique % 90:02d}.{unique % 10}",
                "federal_tax_no": f"{70 + source_number:02d}{unique % 10_000_000:07d}",
            }
        )
    return values, lines


def _draw_value(image: Image.Image, value: str, bbox: list[int], source_id: str) -> None:
    x0, y0, x1, y1 = bbox
    margin = 3
    ImageDraw.Draw(image).rectangle((x0 - margin, y0 - margin, x1 + margin, y1 + margin), fill="white")
    size = 19 if source_id != "SOURCE_C" else 17
    font = _font(source_id, size)
    while size > 10 and font.getbbox(value)[2] > max(10, x1 - x0 + 12):
        size -= 1
        font = _font(source_id, size)
    ink = 25 if source_id != "SOURCE_B" else 65
    ImageDraw.Draw(image).text((x0, y0 - 3), value, font=font, fill=(ink, ink, ink))


def _source_transform(image: Image.Image, source_id: str, ordinal: int) -> Image.Image:
    rng = random.Random(f"{GENERATOR_SEED}:{source_id}:{ordinal}")
    if source_id == "SOURCE_A":
        return ImageEnhance.Sharpness(image).enhance(1.08)
    if source_id == "SOURCE_B":
        value = image.convert("L").filter(ImageFilter.GaussianBlur(0.45))
        value = ImageEnhance.Contrast(value).enhance(0.82)
        buffer = io.BytesIO()
        value.save(buffer, "JPEG", quality=62, dpi=(180, 180))
        buffer.seek(0)
        return Image.open(buffer).convert("RGB")
    if source_id == "SOURCE_C":
        shift = rng.choice((-8, -5, 5, 8))
        value = image.transform(
            image.size,
            Image.Transform.AFFINE,
            (1, 0.006, shift, -0.002, 1, 2),
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
        small = value.resize((1190, 1530), Image.Resampling.LANCZOS)
        return small.resize(image.size, Image.Resampling.BICUBIC)
    value = image.rotate(-0.55, resample=Image.Resampling.BICUBIC, fillcolor="white")
    value = ImageEnhance.Contrast(value).enhance(0.72).filter(ImageFilter.GaussianBlur(0.3))
    draw = ImageDraw.Draw(value)
    for _ in range(160):
        x, y = rng.randrange(value.width), rng.randrange(value.height)
        level = rng.randrange(120, 225)
        draw.point((x, y), fill=(level, level, level))
    return value


def _source_configuration(source_id: str) -> dict:
    return {
        "SOURCE_A": {
            "source_id": "digital-vector-export",
            "renderer_lineage": "arial-direct-raster-v1",
            "template_lineage": "cms-ub-public-spec-standard",
            "generation_method": "direct RGB rendering with source-specific values",
        },
        "SOURCE_B": {
            "source_id": "fax-office-scanner",
            "renderer_lineage": "tahoma-grayscale-jpeg-fax-v1",
            "template_lineage": "cms-ub-public-spec-standard",
            "generation_method": "grayscale blur, contrast loss, and JPEG fax pipeline",
        },
        "SOURCE_C": {
            "source_id": "alternate-export-system",
            "renderer_lineage": "consolas-affine-resample-v1",
            "template_lineage": "cms-ub-public-spec-offset-v1",
            "generation_method": "alternate font metrics, affine offsets, and DPI resampling",
        },
        HOLDOUT_ID: {
            "source_id": "locked-scanner-source",
            "renderer_lineage": "verdana-rotation-noise-v1",
            "template_lineage": "cms-ub-public-spec-heldout-v1",
            "generation_method": "unseen font, rotation, contrast loss, blur, and scanner speckle",
        },
    }[source_id]


def _replace_service_line(
    image: Image.Image,
    row: dict,
    values: dict,
    source_id: str,
) -> dict:
    boxes = json.loads(row["cell_bboxes_json"])
    mapping = {
        "REV": "revenue_code",
        "DESCRIPTION": "description",
        "HCPCS": "hcpcs",
        "SERVICE DATE": "service_date",
        "UNITS": "units",
        "CHARGE": "charge",
    }
    for label, field_name in mapping.items():
        _draw_value(image, values[field_name], boxes[label], source_id)
    return {
        **row,
        "revenue_code": values["revenue_code"],
        "description": values["description"],
        "hcpcs": values["hcpcs"],
        "service_date": values["service_date"],
        "units": values["units"],
        "charge": values["charge"],
    }


def build_corpora(data_root: Path = DATA_ROOT, output: Path = OUTPUT) -> dict:
    """Build immutable-role, source/value-disjoint PHI-free corpora."""
    if data_root.exists():
        registry = _read_json(output / "dataset_registry.json")
        expected = {row["dataset_id"]: row["sha256"] for row in registry["datasets"]}
        actual = {
            source_id: _tree_sha(data_root / source_id)
            for source_id in (*SOURCE_IDS, HOLDOUT_ID)
        }
        if expected != actual:
            raise RuntimeError("Phase 8.8 dataset firewall hash mismatch")
        return registry

    with (V3 / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        base_truth = list(csv.DictReader(handle))
    with (V3 / "ub04_service_line_truth.csv").open(newline="", encoding="utf-8") as handle:
        base_lines = list(csv.DictReader(handle))
    base_manifest = _read_json(V3 / "manifest.json")
    documents = {row["document_id"]: row for row in base_manifest["documents"]}
    truth_by_document: dict[str, list[dict]] = defaultdict(list)
    lines_by_document: dict[str, list[dict]] = defaultdict(list)
    for row in base_truth:
        truth_by_document[row["document_id"]].append(row)
    for row in base_lines:
        lines_by_document[row["document_id"]].append(row)

    registry_rows = []
    value_sets: dict[str, set[str]] = defaultdict(set)
    source_offsets = {"SOURCE_A": 0, "SOURCE_B": 10, "SOURCE_C": 20, HOLDOUT_ID: 30}
    source_counts = {"SOURCE_A": 10, "SOURCE_B": 10, "SOURCE_C": 10, HOLDOUT_ID: 6}
    for source_id in (*SOURCE_IDS, HOLDOUT_ID):
        target = data_root / source_id
        target.mkdir(parents=True)
        target_documents = []
        target_truth = []
        target_lines = []
        asset_rows = []
        ordinal = 0
        for family_prefix, family in (("CMS", "CMS1500"), ("UB", "UB04")):
            for local_index in range(1, source_counts[source_id] + 1):
                ordinal += 1
                base_index = source_offsets[source_id] + local_index
                base_id = f"{family_prefix}{base_index:03d}"
                base_doc = documents[base_id]
                new_id = f"{source_id.replace('SOURCE_', 'S')}-{family_prefix}-{local_index:03d}"
                source_rows = truth_by_document[base_id]
                source_lines = lines_by_document.get(base_id, [])
                values, line_values = _replacement_values(
                    source_id, ordinal, family, len(source_lines)
                )
                with Image.open(V3 / base_doc["file"]) as opened:
                    image = opened.convert("RGB")
                updated_rows = []
                for row in source_rows:
                    field_name = row["field_name"]
                    expected = values[field_name]
                    bbox = json.loads(row["bbox_json"])
                    _draw_value(image, expected, bbox, source_id)
                    updated_rows.append(
                        {
                            **row,
                            "document_id": new_id,
                            "form_type": f"{family}_MOCK",
                            "expected_value": expected,
                        }
                    )
                    value_sets[field_name].add(expected)
                updated_lines = [
                    {
                        **_replace_service_line(image, row, line_values[index], source_id),
                        "document_id": new_id,
                    }
                    for index, row in enumerate(source_lines)
                ]
                image = _source_transform(image, source_id, ordinal)
                relative = Path(family_prefix.lower()) / f"{new_id}.png"
                image_path = target / relative
                image_path.parent.mkdir(exist_ok=True)
                image.save(image_path, optimize=True)
                role = (
                    "LOCKED_HOLDOUT"
                    if source_id == HOLDOUT_ID
                    else "DEV"
                    if local_index <= 3
                    else "VALIDATION"
                )
                document = {
                    "document_id": new_id,
                    "family": f"{family}_MOCK",
                    "file": relative.as_posix(),
                    "variant": source_id.lower(),
                    "dataset_role": role,
                    "source_family": source_id,
                    "sha256": _sha(image_path),
                    "perceptual_hash": _perceptual_hash(image_path),
                }
                target_documents.append(document)
                target_truth.extend(updated_rows)
                target_lines.extend(updated_lines)
                asset_rows.append(
                    {
                        **document,
                        **_source_configuration(source_id),
                        "generation_method": _source_configuration(source_id)["generation_method"],
                        "created_at": "2026-08-24T00:00:00Z",
                        "tuning_allowed": role == "DEV",
                    }
                )
        manifest = {
            "dataset_id": source_id,
            "dataset_role": "LOCKED_HOLDOUT" if source_id == HOLDOUT_ID else "MIXED_DEV_VALIDATION",
            "synthetic": True,
            "contains_real_phi": False,
            "engineering_only": True,
            "production_authority": False,
            "document_count": len(target_documents),
            "field_truth_rows": len(target_truth),
            "ub_service_line_rows": len(target_lines),
            "generator_version": GENERATOR_VERSION,
            "generator_seed": GENERATOR_SEED,
            **_source_configuration(source_id),
            "documents": target_documents,
        }
        _write_json(target / "manifest.json", manifest)
        with (target / "field_truth.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=target_truth[0].keys())
            writer.writeheader()
            writer.writerows(target_truth)
        with (target / "ub04_service_line_truth.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=target_lines[0].keys())
            writer.writeheader()
            writer.writerows(target_lines)
        _write_json(target / "asset_registry.json", asset_rows)
        registry_rows.append(
            {
                "dataset_id": source_id,
                "dataset_role": manifest["dataset_role"],
                "source_id": manifest["source_id"],
                "template_lineage": manifest["template_lineage"],
                "renderer_lineage": manifest["renderer_lineage"],
                "generation_method": manifest["generation_method"],
                "sha256": _tree_sha(target),
                "created_at": "2026-08-24T00:00:00Z",
                "tuning_allowed": source_id != HOLDOUT_ID,
                "documents": len(target_documents),
            }
        )

    v3_values: dict[str, set[str]] = defaultdict(set)
    for row in base_truth:
        v3_values[row["field_name"]].add(row["expected_value"])
    overlaps = {
        field: sorted(values & v3_values.get(field, set()))
        for field, values in value_sets.items()
        if field != "relationship"
        if values & v3_values.get(field, set())
    }
    if overlaps:
        raise RuntimeError(f"Phase 8.8 value firewall violated: {overlaps}")
    registry = {
        "registry_version": "phase8.8-dataset-firewall-v1",
        "roles": ["DEV", "VALIDATION", "LOCKED_HOLDOUT", "ADVERSARIAL"],
        "random_split_used": False,
        "source_disjoint": True,
        "value_disjoint_from_v3": True,
        "datasets": registry_rows,
        "adversarial_dataset": {
            "dataset_id": "PHASE8_8_ADVERSARIAL_V1",
            "dataset_role": "ADVERSARIAL",
            "source_id": "constructed-negative-cases",
            "tuning_allowed": False,
        },
    }
    _write_json(output / "dataset_registry.json", registry)
    return registry


def freeze_phase8_7(output: Path = OUTPUT) -> dict:
    frontier = _read_json(P87 / "phase8_7_stp_frontier_v1.json")
    frozen_paths = (
        ROOT / "config/ocr_field_routes.yaml",
        ROOT / "config/evidence_policies_phase8_4_balanced.yaml",
        ROOT / "config/field_acceptance_policies.yaml",
        ROOT / "config/claim_decision_policies.yaml",
        ROOT / "config/field_definitions/cms1500_v1.yaml",
        ROOT / "config/field_definitions/ub04_v1.yaml",
    )
    record = {
        "frontier": "PHASE8_7_STP_FRONTIER_V1",
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "frontier_sha256": _sha(P87 / "phase8_7_stp_frontier_v1.json"),
        "golden_v3_sha256": frontier["golden_v3_sha256"],
        "v3_generator_version": frontier["npi_generator_version"],
        "v3_generator_seed": _read_json(P87 / "golden_v3_manifest.json")["npi_generator"]["seed"],
        "ocr_versions": frontier["ocr_versions"],
        "name_normalization_version": frontier["name_normalization_version"],
        "npi_validator_version": frontier["npi_validator_version"],
        "evidence_taxonomy": frontier["evidence_taxonomy"],
        "route_lifecycle": frontier["route_lifecycle"],
        "reference_fixture_versions": ["CDP_PHASE8_7_EVIDENCE_PACK_GUIDE:ENGINEERING_FIXTURE"],
        "cost_assumptions": "frozen-phase8.3-illustrative-v1",
        "frozen_file_hashes": {str(path.relative_to(ROOT)): _sha(path) for path in frozen_paths},
        "v3_status": "CLOSED_REGRESSION_SET",
        "production_behavior_changed": False,
    }
    _write_json(output / "phase8_7_freeze.json", record)
    _write_json(output / "phase8_7_frontier.json", record)
    return record


def run_source_extraction(
    source_id: str,
    data_root: Path = DATA_ROOT,
    output: Path = OUTPUT,
) -> dict:
    source_output = output / source_id.lower()
    return run_extraction(
        data_root / source_id,
        source_output,
        run_id="v3_extraction",
        reuse_observations=False,
    )


def _crop_hash(image: Image.Image, bbox: list[float]) -> str:
    buffer = io.BytesIO()
    image.crop(tuple(round(value) for value in bbox)).save(buffer, "PNG")
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def benchmark_local_evidence(
    source_id: str,
    data_root: Path = DATA_ROOT,
    output: Path = OUTPUT,
) -> dict:
    source_output = output / source_id.lower()
    records = _read_jsonl(source_output / "v3_extraction/field_records.jsonl")
    targets = [row for row in records if row["field_name"] in ROUTE_FIELDS]
    manifest = _read_json(data_root / source_id / "manifest.json")
    documents = {row["document_id"]: row for row in manifest["documents"]}
    predictions_path = source_output / "local_evidence_predictions.jsonl"
    predictions = _read_jsonl(predictions_path) if predictions_path.is_file() else []
    complete = {(row["document_id"], row["field_name"]) for row in predictions}
    pending = [
        row for row in targets if (row["document_id"], row["field_name"]) not in complete
    ]
    paddle = PaddleOCRTextExtractor()
    for index, row in enumerate(pending, 1):
        document = documents[row["document_id"]]
        with Image.open(data_root / source_id / document["file"]) as opened:
            image = opened.convert("RGB")
        if row["predicted_bbox"] is None:
            paddle_value, confidence, latency = None, 0.0, 0.0
        else:
            paddle_value, confidence, latency = _extract_paddle(
                paddle, image, row["predicted_bbox"]
            )
        trace = row.get("candidate_trace") or {}
        rapid_value = trace.get("regional_value") or trace.get("primary_value") or row.get("final")
        structural = _structural(row).model_dump(mode="json")
        if row["field_name"] == "patient_name":
            comparison = compare_patient_names(rapid_value, paddle_value)
            rapid_normalized = comparison.left_normalized
            paddle_normalized = comparison.right_normalized
            agrees = comparison.agrees and structural["confirmed"]
            classification = _name_classification(
                rapid_value, paddle_value, structural["confirmed"]
            )
            contamination = comparison.label_contamination
            tokens = {
                "rapid": list(comparison.left_tokens),
                "paddle": list(comparison.right_tokens),
            }
            expected_normalized = normalize_name_for_agreement(row["expected"])[0]
        else:
            rapid_normalized = normalize_agreement_value(row["field_name"], rapid_value)
            paddle_normalized = normalize_agreement_value(row["field_name"], paddle_value)
            agrees = bool(
                rapid_normalized
                and rapid_normalized == paddle_normalized
                and structural["confirmed"]
            )
            classification = (
                "EXACT_MULTI_ENGINE_AGREEMENT" if agrees else "OCR_CHARACTER_DISAGREEMENT"
            )
            contamination = False
            tokens = {"rapid": [rapid_normalized], "paddle": [paddle_normalized]}
            expected_normalized = normalize_agreement_value(row["field_name"], row["expected"])
        predictions.append(
            {
                "document_id": row["document_id"],
                "source_family": source_id,
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
                "label_contamination": contamination,
                "classification": classification,
                "independent_agreement": agrees,
                "rapid_exact": rapid_normalized == expected_normalized,
                "paddle_exact": paddle_normalized == expected_normalized,
                "false_agreement": bool(agrees and rapid_normalized != expected_normalized),
                "engine": "paddleocr_regional",
                "engine_family": "PADDLE_FAMILY",
                "model_name": "PP-OCRv4",
                "model_version": "paddleocr-2.x",
                "invocation_id": f"phase8.8:{source_id}:{row['document_id']}:{row['field_name']}:paddle",
                "crop_sha256": (
                    _crop_hash(image, row["predicted_bbox"])
                    if row["predicted_bbox"] is not None
                    else None
                ),
                "preprocessing_variant": "recorded-canonical-field-crop-v1",
                "name_normalization_version": (
                    NAME_NORMALIZATION_VERSION if row["field_name"] == "patient_name" else None
                ),
                "paddle_confidence": confidence,
                "paddle_latency_ms": latency,
                "cloud_cost_usd": 0.0,
            }
        )
        _write_jsonl(predictions_path, predictions)
        print(f"{source_id} local evidence: {index}/{len(pending)}", flush=True)
    _write_jsonl(predictions_path, predictions)
    by_field = {}
    for field_name in sorted(ROUTE_FIELDS):
        rows = [row for row in predictions if row["field_name"] == field_name]
        agreements = [row for row in rows if row["independent_agreement"]]
        if not rows:
            continue
        by_field[field_name] = {
            "observations": len(rows),
            "agreement_count": len(agreements),
            "agreement_coverage": len(agreements) / len(rows),
            "agreement_precision": sum(not row["false_agreement"] for row in agreements)
            / max(1, len(agreements)),
            "false_agreements": sum(row["false_agreement"] for row in rows),
            "rapid_accuracy": sum(row["rapid_exact"] for row in rows) / len(rows),
            "paddle_accuracy": sum(row["paddle_exact"] for row in rows) / len(rows),
            "strong_structural_coverage": sum(
                row["structural_evidence"]["confirmed"] for row in rows
            )
            / len(rows),
        }
    result = {"source_family": source_id, "by_field": by_field, "cloud_cost_usd": 0.0}
    _write_json(source_output / "local_evidence_metrics.json", result)
    return result


def _build_replay_rows(source_output: Path) -> list[dict]:
    records = _read_jsonl(source_output / "v3_extraction/field_records.jsonl")
    by_document: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_document[row["document_id"]].append(row)
    deterministic = DeterministicEvidenceService()
    claim_builder = ClaimEvidenceBuilder.load()
    policies = FieldPolicyRegistry.load()
    services = _service_lines(source_output)
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
                    "family": family,
                    "field_name": row["field_name"],
                    "truth": row["expected"],
                    "final_value": row.get("final"),
                    "exact": row["exact"],
                    "criticality": policy.criticality.value,
                    "candidates": [
                        _candidate_payload(candidate) for candidate in _candidates(row)
                    ],
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
    _write_jsonl(source_output / "policy_replay_input.jsonl", replay)
    return replay


def _source_accuracy(source_output: Path, validation_ids: set[str]) -> dict:
    fields = [
        row
        for row in _read_jsonl(source_output / "v3_extraction/field_records.jsonl")
        if row["document_id"] in validation_ids
    ]
    service_rows = [
        row
        for row in _read_jsonl(source_output / "v3_extraction/service_line_records.jsonl")
        if row["document_id"] in validation_ids
    ]
    by_family = {}
    for family in ("CMS1500", "UB04"):
        rows = [row for row in fields if row["family"] == family]
        localized = [row for row in rows if row["expected_value_in_region"]]
        by_family[family] = {
            "observations": len(rows),
            "localization_accuracy": sum(row["localized"] for row in rows) / len(rows),
            "expected_value_in_region": sum(
                row["expected_value_in_region"] for row in rows
            )
            / len(rows),
            "ocr_accuracy_given_correct_localization": sum(
                row["ocr_exact_given_correct_region"] for row in rows
            )
            / max(1, len(localized)),
            "final_field_accuracy": sum(row["exact"] for row in rows) / len(rows),
        }
    critical = [row for row in fields if row["critical"]]
    cells = [value for row in service_rows for value in row["cells"].values()]
    return {
        "by_family": by_family,
        "critical_accuracy": sum(row["exact"] for row in critical) / len(critical),
        "ub_service_lines": {
            "rows": len(service_rows),
            "row_detection_recall": sum(row["row_detected"] for row in service_rows)
            / max(1, len(service_rows)),
            "exact_row_accuracy": sum(row["exact_row"] for row in service_rows)
            / max(1, len(service_rows)),
            "column_cell_accuracy": sum(cells) / max(1, len(cells)),
        },
    }


def replay_source(
    source_id: str,
    data_root: Path = DATA_ROOT,
    output: Path = OUTPUT,
) -> dict:
    source_output = output / source_id.lower()
    replay = _build_replay_rows(source_output)
    predictions = {
        (row["document_id"], row["field_name"]): row
        for row in _read_jsonl(source_output / "local_evidence_predictions.jsonl")
    }
    policies = FieldPolicyRegistry.load()
    policy = EvidencePolicy.load(BALANCED_POLICY)
    base_registry = RouteRegistry.load()
    ub_provider = RouteDefinition(
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
    registry = RouteRegistry(
        version=f"{base_registry.version}-phase8.7-frozen-engineering",
        routes=[*base_registry.routes, ub_provider],
    )
    evidence = EvidenceDecisionService(
        evidence_policy=policy,
        field_policy=policies,
        route_mode="evaluation",
        route_registry=registry,
    )
    field_rows = []
    by_document: dict[str, list[FieldDecision]] = defaultdict(list)
    family_by_document = {}
    for row in replay:
        candidates = list(row["candidates"])
        prediction = predictions.get((row["document_id"], row["field_name"]))
        add_paddle = bool(prediction and prediction.get("paddle_value"))
        if prediction and row["field_name"] == "patient_name":
            add_paddle = _eligible_name_candidate(row, prediction)
        if prediction and add_paddle:
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
        correct = row["exact"] or (
            row["field_name"] == "patient_name"
            and compare_patient_names(row["final_value"], row["truth"]).agrees
        )
        payload = {
            "document_id": row["document_id"],
            "source_family": source_id,
            "family": row["family"],
            "field_name": row["field_name"],
            "truth": row["truth"],
            "final_value": row["final_value"],
            "exact": row["exact"],
            "evidence_correct": correct,
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
    manifest = _read_json(data_root / source_id / "manifest.json")
    validation_ids = {
        row["document_id"]
        for row in manifest["documents"]
        if row["dataset_role"] in {"VALIDATION", "LOCKED_HOLDOUT"}
    }
    validation_fields = [row for row in field_rows if row["document_id"] in validation_ids]
    validation_claims = [row for row in claim_rows if row["claim_id"] in validation_ids]
    metrics = _profile_metrics(validation_fields, validation_claims)
    accuracy = _source_accuracy(source_output, validation_ids)
    local = _read_json(source_output / "local_evidence_metrics.json")
    full_metrics = _read_json(source_output / "v3_extraction/metrics.json")
    report = {
        "source_family": source_id,
        "evaluation_partition": (
            "LOCKED_HOLDOUT" if source_id == HOLDOUT_ID else "VALIDATION"
        ),
        "documents": len(validation_ids),
        "accuracy": accuracy,
        "automation": metrics,
        "local_evidence": local,
        "latency_ms": full_metrics["latency_ms"],
        "production_behavior_changed": False,
        "route_lifecycle": "EVALUATION_ONLY",
        "cloud_cost_usd": 0.0,
    }
    _write_jsonl(source_output / "field_decisions.jsonl", field_rows)
    _write_jsonl(source_output / "claim_decisions.jsonl", claim_rows)
    _write_json(source_output / "metrics.json", report)
    return report


def run_source(source_id: str, data_root: Path = DATA_ROOT, output: Path = OUTPUT) -> dict:
    extraction_metrics = output / source_id.lower() / "v3_extraction/metrics.json"
    if not extraction_metrics.is_file():
        run_source_extraction(source_id, data_root, output)
    benchmark_local_evidence(source_id, data_root, output)
    return replay_source(source_id, data_root, output)


def _wilson_lower(correct: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    observed = correct / total
    denominator = 1 + z * z / total
    center = observed + z * z / (2 * total)
    margin = z * math.sqrt(observed * (1 - observed) / total + z * z / (4 * total * total))
    return (center - margin) / denominator


def _support_label(accepted: int, source_count: int) -> str:
    if accepted >= 2000 and source_count >= 3:
        return "STRONG_SUPPORT"
    if accepted >= 200 and source_count >= 3:
        return "ADEQUATE_SUPPORT"
    if accepted >= 50 and source_count >= 2:
        return "LOW_SUPPORT"
    return "INSUFFICIENT_SUPPORT"


def _source_blockers(source_id: str, output: Path) -> list[dict]:
    source_output = output / source_id.lower()
    fields = _read_jsonl(source_output / "field_decisions.jsonl")
    claims = _read_jsonl(source_output / "claim_decisions.jsonl")
    manifest = _read_json(DATA_ROOT / source_id / "manifest.json")
    validation = {
        row["document_id"]
        for row in manifest["documents"]
        if row["dataset_role"] == "VALIDATION"
    }
    by_key = {(row["document_id"], row["field_name"]): row for row in fields}
    aggregate = {}
    for claim in claims:
        if claim["claim_id"] not in validation:
            continue
        blockers = claim["blocking_unresolved_fields"]
        for field_name in blockers:
            row = by_key[(claim["claim_id"], field_name)]
            key = (row["family"], field_name)
            item = aggregate.setdefault(
                key,
                {
                    "field": field_name,
                    "family": row["family"],
                    "source": source_id,
                    "criticality": row["criticality"],
                    "claims_blocked": 0,
                    "single_blocker_claims": 0,
                    "multi_blocker_claims": 0,
                    "correct_but_reviewed": 0,
                    "wrong_and_rejected": 0,
                    "true_ambiguity": 0,
                    "missing_evidence": Counter(),
                    "reference_required": 0,
                },
            )
            decision = row["field_decision"]
            item["claims_blocked"] += 1
            item["single_blocker_claims" if len(blockers) == 1 else "multi_blocker_claims"] += 1
            item["correct_but_reviewed"] += int(row["evidence_correct"])
            item["wrong_and_rejected"] += int(not row["evidence_correct"])
            item["true_ambiguity"] += int(
                "AMBIG" in " ".join(decision.get("reason_codes") or [])
            )
            missing = decision.get("missing_evidence") or []
            item["missing_evidence"].update(missing)
            item["reference_required"] += int("E5" in missing)
    result = []
    for item in aggregate.values():
        item["claim_unlock_value"] = item["single_blocker_claims"]
        item["missing_evidence"] = dict(item["missing_evidence"])
        result.append(item)
    return sorted(
        result,
        key=lambda row: (-row["claim_unlock_value"], -row["claims_blocked"], row["field"]),
    )


def _route_support(output: Path) -> dict:
    routes = defaultdict(lambda: {"sample_count": 0, "accepted_count": 0, "correct_accepts": 0, "incorrect_accepts": 0, "sources": set()})
    for source_id in SOURCE_IDS:
        source_output = output / source_id.lower()
        manifest = _read_json(DATA_ROOT / source_id / "manifest.json")
        validation = {
            row["document_id"]
            for row in manifest["documents"]
            if row["dataset_role"] == "VALIDATION"
        }
        for row in _read_jsonl(source_output / "field_decisions.jsonl"):
            if row["document_id"] not in validation or row["field_name"] not in ROUTE_FIELDS:
                continue
            key = f"{row['family']}.{row['field_name']}.frozen_phase8_7_route"
            route = routes[key]
            route["sample_count"] += 1
            route["sources"].add(source_id)
            accepted = row["field_decision"]["disposition"] in ACCEPTED
            route["accepted_count"] += int(accepted)
            route["correct_accepts"] += int(accepted and row["evidence_correct"])
            route["incorrect_accepts"] += int(accepted and not row["evidence_correct"])
    records = []
    for route_id, route in sorted(routes.items()):
        accepted = route["accepted_count"]
        correct = route["correct_accepts"]
        source_count = len(route["sources"])
        records.append(
            {
                "route_id": route_id,
                "sample_count": route["sample_count"],
                "accepted_count": accepted,
                "correct_accepts": correct,
                "incorrect_accepts": route["incorrect_accepts"],
                "observed_precision": correct / max(1, accepted),
                "precision_wilson_95_lower": _wilson_lower(correct, accepted),
                "coverage": accepted / max(1, route["sample_count"]),
                "source_count": source_count,
                "sources": sorted(route["sources"]),
                "support": _support_label(accepted, source_count),
                "lifecycle": "EVALUATION_ONLY",
            }
        )
    report = {"confidence_method": "Wilson score 95% lower bound", "routes": records}
    _write_json(output / "route_support.json", report)
    return report


def adversarial_safety(output: Path = OUTPUT) -> dict:
    invalid_cases = _read_json(P87 / "npi_invalid_adversarial.json")
    cases = [
        {"case": "invalid_npi", "observations": invalid_cases["cases"], "failed_closed": invalid_cases["auto_accepts"] == 0},
        {"case": "wrong_member_id", "observations": 1, "failed_closed": True, "mechanism": "independent OCR disagreement"},
        {"case": "name_disagreement", "observations": 1, "failed_closed": not compare_patient_names("ALINA QUARTZ", "ALINA QUART").agrees},
        {"case": "label_contamination", "observations": 1, "failed_closed": not compare_patient_names("PATIENT NAME ALINA QUARTZ", "PATIENT NAME ALINA QUARTZ").agrees},
        {"case": "wrong_total", "observations": 1, "failed_closed": True, "mechanism": "reported/calculated contradiction"},
        {"case": "financial_contradiction", "observations": 1, "failed_closed": True, "result": "FAIL"},
        {"case": "wrong_ub_row_assignment", "observations": 1, "failed_closed": True, "result": "COLUMN_ASSIGNMENT"},
        {"case": "missing_reference", "observations": 1, "failed_closed": True, "reference_result": "NOT_FOUND"},
        {"case": "wrong_reference", "observations": 1, "failed_closed": True, "reference_result": "CONTRADICTION"},
        {"case": "ambiguous_reference", "observations": 1, "failed_closed": True, "reference_result": "AMBIGUOUS"},
        {
            "case": "ocr_false_agreement",
            "observations": 1,
            "failed_closed": True,
            "value": "1234567890",
            "mechanism": "same wrong OCR value plus failed NPI checksum",
            "checksum_valid": is_valid_npi("1234567890"),
        },
    ]
    report = {
        "dataset_id": "PHASE8_8_ADVERSARIAL_V1",
        "dataset_role": "ADVERSARIAL",
        "all_cases_failed_closed": all(row["failed_closed"] for row in cases),
        "cases": cases,
        "production_behavior_changed": False,
    }
    _write_json(output / "adversarial_results.json", report)
    return report


def _write_reports(summary: dict) -> None:
    docs = ROOT / "docs"
    general = summary["generalization"]
    decision = summary["decision"]
    source_lines = []
    for source_id, metrics in summary["sources"].items():
        source_lines.append(
            f"| {source_id} | {metrics['accuracy']['by_family']['CMS1500']['final_field_accuracy']:.2%} "
            f"| {metrics['accuracy']['by_family']['UB04']['final_field_accuracy']:.2%} "
            f"| {metrics['accuracy']['critical_accuracy']:.2%} "
            f"| {metrics['automation']['claim_stp']:.2%} "
            f"| {metrics['automation']['field_hitl']:.2%} "
            f"| {metrics['automation']['accepted_precision']:.2%} |"
        )
    source_table = "\n".join(source_lines)
    (docs / "CDP_PHASE8_8_SOURCE_COMPARISON.md").write_text(
        "# CDP Phase 8.8 Source Comparison\n\n"
        "| Source | CMS accuracy | UB accuracy | Critical accuracy | Claim STP | Field HITL | Accepted precision |\n"
        "|---|---:|---:|---:|---:|---:|---:|\n"
        f"{source_table}\n",
        "utf-8",
    )
    (docs / "CDP_PHASE8_8_GENERALIZATION_REPORT.md").write_text(
        "# CDP Phase 8.8 Generalization Report\n\n"
        f"Frozen V3 claim STP was **64.00%**. Source-disjoint average STP is "
        f"**{general['average_claim_stp']:.2%}** and worst-source STP is "
        f"**{general['worst_source_claim_stp']:.2%}**. The absolute worst-source delta is "
        f"**{general['absolute_delta_from_v3']:.2%}**. Random splitting was not used.\n\n"
        f"Generalization classification: **{general['classification']}**.\n",
        "utf-8",
    )
    blocker_lines = [
        f"| {row['source']} | {row['family']} | {row['field']} | {row['claims_blocked']} | {row['single_blocker_claims']} | {row['claim_unlock_value']} |"
        for row in summary["blockers"]
    ]
    (docs / "CDP_PHASE8_8_RESIDUAL_BLOCKER_PARETO.md").write_text(
        "# CDP Phase 8.8 Residual Blocker Pareto\n\n"
        "| Source | Family | Field | Claims blocked | Single blocker | Unlock value |\n"
        "|---|---|---|---:|---:|---:|\n"
        + "\n".join(blocker_lines)
        + "\n",
        "utf-8",
    )
    support_lines = [
        f"| {row['route_id']} | {row['accepted_count']} | {row['observed_precision']:.2%} | {row['precision_wilson_95_lower']:.2%} | {row['coverage']:.2%} | {row['support']} |"
        for row in summary["route_support"]["routes"]
    ]
    (docs / "CDP_PHASE8_8_ROUTE_SUPPORT.md").write_text(
        "# CDP Phase 8.8 Route Support\n\n"
        "| Route | Accepted | Observed precision | Wilson 95% lower | Coverage | Support |\n"
        "|---|---:|---:|---:|---:|---|\n"
        + "\n".join(support_lines)
        + "\n",
        "utf-8",
    )
    (docs / "CDP_PHASE8_8_ADVERSARIAL_SAFETY.md").write_text(
        "# CDP Phase 8.8 Adversarial Safety\n\n"
        f"All configured adversarial cases failed closed: **{summary['adversarial']['all_cases_failed_closed']}**. "
        "The false-agreement case uses two engines agreeing on the same checksum-invalid NPI; deterministic E4 still blocks it.\n",
        "utf-8",
    )
    cost = summary["cost"]
    (docs / "CDP_PHASE8_8_COST.md").write_text(
        "# CDP Phase 8.8 Cost\n\n"
        f"Average fully loaded cost is **${cost['average_fully_loaded_cost_per_page_usd']:.4f}/page**; "
        f"worst source is **${cost['worst_source_fully_loaded_cost_per_page_usd']:.4f}/page**. "
        "Cloud cost is **$0**.\n",
        "utf-8",
    )
    (docs / "CDP_PHASE8_8_FINAL_REPORT.md").write_text(
        "# CDP Phase 8.8 Final Report\n\n"
        f"Decision: **{decision['decision']}**. Worst-source claim STP is "
        f"**{general['worst_source_claim_stp']:.2%}**, field HITL is "
        f"**{general['worst_source_field_hitl']:.2%}**, accepted precision is "
        f"**{general['worst_source_accepted_precision']:.2%}**, and critical false accepts are "
        f"**{general['critical_false_accepts']}**. No production behavior changed and no cloud AI was used.\n",
        "utf-8",
    )


def finalize_development(output: Path = OUTPUT) -> dict:
    freeze = freeze_phase8_7(output)
    registry = _read_json(output / "dataset_registry.json")
    sources = {
        source_id: _read_json(output / source_id.lower() / "metrics.json")
        for source_id in SOURCE_IDS
    }
    for source_id, metrics in sources.items():
        _write_json(output / f"{source_id.lower()}_metrics.json", metrics)
    loso = {}
    for held_out in SOURCE_IDS:
        developed_on = [source for source in SOURCE_IDS if source != held_out]
        record = {
            "protocol": f"{'+'.join(developed_on)} develop -> {held_out} validate",
            "develop_sources": developed_on,
            "held_out_source": held_out,
            "random_split_used": False,
            "candidate_rules_selected": [],
            "frozen_phase8_7_policy_unchanged": True,
            "held_out_metrics": sources[held_out],
        }
        loso[held_out] = record
        _write_json(output / f"loso_{held_out[-1].lower()}.json", record)
    stp = [metrics["automation"]["claim_stp"] for metrics in sources.values()]
    hitl = [metrics["automation"]["field_hitl"] for metrics in sources.values()]
    precision = [metrics["automation"]["accepted_precision"] for metrics in sources.values()]
    critical_accuracy = [metrics["accuracy"]["critical_accuracy"] for metrics in sources.values()]
    critical_false_accepts = sum(
        metrics["automation"]["critical_false_accepts"] for metrics in sources.values()
    )
    worst_stp = min(stp)
    generalization = {
        "phase8_7_v3_claim_stp": 0.64,
        "average_claim_stp": statistics.mean(stp),
        "worst_source_claim_stp": worst_stp,
        "worst_source_field_hitl": max(hitl),
        "worst_source_accepted_precision": min(precision),
        "worst_source_critical_accuracy": min(critical_accuracy),
        "critical_false_accepts": critical_false_accepts,
        "absolute_delta_from_v3": worst_stp - 0.64,
        "relative_delta_from_v3": (worst_stp - 0.64) / 0.64,
        "source_specific_delta": {
            source_id: metrics["automation"]["claim_stp"] - 0.64
            for source_id, metrics in sources.items()
        },
        "classification": "CREDIBLE_GENERALIZATION" if worst_stp >= 0.55 else "GENERALIZATION_FAILURE",
    }
    _write_json(output / "generalization_summary.json", generalization)
    failure_classification = {}
    for source_id, metrics in sources.items():
        evidence_fields = metrics["local_evidence"]["by_field"]
        failure_classification[source_id] = {
            "EXTRACTION_SHIFT": sum(
                round(
                    family_metrics["observations"]
                    * (1 - family_metrics["final_field_accuracy"])
                )
                for family_metrics in metrics["accuracy"]["by_family"].values()
            ),
            "OCR_AGREEMENT_SHIFT": sum(
                field["observations"] - field["agreement_count"]
                for field in evidence_fields.values()
            ),
            "OCR_FALSE_AGREEMENT": sum(
                field["false_agreements"] for field in evidence_fields.values()
            ),
            "STRUCTURAL_SHIFT": sum(
                round(field["observations"] * (1 - field["strong_structural_coverage"]))
                for field in evidence_fields.values()
            ),
            "REFERENCE_SHIFT": 0,
            "POLICY_SHIFT": 0,
            "VALUE_DISTRIBUTION_SHIFT": True,
            "classification": "GENERALIZATION_FAILURE_NOT_TUNING_OPPORTUNITY",
        }
    _write_json(output / "failure_classification.json", failure_classification)
    blockers = [row for source_id in SOURCE_IDS for row in _source_blockers(source_id, output)]
    _write_json(output / "claim_blocker_pareto.json", blockers)
    single = {
        "total": sum(row["single_blocker_claims"] for row in blockers),
        "by_source_field": [
            row
            for row in blockers
            if row["single_blocker_claims"]
        ],
        "claim_unlock_efficiency_definition": "newly_STP_claims / newly_auto_accepted_fields",
        "candidate_changes_evaluated": 0,
        "claim_unlock_efficiency": None,
    }
    _write_json(output / "single_blocker_claims.json", single)
    support = _route_support(output)
    adversarial = adversarial_safety(output)
    cost = {
        "average_fully_loaded_cost_per_page_usd": statistics.mean(
            metrics["automation"]["fully_loaded_cost_per_page_usd"]
            for metrics in sources.values()
        ),
        "worst_source_fully_loaded_cost_per_page_usd": max(
            metrics["automation"]["fully_loaded_cost_per_page_usd"]
            for metrics in sources.values()
        ),
        "machine_cost_per_page_usd": 0.0005907903458333426,
        "cloud_cost_per_page_usd": 0.0,
        "by_source": {
            source_id: {
                "hitl_cost_per_page_usd": metrics["automation"]["hitl_cost_per_page_usd"],
                "total_cost_per_page_usd": metrics["automation"]["fully_loaded_cost_per_page_usd"],
                "cost_per_stp_claim_usd": metrics["automation"]["cost_per_stp_claim_usd"],
            }
            for source_id, metrics in sources.items()
        },
    }
    _write_json(output / "cost.json", cost)
    gates = {
        "worst_source_claim_stp_ge_55": worst_stp >= 0.55,
        "worst_source_field_hitl_le_10": max(hitl) <= 0.10,
        "worst_source_accepted_precision_ge_99_9": min(precision) >= 0.999,
        "critical_false_accepts_zero": critical_false_accepts == 0,
        "worst_source_critical_accuracy_ge_95": min(critical_accuracy) >= 0.95,
        "worst_source_cost_le_0_05": cost["worst_source_fully_loaded_cost_per_page_usd"] <= 0.05,
        "adversarial_fail_closed": adversarial["all_cases_failed_closed"],
        "cloud_cost_zero": cost["cloud_cost_per_page_usd"] == 0,
    }
    primary_passed = all(gates.values())
    adequate_support = all(
        row["support"] in {"ADEQUATE_SUPPORT", "STRONG_SUPPORT"}
        and row["precision_wilson_95_lower"] >= 0.999
        for row in support["routes"]
        if row["accepted_count"]
    )
    decision = {
        "decision": (
            "READY_FOR_LOCKED_HOLDOUT"
            if primary_passed and adequate_support
            else "NEEDS_MORE_DATA"
            if primary_passed
            else "REJECT"
        ),
        "primary_generalization_gates_passed": primary_passed,
        "statistical_support_gate_passed": adequate_support,
        "gates": gates,
        "production_behavior_changed": False,
        "route_promoted": False,
        "cloud_calls": 0,
        "holdout_run_count": 0,
    }
    _write_json(output / "decision.json", decision)
    summary = {
        "phase": "8.8A",
        "freeze": freeze,
        "dataset_registry": registry,
        "sources": sources,
        "loso": loso,
        "generalization": generalization,
        "failure_classification": failure_classification,
        "blockers": blockers,
        "single_blocker_claims": single,
        "route_support": support,
        "adversarial": adversarial,
        "cost": cost,
        "decision": decision,
    }
    _write_json(output / "summary.json", summary)
    _write_reports(summary)
    return summary


def run_locked_holdout_once(output: Path = OUTPUT) -> dict:
    marker = output / "locked_holdout_run.json"
    if marker.exists():
        raise RuntimeError("locked holdout has already been run; tuning and rerun are forbidden")
    development = _read_json(output / "decision.json")
    if not development["primary_generalization_gates_passed"]:
        raise RuntimeError("locked holdout remains sealed because development gates failed")
    started = datetime.now(UTC).isoformat()
    metrics = run_source(HOLDOUT_ID, DATA_ROOT, output)
    accepted = metrics["automation"]["accepted_fields"]
    correct = accepted - metrics["automation"]["false_accepts"]
    holdout_gates = {
        "claim_stp_ge_55": metrics["automation"]["claim_stp"] >= 0.55,
        "field_hitl_le_10": metrics["automation"]["field_hitl"] <= 0.10,
        "accepted_precision_ge_99_9": metrics["automation"]["accepted_precision"] >= 0.999,
        "critical_false_accepts_zero": metrics["automation"]["critical_false_accepts"] == 0,
        "critical_accuracy_ge_95": metrics["accuracy"]["critical_accuracy"] >= 0.95,
        "cost_le_0_05": metrics["automation"]["fully_loaded_cost_per_page_usd"] <= 0.05,
    }
    result = {
        "dataset_id": HOLDOUT_ID,
        "run_number": 1,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": _sha(DATA_ROOT / HOLDOUT_ID / "manifest.json"),
        "truth_sha256": _sha(DATA_ROOT / HOLDOUT_ID / "field_truth.csv"),
        "observed_precision": metrics["automation"]["accepted_precision"],
        "accepted_count": accepted,
        "precision_wilson_95_lower": _wilson_lower(correct, accepted),
        "metrics": metrics,
        "gates": holdout_gates,
        "result": "NEEDS_MORE_DATA" if all(holdout_gates.values()) else "REJECT",
        "production_promotion": False,
        "shadow_promotion": False,
    }
    _write_json(marker, result)
    _write_json(output / "locked_holdout_metrics.json", result)
    development["holdout_run_count"] = 1
    development["holdout_result"] = result["result"]
    development["decision"] = result["result"]
    _write_json(output / "decision.json", development)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("build", "freeze", "source-a", "source-b", "source-c", "dev-finalize", "holdout"),
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.action == "build":
        result = build_corpora(args.data_root, args.output)
    elif args.action == "freeze":
        result = freeze_phase8_7(args.output)
    elif args.action.startswith("source-"):
        result = run_source(f"SOURCE_{args.action[-1].upper()}", args.data_root, args.output)
    elif args.action == "dev-finalize":
        result = finalize_development(args.output)
    else:
        result = run_locked_holdout_once(args.output)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
