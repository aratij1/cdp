"""Frozen-crop OCR failure analysis and local-engine benchmark for Phase 8.10B."""

from __future__ import annotations

import io
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

from PIL import Image

from packages.field_localization import FieldDefinitionRegistry
from packages.local_evidence_cascade import decide_local_candidate
from packages.page_observation import line_clustered_reading_order
from workers.cascade.tesseract_adapter import for_field_type
from workers.page_detection.text_extraction import RapidOCRTextExtractor

ROOT = Path(__file__).resolve().parents[1]
PHASE8_10 = ROOT / "evaluation_results/phase8_10"
OUTPUT = ROOT / "evaluation_results/phase8_10b"
DATA = ROOT / "evaluation_data/phase8_8_generalization"
DOCS = ROOT / "docs"
SOURCES = ("SOURCE_A", "SOURCE_B", "SOURCE_C")

TYPE_TAG = {
    "PERSON_NAME": "NAME_TEXT",
    "PERSON_OR_ORGANIZATION": "NAME_TEXT",
    "DATE": "DATE",
    "NPI": "NUMERIC",
    "TAX_IDENTIFIER": "NUMERIC",
    "CURRENCY": "AMOUNT",
    "ALPHANUMERIC_ID": "ALPHANUMERIC_ID",
    "CPT_HCPCS": "CODE",
    "ICD_CODE": "CODE",
    "TYPE_OF_BILL": "CODE",
}
MATRIX_TYPE = {
    "PERSON_NAME": "NAME",
    "PERSON_OR_ORGANIZATION": "NAME",
    "DATE": "DATE",
    "NPI": "NPI",
    "TAX_IDENTIFIER": "ID",
    "CURRENCY": "AMOUNT",
    "ALPHANUMERIC_ID": "ID",
    "CPT_HCPCS": "CODE",
    "ICD_CODE": "CODE",
    "TYPE_OF_BILL": "CODE",
    "ADDRESS": "ADDRESS",
}
CONFUSIONS = {("0", "O"), ("1", "I"), ("1", "L"), ("2", "Z"),
              ("5", "S"), ("6", "G"), ("8", "B")}


def _canonical(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", _canonical(value))


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for offset, target in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[offset] + 1,
                previous[offset - 1] + (char != target),
            ))
        previous = current
    return previous[-1]


def _cer(actual: object, expected: object) -> float:
    left, right = _canonical(actual), _canonical(expected)
    return _distance(left, right) / max(1, len(right))


def _primary_failure(raw: str, expected: str) -> tuple[str, list[str]]:
    left, right = _canonical(raw), _canonical(expected)
    tags: list[str] = []
    if not left:
        return "EMPTY_OCR", tags
    if _compact(left) == _compact(right):
        if left.replace(" ", "") == right.replace(" ", ""):
            return "WORD_SEGMENTATION", tags
        return "PUNCTUATION", tags
    if sorted(left.split()) == sorted(right.split()) and left.split() != right.split():
        return "TOKEN_ORDER", tags
    if len(left) == len(right):
        substitutions = [(a, b) for a, b in zip(left, right, strict=True) if a != b]
        if substitutions and all((a, b) in CONFUSIONS or (b, a) in CONFUSIONS
                                 for a, b in substitutions):
            return "DIGIT_LETTER_CONFUSION", tags
        return "CHAR_SUBSTITUTION", tags
    if len(left) < len(right):
        return "CHAR_DELETION", tags
    if len(left) > len(right):
        return "CHAR_INSERTION", tags
    return "OTHER", tags


def _registries() -> dict[str, FieldDefinitionRegistry]:
    return {
        family: FieldDefinitionRegistry.load(
            ROOT / f"config/field_definitions/{'cms1500' if family == 'CMS1500' else 'ub04'}_v1.yaml"
        )
        for family in ("CMS1500", "UB04")
    }


def _all_validation_rows() -> list[dict]:
    rows = []
    for source in SOURCES:
        path = PHASE8_10 / source.lower() / "v3_extraction/field_records.jsonl"
        for line in path.read_text("utf-8").splitlines():
            row = json.loads(line)
            if row.get("dataset_role") == "VALIDATION":
                row["source"] = source
                rows.append(row)
    return rows


def _image_path(source: str, document_id: str) -> Path:
    matches = [path for path in (DATA / source).rglob(f"{document_id}.*")
               if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}]
    if len(matches) != 1:
        raise ValueError(f"EXPECTED_ONE_IMAGE:{source}:{document_id}:{len(matches)}")
    return matches[0]


def build_failure_records() -> tuple[list[dict], list[dict]]:
    registries = _registries()
    all_rows = _all_validation_rows()
    usable = [row for row in all_rows if row["expected_value_in_region"]]
    failures = []
    for row in usable:
        if row["ocr_exact_given_correct_region"]:
            continue
        definition = registries[row["family"]].get(row["family"], row["field_name"])
        primary, tags = _primary_failure(row.get("raw_ocr") or "", row["expected"])
        tags.append(TYPE_TAG.get(definition.datatype, "OTHER"))
        variant = str(row.get("variant") or "").upper()
        for marker in ("FAX_NOISE", "BLUR", "LOW_CONTRAST", "ROTATION_RESIDUAL", "SMALL_TEXT"):
            if marker in variant:
                tags.append(marker)
        image_path = _image_path(row["source"], row["document_id"])
        image = Image.open(image_path).convert("RGB")
        bbox = tuple(round(value) for value in row["predicted_bbox"])
        crop = image.crop(bbox)
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        trace = row.get("candidate_trace") or {}
        regional = trace.get("regional_normalized")
        failures.append({
            "document_id": row["document_id"],
            "source": row["source"],
            "family": row["family"],
            "field_name": row["field_name"],
            "datatype": definition.datatype,
            "datatype_family": MATRIX_TYPE.get(definition.datatype, "OTHER"),
            "critical": bool(row["critical"]),
            "image_path": str(image_path.relative_to(ROOT)).replace("\\", "/"),
            "bbox": list(bbox),
            "crop_sha256": sha256(buffer.getvalue()).hexdigest(),
            "truth": row["expected"],
            "rapid_observation_raw": row.get("raw_ocr"),
            "rapid_observation_cer": _cer(row.get("raw_ocr"), row["expected"]),
            "primary_failure": primary,
            "secondary_tags": sorted(set(tags)),
            "secondary_called": bool(trace.get("secondary_invoked")),
            "secondary_normalized": regional,
            "secondary_correct": _canonical(regional) == _canonical(row["expected"]),
            "secondary_unchanged": bool(trace.get("secondary_invoked")) and not bool(
                trace.get("changed_output")
            ),
            "final_value": row.get("final"),
            "final_correct": bool(row["exact"]),
            "remaining_failure": not bool(row["exact"]),
        })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "ocr_failure_records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in failures), "utf-8"
    )
    return usable, failures


def _matrix(usable: list[dict], failures: list[dict]) -> dict:
    failure_keys = {(row["document_id"], row["field_name"]): row for row in failures}
    registries = _registries()
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in usable:
        definition = registries[row["family"]].get(row["family"], row["field_name"])
        failure = failure_keys.get((row["document_id"], row["field_name"]))
        trace = row.get("candidate_trace") or {}
        values = {
            "rapid_correct": int(bool(row["ocr_exact_given_correct_region"])),
            "rapid_wrong": int(not row["ocr_exact_given_correct_region"]),
            "secondary_called": int(bool(trace.get("secondary_invoked"))),
            "secondary_correct": int(bool(failure and failure["secondary_correct"])),
            "secondary_wrong": int(bool(trace.get("secondary_invoked")) and not bool(
                failure and failure["secondary_correct"]
            )),
            "secondary_unchanged": int(bool(trace.get("secondary_invoked")) and not bool(
                trace.get("changed_output")
            )),
            "remaining_failure": int(not row["exact"]),
        }
        for key in (
            f"FIELD:{row['field_name']}",
            f"FORM:{row['family']}",
            f"DATATYPE:{MATRIX_TYPE.get(definition.datatype, 'OTHER')}",
        ):
            groups[key].update(values)
    return {key: dict(value) for key, value in sorted(groups.items())}


def _field_type(datatype: str) -> str:
    return {
        "DATE": "date", "NPI": "npi", "TAX_IDENTIFIER": "tax_id",
        "CURRENCY": "currency", "ALPHANUMERIC_ID": "code", "CPT_HCPCS": "code",
        "ICD_CODE": "code", "TYPE_OF_BILL": "code",
    }.get(datatype, "text")


def run_benchmark(failures: list[dict]) -> list[dict]:
    rapid = RapidOCRTextExtractor()
    try:
        import paddleocr  # noqa: F401
        paddle_available = True
    except ImportError:
        paddle_available = False
    records = []
    images: dict[Path, Image.Image] = {}
    for number, failure in enumerate(failures, 1):
        path = ROOT / failure["image_path"]
        image = images.setdefault(path, Image.open(path).convert("RGB"))
        bbox = failure["bbox"]
        for engine_name in ("rapidocr", "paddleocr", "tesseract"):
            if engine_name == "paddleocr" and not paddle_available:
                records.append({**failure, "engine": engine_name, "status": "ENGINE_UNAVAILABLE",
                                "raw_output": None, "normalized_output": None,
                                "exact_match": False, "cer": None, "latency_ms": None,
                                "cpu_time_ms": None})
                continue
            started, cpu_started = time.perf_counter(), time.process_time()
            try:
                if engine_name == "rapidocr":
                    lines = rapid.extract_region(image, *bbox)
                elif engine_name == "tesseract":
                    lines = for_field_type(_field_type(failure["datatype"])).extract_region(
                        image, *bbox
                    )
                else:
                    from workers.page_detection.text_extraction import PaddleOCRTextExtractor
                    lines = PaddleOCRTextExtractor().extract_region(image, *bbox)
                raw = " ".join(line.text for line in line_clustered_reading_order(lines))
                normalized = decide_local_candidate(raw, failure["datatype"]).normalized_value or raw
                status = "OK"
            except Exception as exc:  # provider availability is an observed benchmark result
                raw, normalized = None, None
                status = f"ENGINE_EXCEPTION:{type(exc).__name__}"
            latency = (time.perf_counter() - started) * 1000
            cpu = (time.process_time() - cpu_started) * 1000
            records.append({
                **failure,
                "engine": engine_name,
                "status": status,
                "raw_output": raw,
                "normalized_output": normalized,
                "exact_match": _canonical(normalized) == _canonical(failure["truth"]),
                "cer": _cer(normalized, failure["truth"]) if normalized is not None else None,
                "latency_ms": latency,
                "cpu_time_ms": cpu,
            })
        print(f"phase8.10b OCR benchmark {number}/{len(failures)}", flush=True)
    (OUTPUT / "ocr_failure_benchmark.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records), "utf-8"
    )
    return records


def summarize(usable: list[dict], failures: list[dict], benchmark: list[dict]) -> dict:
    matrix = _matrix(usable, failures)
    available = [row for row in benchmark if row["status"] == "OK"]
    by_engine = {}
    for engine in ("rapidocr", "paddleocr", "tesseract"):
        rows = [row for row in benchmark if row["engine"] == engine]
        ok = [row for row in rows if row["status"] == "OK"]
        by_engine[engine] = {
            "status": "AVAILABLE" if len(ok) == len(rows) else (
                "UNAVAILABLE" if not ok else "PARTIAL"
            ),
            "samples": len(ok),
            "correct": sum(row["exact_match"] for row in ok),
            "accuracy_on_rapid_failure_set": (
                sum(row["exact_match"] for row in ok) / len(ok) if ok else None
            ),
            "p50_latency_ms": statistics.median(
                row["latency_ms"] for row in ok
            ) if ok else None,
        }
    indexed = defaultdict(dict)
    for row in available:
        indexed[(row["document_id"], row["field_name"])][row["engine"]] = row
    solved_paddle = sum(item.get("paddleocr", {}).get("exact_match", False)
                        for item in indexed.values())
    solved_tesseract = sum(item.get("tesseract", {}).get("exact_match", False)
                           for item in indexed.values())
    both = sum(item.get("paddleocr", {}).get("exact_match", False)
               and item.get("tesseract", {}).get("exact_match", False)
               for item in indexed.values())
    unsolved = sum(not any(row.get("exact_match", False) for row in item.values())
                   for item in indexed.values())
    summary = {
        "production_usable_record_definition": "expected_value_in_region",
        "production_usable_regions": len(usable),
        "rapid_observation_correct": len(usable) - len(failures),
        "rapid_observation_incorrect": len(failures),
        "final_failures_within_region": sum(row["remaining_failure"] for row in failures),
        "failure_categories": dict(Counter(row["primary_failure"] for row in failures)),
        "attribution_rate": sum(row["primary_failure"] != "OTHER" for row in failures)
        / max(1, len(failures)),
        "matrix": matrix,
        "engines": by_engine,
        "rapid_failures_solved_by_paddle": solved_paddle,
        "rapid_failures_solved_by_tesseract": solved_tesseract,
        "solved_by_both": both,
        "unsolved_by_all_available": unsolved,
    }
    (OUTPUT / "ocr_summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    return summary


def write_reports(summary: dict) -> None:
    categories = sorted(summary["failure_categories"].items(), key=lambda item: -item[1])
    lines = "\n".join(f"| {name} | {count} |" for name, count in categories)
    (DOCS / "CDP_PHASE8_10B_OCR_FAILURE_PARETO.md").write_text(
        "# CDP Phase 8.10B OCR Failure Pareto\n\n"
        f"The frozen extraction records contain {summary['production_usable_regions']} regions "
        f"marked expected-value-present. Rapid's page observation is correct on "
        f"{summary['rapid_observation_correct']} and wrong on {summary['rapid_observation_incorrect']} "
        f"({summary['rapid_observation_correct']/summary['production_usable_regions']:.2%} conditional accuracy). "
        f"Selective regional extraction reduces this to {summary['final_failures_within_region']} "
        "remaining final failures. This preserves the historical 301/390 denominator; it is not "
        "silently substituted with the separate 369/420 production-usable localization metric.\n\n"
        "| Primary class | Count |\n|---|---:|\n" + lines + "\n\n"
        f"Meaningful attribution: {summary['attribution_rate']:.2%}. Datatype and image-condition "
        "labels are retained as secondary tags in `ocr_failure_records.jsonl`.\n",
        "utf-8",
    )
    matrix_lines = []
    for key, row in summary["matrix"].items():
        matrix_lines.append(
            f"| {key} | {row.get('rapid_correct',0)} | {row.get('rapid_wrong',0)} | "
            f"{row.get('secondary_called',0)} | {row.get('secondary_correct',0)} | "
            f"{row.get('secondary_wrong',0)} | {row.get('secondary_unchanged',0)} | "
            f"{row.get('remaining_failure',0)} |"
        )
    (DOCS / "CDP_PHASE8_10B_OCR_FIELD_MATRIX.md").write_text(
        "# CDP Phase 8.10B OCR Field Matrix\n\n"
        "| Scope | Rapid correct | Rapid wrong | Secondary called | Secondary correct | "
        "Secondary wrong | Secondary unchanged | Remaining failure |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|\n" + "\n".join(matrix_lines) + "\n",
        "utf-8",
    )


def main() -> None:
    usable, failures = build_failure_records()
    benchmark = run_benchmark(failures)
    summary = summarize(usable, failures, benchmark)
    write_reports(summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
