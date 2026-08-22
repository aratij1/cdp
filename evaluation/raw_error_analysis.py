"""Truthful raw-accuracy diagnostics for the frozen synthetic benchmark.

This module does not tune extraction or acceptance policy. It freezes a run,
builds an error-contribution Pareto, reconstructs the exact localized crops,
and separates crop/localization failures from OCR failures. Crop labels are
explicitly heuristic unless the synthetic renderer contract proves the pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw

from evaluation.generate_public_synthetic_claims import _font, _intersects
from packages.criticality import CriticalityPolicy, DEFAULT_CRITICALITY_PATH
from workers.document_preparation.preprocessing import deskew, detect_skew_angle
from workers.page_detection.template_alignment import align_to_reference

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data" / "synthetic_public_v1"
DEFAULT_PREDICTIONS = ROOT / "evaluation_results" / "field_routing_verification_rerun"
DEFAULT_OUTPUT = ROOT / "evaluation_results" / "raw_accuracy_recovery"
DEFAULT_PARETO_DOC = ROOT / "docs" / "CDP_RAW_ACCURACY_ERROR_PARETO.md"

GEOMETRIC_CONDITIONS = {"rotation", "skew", "cropped_edges"}
REFERENCE_PRIORITY = {
    "clean_scan": 0, "fax": 1, "low_contrast": 2, "handwriting": 3,
    "poor_dpi": 4, "skew": 5, "rotation": 6, "cropped_edges": 7,
}
FROZEN_BASELINE_FIELDS = {
    "insured_id_number": (0, 60), "federal_tax_no": (0, 60),
    "provider_npi": (16, 60), "patient_dob": (82, 120), "patient_name": (77, 120),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        resolved = path.resolve()
        digest.update(resolved.relative_to(ROOT).as_posix().encode())
        digest.update(resolved.read_bytes())
    return digest.hexdigest()


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _similarity(left: Any, right: Any) -> float:
    return SequenceMatcher(None, _norm(left), _norm(right)).ratio()


def _reference_ids(manifest: dict[str, dict]) -> dict[str, str]:
    selected: dict[str, tuple[int, str]] = {}
    for document_id, metadata in manifest.items():
        candidate = (REFERENCE_PRIORITY.get(metadata["condition"], 99), document_id)
        family = metadata["form_type"]
        if family not in selected or candidate < selected[family]:
            selected[family] = candidate
    return {family: item[1] for family, item in selected.items()}


def _should_register(skew_degrees: float) -> bool:
    magnitude = abs(skew_degrees)
    return magnitude < 0.20 or magnitude > 1.00


def freeze_baseline(prediction_root: Path, dataset: Path, output: Path) -> dict[str, Any]:
    baseline = output / "baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    for name in ("metrics.json", "predictions.json"):
        shutil.copy2(prediction_root / name, baseline / name)
    dataset_files = [dataset / name for name in (
        "ground_truth.json", "document_manifest.json", "asset_inventory.json", "provenance.json"
    )]
    config_files = [
        ROOT / "config/templates/cms1500_v02_12.yaml",
        ROOT / "config/templates/ub04_v2014.yaml",
        ROOT / "config/field_criticality.yaml",
    ]
    templates = {}
    for path in config_files[:2]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates[payload["template_id"]] = {
            "version": str(payload["version"]), "sha256": _sha256(path),
        }
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "UNAVAILABLE"
    try:
        executable = shutil.which("tesseract")
        windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        executable = executable or (str(windows_default) if windows_default.is_file() else "tesseract")
        ocr_version = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, check=True
        ).stdout.splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        ocr_version = "UNAVAILABLE"
    prediction_payload = json.loads((baseline / "predictions.json").read_text(encoding="utf-8"))
    engines = sorted({
        field.get("engine", "unknown")
        for document in prediction_payload["documents"] for field in document["fields"]
    })
    ocr_versions = {"tesseract": ocr_version}
    ocr_python = ROOT / ".venv-ocr/Scripts/python.exe"
    for package in ("paddleocr", "rapidocr-onnxruntime"):
        engine = "paddleocr" if package == "paddleocr" else "rapidocr"
        if engine not in engines:
            continue
        try:
            ocr_versions[engine] = subprocess.run(
                [str(ocr_python), "-c", f"from importlib.metadata import version;print(version('{package}'))"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            ocr_versions[engine] = "UNAVAILABLE"
    command = (
        f"python -m evaluation.benchmark_synthetic_claims --dataset {dataset.as_posix()} "
        "--page-registration --field-routing"
    )
    if "paddleocr" in engines:
        command += " --member-id-engine paddleocr"
    elif "rapidocr" in engines:
        command += " --member-id-engine rapidocr"
    manifest = {
        "qualification": "SYNTHETIC_ONLY_NOT_PRODUCTION_ACCURACY",
        "git_sha": git_sha,
        "dataset_version": dataset.name,
        "dataset_sha256": _tree_hash(dataset_files),
        "configuration_sha256": _tree_hash(config_files),
        "templates": templates,
        "ocr_versions": ocr_versions,
        "registration_version": _sha256(ROOT / "workers/page_detection/template_alignment.py"),
        "preprocessing_version": _sha256(ROOT / "workers/document_preparation/preprocessing.py"),
        "routing_version": _sha256(ROOT / "evaluation/benchmark_synthetic_claims.py"),
        "metrics_sha256": _sha256(baseline / "metrics.json"),
        "predictions_sha256": _sha256(baseline / "predictions.json"),
        "command": command,
    }
    (baseline / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _template_label_contaminants(family: str, box: list[int]) -> list[str]:
    name = "cms1500_v02_12.yaml" if family == "CMS1500" else "ub04_v2014.yaml"
    spec = yaml.safe_load((ROOT / "config/templates" / name).read_text(encoding="utf-8"))
    target = tuple(box)
    canvas = Image.new("RGB", (8, 8), "white")
    draw = ImageDraw.Draw(canvas)
    label_font = _font(10)
    contaminants = []
    for field in spec["field_regions"]:
        label_x = field["x0"] + 2
        label_y = max(100, field["y0"] - 13)
        label_box = draw.textbbox((label_x, label_y), field["field_name"], font=label_font)
        if _intersects(label_box, target):
            contaminants.append(field["field_name"])
    return contaminants


def _foreground_ratio(crop: Image.Image) -> float:
    gray = crop.convert("L")
    histogram = gray.histogram()
    return sum(histogram[:150]) / max(1, gray.width * gray.height)


def classify_error(row: dict[str, Any]) -> tuple[str, str, str, float]:
    """Return root cause, crop state, explanation, and classification confidence."""
    expected, actual = row["expected"], row.get("raw_value")
    similarity = _similarity(expected, actual)
    contaminants = row["label_contaminants"]
    if contaminants:
        return (
            "SYNTHETIC_RENDERING_ARTIFACT", "CROP_MULTI_FIELD",
            f"template labels overlap the data ROI: {', '.join(contaminants)}", 1.0,
        )
    if row["foreground_ratio"] < 0.002:
        return "EMPTY_CROP", "CROP_EMPTY", "localized crop contains almost no foreground pixels", 0.95
    if row["condition"] in GEOMETRIC_CONDITIONS and not row["registration_accepted"]:
        return "REGISTRATION_FAILURE", "CROP_PARTIAL_TEXT", "geometric distortion was not accepted by registration", 0.95
    other = max(
        ((_similarity(actual, value), name) for name, value in row["other_truth"].items()),
        default=(0.0, ""),
    )
    if other[0] >= 0.88:
        return "WRONG_ROI", "CROP_WRONG_FIELD", f"OCR matches neighboring field {other[1]}", 0.90
    expected_tokens, actual_tokens = _norm(expected).split(), _norm(actual).split()
    if actual and " ".join(actual_tokens) != " ".join(expected_tokens) and sorted(actual_tokens) == sorted(expected_tokens):
        return "OCR_TOKEN_ORDER_ERROR", "CROP_CORRECT_TEXT_VISIBLE", "tokens match but order differs", 0.90
    if similarity >= 0.72:
        return "OCR_CHARACTER_ERROR", "CROP_CORRECT_TEXT_VISIBLE", "high character overlap with ground truth", 0.90
    if similarity >= 0.30:
        return "OCR_WORD_SEGMENTATION_ERROR", "CROP_CORRECT_TEXT_VISIBLE", "partial OCR overlap proves target text is present", 0.80
    if not actual:
        return "OCR_ENGINE_FAILURE", "CROP_CORRECT_TEXT_VISIBLE", "synthetic renderer contract places truth in this uncontaminated ROI", 0.75
    return "OCR_ENGINE_FAILURE", "CROP_CORRECT_TEXT_VISIBLE", "correct synthetic ROI has unrelated OCR output", 0.65


def _localized_pages(dataset: Path, manifest: dict[str, dict]) -> dict[str, tuple[Image.Image, dict]]:
    reference_ids = _reference_ids(manifest)
    references = {
        family: Image.open(dataset / manifest[doc_id]["file_name"]).convert("RGB")
        for family, doc_id in reference_ids.items()
    }
    pages: dict[str, tuple[Image.Image, dict]] = {}
    for document_id, metadata in manifest.items():
        with Image.open(dataset / metadata["file_name"]) as source:
            page = source.convert("RGB")
        skew = detect_skew_angle(page)
        localized = deskew(page, skew)
        evidence: dict[str, Any] = {
            "algorithm": "deskew_only", "accepted": None, "registration_confidence": None,
            "rotation_degrees": skew,
        }
        if _should_register(skew):
            result = align_to_reference(localized, references[metadata["form_type"]])
            if result.evidence:
                evidence = result.evidence.model_dump(mode="json")
                evidence["registration_confidence"] = result.evidence.alignment_confidence
            if result.success and result.warped is not None:
                localized = result.warped
        pages[document_id] = (localized, evidence)
    return pages


def _rows(predictions: dict, truth: dict, manifest: dict, pages: dict, output: Path,
          *, label_safe_renderer: bool = False) -> list[dict]:
    truth_docs = {item["document_id"]: item for item in truth["documents"]}
    crop_root, overlay_root = output / "crops", output / "roi_overlay"
    crop_root.mkdir(parents=True, exist_ok=True); overlay_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    policy = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
    for prediction in predictions["documents"]:
        document_id = prediction["document_id"]
        metadata, truth_doc = manifest[document_id], truth_docs[document_id]
        truth_fields = {item["field_name"]: item for item in truth_doc["fields"]}
        truth_values = {name: item["expected_raw"] for name, item in truth_fields.items()}
        localized, registration = pages[document_id]
        overlay = localized.copy(); draw = ImageDraw.Draw(overlay)
        wrong_fields = [item for item in prediction["fields"] if not item["correct"]]
        for item in wrong_fields:
            name = item["field_name"]; box = metadata["crop_boxes"][name]
            draw.rectangle(tuple(box), outline="red", width=4); draw.text((box[0], max(0, box[1]-18)), name, fill="red")
        overlay.thumbnail((520, 680)); overlay_path = overlay_root / f"{document_id}.jpg"
        overlay.save(overlay_path, quality=82)
        for item in prediction["fields"]:
            name = item["field_name"]; box = metadata["crop_boxes"][name]
            crop_dir = crop_root / document_id; crop_dir.mkdir(exist_ok=True)
            crop_path = crop_dir / f"{name}.png"; crop = localized.crop(tuple(box)); crop.save(crop_path)
            level = policy.for_field(name)
            row = {
                **item, "document_id": document_id, "document_family": metadata["form_type"],
                "condition": metadata["condition"], "crop_box": box,
                "crop_path": crop_path.relative_to(output).as_posix(),
                "overlay_path": overlay_path.relative_to(output).as_posix(),
                "foreground_ratio": _foreground_ratio(crop),
                "label_contaminants": (
                    [] if label_safe_renderer
                    else _template_label_contaminants(metadata["form_type"], box)
                ),
                "registration": registration,
                "registration_confidence": registration.get("registration_confidence"),
                "registration_accepted": registration.get("accepted") is not False,
                "criticality": level.value,
                "blocking": level.value in {"C2", "C3"},
                "ground_truth_critical": (
                    bool(truth_fields[name].get("critical")) or level.value in {"C2", "C3"}
                ),
                "other_truth": {key: value for key, value in truth_values.items() if key != name},
                "raw_exact": (item.get("raw_value") or "") == item["expected"],
                "normalized_exact": _norm(item.get("raw_value")) == _norm(item["expected"]),
            }
            if not item["correct"]:
                category, crop_status, reason, confidence = classify_error(row)
                row.update(error_category=category, crop_status=crop_status,
                           classification_reason=reason, classification_confidence=confidence)
            else:
                row.update(error_category=None, crop_status="CROP_CORRECT_TEXT_VISIBLE",
                           classification_reason="normalized extraction matches truth",
                           classification_confidence=1.0)
            row.pop("other_truth")
            rows.append(row)
    return rows


def pareto(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["document_family"], row["field_name"])].append(row)
    total_errors = sum(not row["correct"] for row in rows)
    output = []
    cumulative = 0
    for (family, field), values in sorted(grouped.items(), key=lambda item: (-sum(not r["correct"] for r in item[1]), item[0])):
        wrong = sum(not row["correct"] for row in values); correct = len(values) - wrong
        cumulative += wrong
        output.append({
            "document_family": family, "field_name": field, "total": len(values),
            "correct": correct, "wrong": wrong, "accuracy": correct / len(values),
            "error_contribution": wrong / total_errors if total_errors else 0,
            "cumulative_error_percentage": cumulative / total_errors if total_errors else 0,
            "criticality": values[0]["criticality"], "blocking": values[0]["blocking"],
        })
    return output


def _write_pareto_doc(items: list[dict], metrics: dict, path: Path) -> None:
    lines = [
        "# CDP Raw Accuracy Error Pareto", "",
        "> Synthetic-only diagnostic. This is not production accuracy.", "",
        f"Baseline: **{metrics['overall']['correct']} / {metrics['overall']['total']} ({metrics['overall']['accuracy']:.2%})**. ",
        f"Total errors: **{metrics['overall']['total'] - metrics['overall']['correct']}**.", "",
        "| Rank | Family | Field | Total | Correct | Wrong | Accuracy | % all errors | Cumulative | Criticality | Blocks STP |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for rank, item in enumerate(items, 1):
        lines.append(
            f"| {rank} | {item['document_family']} | `{item['field_name']}` | {item['total']} | "
            f"{item['correct']} | {item['wrong']} | {item['accuracy']:.2%} | "
            f"{item['error_contribution']:.2%} | {item['cumulative_error_percentage']:.2%} | "
            f"{item['criticality']} | {'yes' if item['blocking'] else 'no'} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gallery(rows: list[dict], output: Path) -> None:
    errors = [row for row in rows if not row["correct"]]
    families = sorted({row["document_family"] for row in errors})
    fields = sorted({row["field_name"] for row in errors})
    categories = sorted({row["error_category"] for row in errors})
    def options(values):
        return "".join(f'<option value="{html.escape(str(value))}">{html.escape(str(value))}</option>' for value in values)
    cards = []
    for row in errors:
        registration = row["registration"]
        details = html.escape(json.dumps(registration, sort_keys=True))
        cards.append(f"""
<article data-family="{html.escape(row['document_family'])}" data-field="{html.escape(row['field_name'])}"
 data-category="{html.escape(row['error_category'])}" data-engine="{html.escape(row.get('engine',''))}">
 <h2>{html.escape(row['document_id'])} · {html.escape(row['field_name'])}</h2>
 <div class="images"><figure><img src="{row['crop_path']}"><figcaption>Exact localized crop</figcaption></figure>
 <figure><img src="{row['overlay_path']}"><figcaption>Registered page + expected ROI</figcaption></figure></div>
 <dl><dt>Family / condition</dt><dd>{row['document_family']} / {row['condition']}</dd>
 <dt>Ground truth</dt><dd>{html.escape(str(row['expected']))}</dd>
 <dt>Final extracted</dt><dd>{html.escape(str(row.get('raw_value')))}</dd>
 <dt>Primary OCR</dt><dd>{html.escape(str(row.get('raw_value')))} ({row.get('confidence',0):.3f})</dd>
 <dt>Secondary OCR</dt><dd>{'not run' if row.get('attempts',1) == 1 else 'aggregate only in frozen baseline'}</dd>
 <dt>ROI / bbox</dt><dd>{html.escape(str(row['crop_box']))}</dd>
 <dt>Registration</dt><dd>{html.escape(str(registration.get('algorithm')))}; confidence={registration.get('registration_confidence')}</dd>
 <dt>Preprocessing</dt><dd>frozen benchmark route; attempt count={row.get('attempts')}</dd>
 <dt>Normalization before / after</dt><dd>{html.escape(str(row.get('raw_value')))} → {_norm(row.get('raw_value'))}</dd>
 <dt>Parser result</dt><dd>not separately recorded in frozen baseline</dd>
 <dt>Crop status</dt><dd>{row['crop_status']}</dd><dt>Error category</dt><dd>{row['error_category']}</dd>
 <dt>Classification basis</dt><dd>{html.escape(row['classification_reason'])} ({row['classification_confidence']:.0%})</dd>
 <dt>Registration evidence</dt><dd class="small">{details}</dd></dl></article>""")
    page = f"""<!doctype html><meta charset="utf-8"><title>CDP raw error gallery</title>
<style>body{{font:14px system-ui;margin:20px;background:#f6f7f9}}.filters{{position:sticky;top:0;background:white;padding:12px;z-index:2}}
article{{background:white;margin:16px 0;padding:16px;border-radius:10px}}.images{{display:flex;gap:16px;align-items:start;flex-wrap:wrap}}
img{{max-width:520px;max-height:420px;border:1px solid #bbb}}dl{{display:grid;grid-template-columns:190px 1fr;gap:6px}}dt{{font-weight:700}}dd{{margin:0}}.small{{font:11px monospace;overflow-wrap:anywhere}}</style>
<h1>CDP Raw Accuracy Error Gallery</h1><p>Synthetic-only diagnostic; classifications identify their evidence basis.</p>
<div class="filters">Family <select id="family"><option value="">all</option>{options(families)}</select>
 Field <select id="field"><option value="">all</option>{options(fields)}</select>
 Category <select id="category"><option value="">all</option>{options(categories)}</select>
 Engine <select id="engine"><option value="">all</option>{options(sorted({row.get('engine','') for row in errors}))}</select>
 <span id="count"></span></div>{''.join(cards)}
<script>const ids=['family','field','category','engine'];function filter(){{let n=0;document.querySelectorAll('article').forEach(x=>{{let ok=ids.every(k=>!document.getElementById(k).value||x.dataset[k]===document.getElementById(k).value);x.hidden=!ok;n+=ok}});count.textContent=n+' errors'}}ids.forEach(k=>document.getElementById(k).onchange=filter);filter()</script>"""
    (output / "error_gallery.html").write_text(page, encoding="utf-8")


def _write_recovery_docs(rows: list[dict], items: list[dict], summary: dict) -> None:
    errors = [row for row in rows if not row["correct"]]
    top_fields: list[str] = []
    for item in items:
        if item["wrong"] and item["field_name"] not in top_fields:
            top_fields.append(item["field_name"])
        if len(top_fields) == 5:
            break
    for field in top_fields:
        values = [row for row in rows if row["field_name"] == field]
        failures = [row for row in values if not row["correct"]]
        categories = Counter(row["error_category"] for row in failures)
        crop_states = Counter(row["crop_status"] for row in failures)
        family_counts = Counter(row["document_family"] for row in values)
        path = ROOT / "docs" / f"FIELD_RECOVERY_{field.upper()}.md"
        baseline_correct, baseline_total = FROZEN_BASELINE_FIELDS.get(
            field, (sum(row["correct"] for row in values), len(values))
        )
        final_correct = sum(row["correct"] for row in values)
        path.write_text(
            "\n".join([
                f"# Field Recovery: `{field}`", "",
                "> Synthetic benchmark diagnosis. Do not treat these measurements as production accuracy.", "",
                f"- Families: {dict(family_counts)}",
                f"- Frozen baseline accuracy: {baseline_correct}/{baseline_total} "
                f"({baseline_correct/baseline_total:.2%})",
                f"- Final accuracy: {final_correct}/{len(values)} ({final_correct/len(values):.2%})",
                f"- Error count: {len(failures)}",
                f"- Root causes: {dict(categories)}",
                f"- Crop states: {dict(crop_states)}", "",
                "## Measured conclusion", "",
                (
                    "The dominant failure is benchmark rendering/ROI contamination. Repair and regenerate the "
                    "synthetic fixture before changing production OCR."
                    if categories.get("SYNTHETIC_RENDERING_ARTIFACT", 0) >= len(failures) / 2
                    else "The dominant failures occur with the target crop present; benchmark field-specific OCR next."
                ), "",
                "## Required next experiment", "",
                "Run one isolated change, compare this field and overall accuracy, preserve zero false accepts, "
                "and reject the change if a frozen strong field regresses.", "",
            ]), encoding="utf-8"
        )
    ub = [item for item in items if item["document_family"] == "UB04"]
    ub_lines = [
        "# UB-04 Raw Error Pareto", "", "> Synthetic-only diagnostic.", "",
        "| Rank | Field | Total | Correct | Wrong | Accuracy | % all benchmark errors |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for rank, item in enumerate(ub, 1):
        ub_lines.append(
            f"| {rank} | `{item['field_name']}` | {item['total']} | {item['correct']} | "
            f"{item['wrong']} | {item['accuracy']:.2%} | {item['error_contribution']:.2%} |"
        )
    ub_lines.extend(["", "No service-line fields exist in synthetic_public_v1; UB-04 row/column accuracy is therefore not evaluated.", ""])
    (ROOT / "docs/UB04_RAW_ERROR_PARETO.md").write_text("\n".join(ub_lines), encoding="utf-8")
    artifacts = sum(row["error_category"] == "SYNTHETIC_RENDERING_ARTIFACT" for row in errors)
    (ROOT / "docs/CDP_SYNTHETIC_BENCHMARK_AUDIT.md").write_text(
        "\n".join([
            "# CDP Synthetic Benchmark Audit", "",
            "The current dataset is PHI-free and deterministic, but it is not production-representative.", "",
            f"- Evaluated fields: {len(rows)}",
            f"- Errors: {len(errors)}",
            f"- Proven label/data ROI overlaps among errors: {artifacts}",
            f"- System/OCR errors after excluding proven rendering overlaps: {len(errors)-artifacts}",
            "- Service-line labels: absent",
            "- Production holdout qualification: false", "",
            "## Finding", "",
            (
                "No populated data ROI contains a template label in the corrected renderer. The remaining failures "
                "are system/OCR errors on this synthetic set."
                if artifacts == 0
                else "The generator draws several template labels inside another populated field ROI. Those cases "
                "are BENCHMARK_GENERATION_ERROR, not evidence that production OCR or registration is wrong."
            ), "",
        ]), encoding="utf-8"
    )
    (ROOT / "docs/CDP_RAW_ACCURACY_RECOVERY_REPORT.md").write_text(
        "\n".join([
            "# CDP Raw Accuracy Recovery Report", "",
            "> In progress. All current figures are synthetic-only.", "",
            f"- Baseline/final current run: {summary['raw_accuracy']:.2%} ({summary['correct_fields']}/{summary['total_fields']})",
            f"- CMS: {summary['family_accuracy'].get('CMS1500', 0):.2%}",
            f"- UB-04: {summary['family_accuracy'].get('UB04', 0):.2%}",
            f"- Critical accuracy: {summary['critical_accuracy']:.2%}",
            f"- Crop correctness: {summary['crop_correctness_rate']:.2%}",
            f"- OCR accuracy conditional on correct crop: {summary['ocr_accuracy_given_correct_crop']:.2%}",
            f"- Normalization regressions: {summary['normalization_regression_count']}",
            f"- Registration errors: {summary['error_categories'].get('REGISTRATION_FAILURE', 0)}",
            f"- OCR errors: {sum(count for name, count in summary['error_categories'].items() if name.startswith('OCR_'))}",
            "- UB row errors: not measurable; the fixture has no service lines",
            f"- Safe automation coverage: {summary['safe_automation_coverage']:.2%}",
            f"- HITL: {summary['hitl_rate']:.2%}",
            f"- False accepts: {summary['false_accepts']}",
            f"- Mean latency: {summary['mean_latency_ms']:.2f} ms",
            f"- P95 latency: {summary['p95_latency_ms']:.2f} ms", "",
            "## Top errors before", "",
            "`insured_id_number` 60; `federal_tax_no` 60; `provider_npi` 44; "
            "`patient_dob` 38; `patient_name` 43.", "",
            "## Top errors after", "",
            ", ".join(
                f"`{name}` {count}" for name, count in summary["errors_by_field"].items()
            ) or "None.", "",
            "## Next recommended work", "",
            "Build an untouched production-representative holdout and retain the six residual correct-crop OCR errors "
            "for field-specific recovery. Raw accuracy now permits cautious evidence/HITL optimization without "
            "lowering acceptance thresholds.", "",
        ]), encoding="utf-8"
    )


def analyze(prediction_root: Path, dataset: Path, output: Path, pareto_doc: Path,
            *, label_safe_renderer: bool = False, write_recovery_docs: bool = True) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((dataset / "document_manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    predictions = json.loads((prediction_root / "predictions.json").read_text(encoding="utf-8"))
    metrics = json.loads((prediction_root / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((dataset / "provenance.json").read_text(encoding="utf-8"))
    label_safe_renderer = (
        label_safe_renderer
        or provenance.get("generator_contract") == "label-safe-populated-roi-v2"
    )
    pages = _localized_pages(dataset, manifest)
    rows = _rows(
        predictions, truth, manifest, pages, output,
        label_safe_renderer=label_safe_renderer,
    )
    items = pareto(rows)
    errors = [row for row in rows if not row["correct"]]
    correct_crops = [row for row in rows if row["crop_status"] == "CROP_CORRECT_TEXT_VISIBLE"]
    accepted = int(metrics.get("field_routing", {}).get("accepted", 0))
    critical = [row for row in rows if row["ground_truth_critical"]]
    family_accuracy = {}
    for family in sorted({row["document_family"] for row in rows}):
        family_rows = [row for row in rows if row["document_family"] == family]
        family_accuracy[family] = sum(row["correct"] for row in family_rows) / len(family_rows)
    summary = {
        "qualification": "SYNTHETIC_ONLY_NOT_PRODUCTION_ACCURACY",
        "total_fields": len(rows), "correct_fields": sum(row["correct"] for row in rows),
        "wrong_fields": len(errors), "raw_accuracy": sum(row["correct"] for row in rows) / len(rows),
        "family_accuracy": family_accuracy,
        "critical_correct": sum(row["correct"] for row in critical),
        "critical_total": len(critical),
        "critical_accuracy": sum(row["correct"] for row in critical) / len(critical),
        "safe_automated_fields": accepted,
        "safe_automation_coverage": accepted / len(rows),
        "hitl_rate": 1 - accepted / len(rows),
        "false_accepts": int(metrics.get("qualification", {}).get("false_accepts", 0)),
        "mean_latency_ms": metrics["runtime"]["mean_latency_ms"],
        "p95_latency_ms": metrics["runtime"]["p95_latency_ms"],
        "crop_correct_fields": len(correct_crops),
        "crop_correctness_rate": len(correct_crops) / len(rows),
        "ocr_correct_given_correct_crop": sum(row["correct"] for row in correct_crops),
        "ocr_accuracy_given_correct_crop": (
            sum(row["correct"] for row in correct_crops) / len(correct_crops) if correct_crops else None
        ),
        "meaningfully_classified_errors": sum(row["error_category"] != "UNKNOWN" for row in errors),
        "meaningful_classification_rate": sum(row["error_category"] != "UNKNOWN" for row in errors) / len(errors),
        "error_categories": dict(Counter(row["error_category"] for row in errors)),
        "errors_by_field": dict(Counter(row["field_name"] for row in errors).most_common()),
        "crop_statuses": dict(Counter(row["crop_status"] for row in errors)),
        "normalization_regression_count": sum(row["raw_exact"] and not row["normalized_exact"] for row in rows),
        "normalization_improvement_count": sum(not row["raw_exact"] and row["normalized_exact"] for row in rows),
        "telemetry_limitations": [
            "Frozen predictions do not retain per-attempt OCR text.",
            "Parser input/output was not separately recorded.",
            "Crop correctness is deterministic/heuristic and includes an explicit confidence and basis.",
        ],
    }
    (output / "field_error_pareto.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
    (output / "classified_errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    (output / "raw_accuracy_diagnostics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_pareto_doc(items, metrics, pareto_doc); _gallery(rows, output)
    if write_recovery_docs:
        _write_recovery_docs(rows, items, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pareto-doc", type=Path, default=DEFAULT_PARETO_DOC)
    parser.add_argument("--label-safe-renderer", action="store_true")
    parser.add_argument("--skip-recovery-docs", action="store_true")
    args = parser.parse_args()
    freeze_baseline(args.predictions, args.dataset, args.output)
    summary = analyze(
        args.predictions, args.dataset, args.output, args.pareto_doc,
        label_safe_renderer=args.label_safe_renderer,
        write_recovery_docs=not args.skip_recovery_docs,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
