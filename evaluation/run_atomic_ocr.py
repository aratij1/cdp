"""Run the OCR cascade on validated, one-field-per-image template crops."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml
from PIL import Image, ImageOps

from evaluation.schemas import PredictedField, PredictionDataset, PredictionDocument
from packages.validation_rules.npi import is_valid_npi
from workers.cascade.cascading_ocr import CascadingOCR, OCRCandidatePass
from workers.cascade.tesseract_adapter import TesseractTextExtractor, for_field_type
from workers.page_detection.text_extraction import (
    PaddleOCRTextExtractor,
    RapidOCRTextExtractor,
    TextLine,
)

STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "NA",
}

FORM_VOCABULARY = {
    "ADMISSION",
    "BIRTH",
    "BIRTHDATE",
    "DATE",
    "FIRST",
    "INSURED",
    "LAST",
    "NAME",
    "PATIENT",
}

STREET_SUFFIXES = {
    "AVE",
    "AVENUE",
    "BLVD",
    "BOULEVARD",
    "CT",
    "COURT",
    "DR",
    "DRIVE",
    "HWY",
    "HIGHWAY",
    "LANE",
    "LN",
    "RD",
    "ROAD",
    "ST",
    "STREET",
}


def _engine_family(engine: str) -> str:
    if engine.startswith("tesseract"):
        return "TESSERACT_FAMILY"
    if engine == "rapidocr":
        return "RAPID_ONNX_FAMILY"
    if engine == "paddleocr":
        return "PADDLE_FAMILY"
    return engine.upper()


def prepare_field_image(field_name: str, image: Image.Image) -> Image.Image:
    """Upscale low-height crops and normalize contrast without using labels."""
    if field_name == "rel_code":
        return image.convert("RGB")
    normalized = ImageOps.autocontrast(image.convert("L"), cutoff=1).convert("RGB")
    factor = 3 if field_name in {"type_of_bill", "patient_state", "insured_state"} else 2
    if normalized.height >= 100:
        return normalized
    return normalized.resize(
        (normalized.width * factor, normalized.height * factor), Image.Resampling.LANCZOS
    )


def _joined(lines: list[TextLine]) -> tuple[str, float]:
    ordered = sorted(lines, key=lambda line: (line.y0, line.x0))
    text = " ".join(line.text for line in ordered).strip()
    confidence = sum(line.confidence for line in ordered) / len(ordered) if ordered else 0.0
    return text, confidence


def _person_part(text: str, first: bool) -> str:
    cleaned = re.sub(r"[^A-Za-z,.' -]", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    parts = [part.strip(" .").upper() for part in cleaned.split(",", 1)]
    if len(parts) == 1:
        words = parts[0].split()
        parts = [words[0], " ".join(words[1:])] if words else [""]
    selected = parts[1 if first else 0] if len(parts) > (1 if first else 0) else ""
    if first:
        # The source crop is intentionally OCRed once as a complete name.
        # The output contract stores middle name separately, so do not leak
        # subsequent tokens into patient_first.
        return selected.split()[0] if selected.split() else ""
    return selected


def normalize_atomic(field_name: str, raw: str) -> str:
    value = re.sub(r"\s+", " ", raw).strip()
    if field_name in {"patient_last", "patient_first"}:
        selected = _person_part(value, first=field_name == "patient_first")
        if selected in FORM_VOCABULARY or any(
            token in FORM_VOCABULARY for token in selected.split()
        ):
            return ""
        return selected
    if field_name in {"patient_addr1", "insured_addr1"}:
        tokens = re.findall(r"[A-Z0-9]+", value.upper())
        if (
            len(tokens) >= 3
            and tokens[0] in STREET_SUFFIXES
            and any(token[0].isdigit() for token in tokens[1:] if token)
        ):
            tokens = [*tokens[1:], tokens[0]]
        elif (
            len(tokens) >= 3
            and tokens[0][0].isdigit()
            and tokens[1] in STREET_SUFFIXES
        ):
            tokens = [tokens[0], *tokens[2:], tokens[1]]
        return " ".join(tokens)
    if field_name == "rel_code":
        upper = value.upper()
        for code, label in (("01", "SELF"), ("02", "SPOUSE"), ("03", "CHILD"), ("04", "OTHER")):
            if re.search(fr"{label}.{{0,8}}X|X.{{0,8}}{label}", upper):
                return code
        return ""
    if field_name.endswith("_state"):
        tokens = re.findall(r"\b[A-Z]{2}\b", value.upper())
        return next((token for token in tokens if token in STATES), "")
    if field_name.endswith("_zip"):
        digits = re.sub(r"\D", "", value)
        return digits if len(digits) in {5, 9} else ""
    if field_name in {"federal_tax_id", "provider_npi", "patient_control_number", "patient_dob"}:
        lengths = {
            "federal_tax_id": 9,
            "provider_npi": 10,
            "patient_control_number": 12,
            "patient_dob": 8,
        }
        groups = re.findall(r"\d+", value)
        digits = "".join(groups)
        length = lengths[field_name]
        candidates = [group for group in groups if len(group) == length]
        return candidates[0] if candidates else (digits if len(digits) == length else "")
    if field_name == "type_of_bill":
        digits = re.sub(r"\D", "", value)
        return digits[-3:] if len(digits) in {3, 4} else ""
    if field_name == "principal_diagnosis":
        match = re.search(r"\b([A-Z]\d{2,6}(?:\.\d+)?)\b", value.upper())
        return re.sub(r"[^A-Z0-9]", "", match.group(1)) if match else ""
    if field_name == "patient_sex":
        match = re.search(r"\b([MF])\b", value.upper())
        return match.group(1) if match else ""
    return re.sub(r"\s+", " ", value).strip(" ,").upper()


def _valid(field_name: str, value: str) -> bool:
    if not value:
        return False
    if field_name.endswith("_state"):
        return value in STATES
    if field_name.endswith("_zip"):
        return len(value) in {5, 9}
    lengths = {
        "federal_tax_id": 9,
        "provider_npi": 10,
        "patient_control_number": 12,
        "patient_dob": 8,
    }
    if field_name in lengths:
        syntax_ok = value.isdigit() and len(value) == lengths[field_name]
        return is_valid_npi(value) if field_name == "provider_npi" and syntax_ok else syntax_ok
    if field_name == "type_of_bill":
        return value.isdigit() and len(value) == 3
    if field_name == "principal_diagnosis":
        return bool(re.fullmatch(r"[A-Z]\d{2,6}", value))
    if field_name == "rel_code":
        return value in {"01", "02", "03", "04"}
    if field_name in {"patient_first", "patient_last"}:
        return bool(re.fullmatch(r"[A-Z][A-Z' -]+", value)) and len(
            re.sub(r"[^A-Z]", "", value)
        ) >= 2
    return len(value) <= 80


def _paddle_lines(
    extractor: PaddleOCRTextExtractor, image: Image.Image, cache: Path
) -> list[TextLine]:
    if cache.is_file():
        return [TextLine(**item) for item in json.loads(cache.read_text(encoding="utf-8"))]
    lines = extractor.extract(image)
    cache.write_text(json.dumps([line.__dict__ for line in lines]), encoding="utf-8")
    return lines


def _rapid_lines(
    extractor: RapidOCRTextExtractor, image: Image.Image, cache: Path
) -> list[TextLine]:
    if cache.is_file():
        return [TextLine(**item) for item in json.loads(cache.read_text(encoding="utf-8"))]
    lines = extractor.extract_region(image, 0, 0, image.width, image.height)
    cache.write_text(json.dumps([line.__dict__ for line in lines]), encoding="utf-8")
    return lines


def _safe_to_accept(
    field_name: str,
    value: str,
    critical: bool,
    independent_families: set[str],
    deterministic_pixel_evidence: bool = False,
) -> bool:
    if not value or not _valid(field_name, value):
        return False
    # Person-name formats are not authoritative validation. They remain in
    # review until a governed identity/reference match is available.
    if critical and field_name in {"patient_first", "patient_last"}:
        return False
    if deterministic_pixel_evidence and not critical:
        return True
    return len(independent_families) >= 2


def _tesseract_field_type(field_name: str, contract_type: str) -> str:
    if contract_type in {"date", "npi", "tax_id", "checkbox"}:
        return contract_type
    if contract_type in {"state", "bill_type", "diagnosis", "identifier"}:
        return "code"
    if contract_type == "zip":
        return "zip"
    if field_name.endswith("_state"):
        return "code"
    return "text"


def _should_suppress_duplicate_patient_address(
    relationship: PredictedField | None, insured_address: PredictedField | None
) -> bool:
    if relationship is None or relationship.raw_value != "01" or insured_address is None:
        return False
    value = (insured_address.raw_value or "").strip().upper()
    return value not in {"", "NA", "SAME", "UNKNOWN"}


def _relationship_from_pixels(image: Image.Image) -> str:
    gray = image.convert("L")
    # Interior rectangles exclude the printed checkbox borders. Coordinates
    # are relative to the atomic CMS box-6 crop.
    interiors = {
        "01": (72, 25, 91, 44),
        "02": (170, 25, 189, 44),
        "03": (250, 25, 269, 44),
        "04": (349, 25, 368, 44),
    }
    darkness = {}
    for code, box in interiors.items():
        crop = gray.crop(box)
        darkness[code] = sum(crop.histogram()[:128]) / (crop.width * crop.height)
    code, score = max(darkness.items(), key=lambda item: item[1])
    return code if score >= 0.03 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops", type=Path, default=Path("evaluation_results/field_crops"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluation_data/document_manifest.json")
    )
    parser.add_argument(
        "--prior-predictions", type=Path, default=Path("evaluation_data/predictions.json")
    )
    parser.add_argument("--output", type=Path, default=Path("evaluation_data/predictions_atomic.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prior = PredictionDataset.model_validate_json(
        args.prior_predictions.read_text(encoding="utf-8")
    )
    prior_by_id = {document.document_id: document for document in prior.documents}
    field_contract = yaml.safe_load(
        Path("config/evaluation/field_contract.yaml").read_text(encoding="utf-8")
    )
    rapid = RapidOCRTextExtractor()
    paddle = PaddleOCRTextExtractor()
    documents = []
    for document_id, metadata in sorted(manifest.items()):
        if metadata["form_type"] == "UNSTRUCTURED":
            documents.append(prior_by_id[document_id])
            continue
        fields = []
        for crop_path in sorted((args.crops / document_id).glob("*.png")):
            field_name = crop_path.stem
            form_fields = field_contract["forms"][metadata["form_type"]]["fields"]
            contract_field = form_fields.get(field_name, {})
            tesseract_type = _tesseract_field_type(
                field_name, str(contract_field.get("type", "text"))
            )
            cascade = CascadingOCR(
                paddle,
                [for_field_type(tesseract_type), TesseractTextExtractor(psm=11)],
            )
            with Image.open(crop_path) as source:
                original_image = source.convert("RGB")
            image = prepare_field_image(field_name, original_image)
            image_hash = hashlib.sha256(image.tobytes()).hexdigest()[:12]
            rapid_primary = _rapid_lines(
                rapid, image, crop_path.with_suffix(f".{image_hash}.rapid.json")
            )
            primary = _paddle_lines(
                paddle, image, crop_path.with_suffix(f".{image_hash}.paddle.json")
            )
            passes = [OCRCandidatePass("rapidocr", "field_prepared", rapid_primary)]
            passes.extend(
                cascade.extract_candidates(
                    image,
                    primary_lines=primary,
                    cache_prefix=crop_path.with_suffix(f".{image_hash}.cascade"),
                )
            )
            candidates = []
            engine_agreement: dict[str, set[str]] = {}
            for candidate_pass in passes:
                raw, confidence = _joined(candidate_pass.lines)
                value = normalize_atomic(field_name, raw)
                if value:
                    engine_agreement.setdefault(value, set()).add(
                        _engine_family(candidate_pass.engine)
                    )
                candidates.append((value, raw, confidence, candidate_pass))
            scored = [
                (
                    confidence
                    + 0.20 * (len(engine_agreement[value]) - 1)
                    + (0.12 if candidate_pass.engine == "rapidocr" else 0)
                    + (0.06 if candidate_pass.engine == "paddleocr" else 0),
                    len(engine_agreement[value]),
                    value,
                    raw,
                    confidence,
                    candidate_pass,
                )
                for value, raw, confidence, candidate_pass in candidates
                if _valid(field_name, value)
            ]
            _, _, value, raw, confidence, winner = max(
                scored,
                key=lambda item: (item[1] >= 2, item[1], item[0]),
                default=(0, 0, "", "", 0.0, passes[0]),
            )
            pixel_evidence = False
            if field_name == "rel_code":
                pixel_value = _relationship_from_pixels(original_image)
                if pixel_value:
                    value, raw, confidence = pixel_value, pixel_value, 1.0
                    pixel_evidence = True
            critical = bool(contract_field.get("critical", False))
            supporting_families = engine_agreement.get(value, set())
            accepted = _safe_to_accept(
                field_name,
                value,
                critical,
                supporting_families,
                deterministic_pixel_evidence=pixel_evidence,
            )
            fields.append(
                PredictedField(
                    field_name=field_name,
                    raw_value=value,
                    confidence=confidence,
                    validation_result=(
                        "VALID_INDEPENDENT_CONSENSUS" if accepted else "NEEDS_REVIEW"
                    ),
                    extraction_method=f"{winner.engine}:{winner.preprocessing}",
                    crop_reference=str(crop_path.relative_to(args.crops.parent)).replace("\\", "/"),
                    accepted=accepted,
                    reviewed=not accepted,
                    metadata={
                        "critical": critical,
                        "independent_families": sorted(supporting_families),
                        "acceptance_reason": (
                            "DETERMINISTIC_PIXEL_EVIDENCE"
                            if accepted and pixel_evidence
                            else "INDEPENDENT_ENGINE_CONSENSUS"
                            if accepted
                            else "HUMAN_REVIEW_REQUIRED"
                        ),
                        "ocr_candidates": [
                            {
                                "engine": candidate_pass.engine,
                                "preprocessing": candidate_pass.preprocessing,
                                "raw": candidate_raw,
                                "value": candidate_value,
                                "confidence": candidate_confidence,
                                "selected": candidate_pass is winner and candidate_value == value,
                            }
                            for candidate_value, candidate_raw, candidate_confidence, candidate_pass
                            in candidates
                        ]
                    },
                )
            )
        by_name = {field.field_name: field for field in fields}
        if _should_suppress_duplicate_patient_address(
            by_name.get("rel_code"), by_name.get("insured_addr1")
        ):
            for field_name in (
                "patient_addr1",
                "patient_addr2",
                "patient_city",
                "patient_state",
                "patient_zip",
            ):
                if field_name in by_name:
                    original = by_name[field_name]
                    by_name[field_name] = original.model_copy(
                        update={
                            "raw_value": "",
                            "normalized_value": None,
                            "accepted": False,
                            "reviewed": True,
                            "validation_result": "NEEDS_REVIEW",
                            "metadata": {
                                **original.metadata,
                                "projected_from_relationship": "SELF",
                                "pre_projection_value": original.raw_value,
                            },
                        }
                    )
        if by_name.get("insured_addr1") and by_name["insured_addr1"].raw_value == "SAME":
            placeholders = {
                "insured_city": "NA",
                "insured_state": "NA",
                "insured_zip": "999999999",
            }
            for field_name, placeholder in placeholders.items():
                if field_name in by_name:
                    by_name[field_name] = by_name[field_name].model_copy(
                        update={
                            "raw_value": placeholder,
                            "normalized_value": None,
                            "accepted": False,
                            "reviewed": True,
                            "validation_result": "NEEDS_REVIEW",
                        }
                    )
        documents.append(PredictionDocument(document_id=document_id, fields=list(by_name.values())))
        print(f"Atomic OCR {document_id}: {len(fields)} fields")
    result = PredictionDataset(documents=documents)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
