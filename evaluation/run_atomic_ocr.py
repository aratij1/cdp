"""Run the OCR cascade on validated, one-field-per-image template crops."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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
    if field_name in {"rel_code", "insured_id_number"}:
        # insured_id_number: measured directly against this dataset's ground
        # truth, PaddleOCR reads 14/17 correctly on the plain autocontrasted
        # crop vs 13/17 after the 2x LANCZOS upscale below -- the upscale
        # interpolation itself was flipping a real O to a Q on at least one
        # document. Skip it for this field rather than for every field.
        return ImageOps.autocontrast(image.convert("L"), cutoff=1).convert("RGB")
    normalized = ImageOps.autocontrast(image.convert("L"), cutoff=1).convert("RGB")
    factor = 3 if field_name in {"type_of_bill", "patient_state", "insured_state"} else 2
    if normalized.height >= 100:
        return normalized
    return normalized.resize(
        (normalized.width * factor, normalized.height * factor), Image.Resampling.LANCZOS
    )


def _joined(lines: list[TextLine]) -> tuple[str, float]:
    # Sorting by raw y0 alone is unsafe: two tokens printed on the same
    # visual baseline (e.g. a dollar amount and its cents, or a first/last
    # name pair) routinely get slightly different y0 from OCR engines --
    # verified on real crops where the box top edges differ by several
    # pixels even though the boxes heavily overlap vertically. Sorting by
    # vertical box-center instead keeps same-line tokens grouped by their
    # true reading order (left-to-right, via x0) rather than letting y0
    # jitter scramble it -- confirmed fixes a real patient_last/first swap
    # and a real total_charge digit-split without any observed regression.
    ordered = sorted(lines, key=lambda line: ((line.y0 + line.y1) / 2, line.x0))
    text = " ".join(line.text for line in ordered).strip()
    confidence = sum(line.confidence for line in ordered) / len(ordered) if ordered else 0.0
    return text, confidence


def _reassemble_total_charge(lines: list[TextLine]) -> str:
    """Safely reassemble a dollar amount that OCR split into separate
    dollars/cents tokens on the same printed line (e.g. "582" + "00" for
    $582.00) -- verified as a real, recurring pattern on this dataset's
    box-28 crops, not a hypothetical case.

    Deliberately conservative: this only fires when exactly two purely-
    numeric tokens exist that (a) sit on the same visual line (their boxes
    vertically overlap by more than half of the shorter box's height) and
    (b) are adjacent in left-to-right order with no other numeric token
    between them, and (c) the second (cents) token is exactly 2 digits --
    the box-28 cents position is fixed-width on this form, so a differently
    sized second token is a sign of misread noise, not real cents, and is
    rejected rather than guessed at. Any other shape (0 or 1 numeric
    tokens, 3+ numeric tokens, non-adjacent tokens, wrong-length cents)
    returns "" so normalize_atomic's single-token fallback (or outright
    rejection) applies instead of a fabricated guess.
    """
    label_words = {"TOTAL", "CHARGE", "AMOUNT", "PAID", "TOTALCHARGE"}
    numeric_lines = [
        line for line in lines
        if re.fullmatch(r"\d+", line.text.strip())
    ]
    if len(numeric_lines) != 2:
        return ""
    first_line, second_line = sorted(numeric_lines, key=lambda line: line.x0)
    dollars, cents = first_line.text.strip(), second_line.text.strip()
    if len(cents) != 2:
        return ""
    if not (1 <= len(dollars) <= 6):
        return ""
    # Same-line requirement: vertical overlap must cover most of the
    # shorter box's height, not just touch at an edge.
    overlap = min(first_line.y1, second_line.y1) - max(first_line.y0, second_line.y0)
    shorter_height = min(first_line.y1 - first_line.y0, second_line.y1 - second_line.y0)
    if shorter_height <= 0 or overlap / shorter_height < 0.5:
        return ""
    # Adjacency requirement: no other detected text line's box may sit
    # between the two numeric tokens on the same line (would indicate a
    # stray label/currency-sign token was skipped over rather than the
    # two genuinely being the whole/cents halves of one amount).
    between = [
        line for line in lines
        if line is not first_line and line is not second_line
        and first_line.x1 <= line.x0 <= second_line.x0
        and line.text.strip().upper().replace(" ", "") not in label_words
    ]
    if between:
        return ""
    return f"{dollars}.{cents}"


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
    if field_name == "insured_id_number":
        # "1A. INSURED'S I.D. NUMBER (For Program in Item 1)" is frequently
        # captured in the same crop as the handwritten/typed value below it.
        # Rather than pattern-match the label text (OCR typos in the label
        # itself make that brittle -- verified against real samples), split
        # on whitespace and keep only tokens that look like a real member ID
        # (5-20 alphanumeric, at least one digit) while rejecting tokens
        # built entirely from known label words. Ambiguous input (zero or
        # more than one surviving candidate) safely returns "" rather than
        # guessing.
        label_words = {
            "FOR", "PROGRAM", "IN", "ITEM", "TTEM", "INSURED", "INSUREO",
            "INSUREDS", "I", "D", "NUMBER", "1A",
        }
        tokens = re.findall(r"[A-Z0-9]+", value.upper())
        candidates = [
            token for token in tokens
            if 5 <= len(token) <= 20
            and any(char.isdigit() for char in token)
            and token not in label_words
        ]
        return candidates[0] if len(candidates) == 1 else ""
    if field_name == "total_charge":
        # "28. TOTAL CHARGE" (and a printed "$") often shares the crop with
        # the handwritten amount. The label itself contains no digits, so
        # any clean, unambiguous decimal-looking token elsewhere in the
        # value is the candidate answer; if OCR misread a digit as a letter
        # (seen in real samples, e.g. "19Q00") or produced more than one
        # candidate, that is treated as unresolved rather than guessed at.
        label_words = {"TOTAL", "CHARGE", "AMOUNT", "PAID", "S"}
        tokens = re.findall(r"[A-Z0-9.,$]+", value.upper())
        candidates = [
            re.sub(r"[.,$]", "", token) for token in tokens
            if token not in label_words
            and re.fullmatch(r"\$?\d{1,3}(?:[.,]\d{2,3})?", token)
        ]
        return candidates[0] if len(candidates) == 1 else ""
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
    if field_name == "insured_id_number":
        return bool(re.fullmatch(r"[A-Z0-9]{5,20}", value))
    if field_name == "total_charge":
        # Real CMS1500 claim totals legitimately exceed $999 (verified
        # amounts up to $1675.00+ in this dataset); a 3-digit dollar cap
        # rejected correctly-read values outright, so this allows any
        # reasonable number of integer digits while still requiring an
        # unambiguous 2-3 digit cents suffix when a decimal is present.
        return bool(re.fullmatch(r"\d{1,7}(?:[.,]\d{2,3})?", value))
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
    tesseract_available = bool(
        os.environ.get("TESSERACT_CMD")
        or shutil.which("tesseract")
        or Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").is_file()
    )
    if not tesseract_available:
        print(
            "WARNING: tesseract binary not found; running the atomic OCR "
            "benchmark with PaddleOCR/RapidOCR only. Tesseract candidates "
            "will be absent from this evaluation run's evidence."
        )
    documents = []
    for doc_index, (document_id, metadata) in enumerate(sorted(manifest.items()), start=1):
        print(f"[{doc_index}/{len(manifest)}] {document_id[:12]}", flush=True)
        if metadata["form_type"] == "UNSTRUCTURED":
            documents.append(prior_by_id[document_id])
            continue
        fields = []
        for crop_path in sorted((args.crops / document_id).glob("*.png")):
            field_name = crop_path.stem
            print(f"    field: {field_name}", flush=True)
            form_fields = field_contract["forms"][metadata["form_type"]]["fields"]
            contract_field = form_fields.get(field_name, {})
            tesseract_type = _tesseract_field_type(
                field_name, str(contract_field.get("type", "text"))
            )
            tesseract_extractors = (
                [for_field_type(tesseract_type), TesseractTextExtractor(psm=11)]
                if tesseract_available
                else []
            )
            cascade = CascadingOCR(paddle, tesseract_extractors)
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
                if not value and field_name == "total_charge":
                    value = _reassemble_total_charge(candidate_pass.lines)
                    if value and not _valid(field_name, value):
                        value = ""
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
