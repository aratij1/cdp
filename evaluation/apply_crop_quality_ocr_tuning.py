"""Attach shadow OCR recommendations to every crop-quality pilot record.

This step never reads reviewer labels or evaluation truth. Paddle model versions
belong to one independence group; an automatic recommendation requires agreement
between Paddle and Tesseract families.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

PILOT = Path("evaluation_results/table_crop_quality_pilot")


def _normalize(value: object, field_type: str) -> str:
    raw = str(value or "").upper().strip()
    if field_type in {"currency", "amount"}:
        cleaned = re.sub(r"[^0-9.\-]", "", raw)
        if cleaned and "." not in cleaned and len(cleaned) > 2:
            cleaned = f"{cleaned[:-2]}.{cleaned[-2:]}"
        return cleaned
    if field_type in {"date", "numeric", "integer", "zip", "npi"}:
        return re.sub(r"\D", "", raw)
    return re.sub(r"[^A-Z0-9]", "", raw)


def _hard_valid(value: str, field_type: str, field_name: str = "") -> bool:
    if not value:
        return False
    # A syntactically plausible HCPCS/HIPPS value is not authoritative.  The
    # crop pilot contains correlated cross-engine substitutions (for example
    # N/0), so keep this route review-only until a versioned code reference is
    # present.
    if field_name == "hcpcs_rate_hipps_code":
        return False
    if field_type == "date":
        formats = ("%m%d%y", "%m%d%Y")
        return any(_valid_date(value, fmt) for fmt in formats)
    if field_type in {"currency", "amount"}:
        try:
            return Decimal(value) >= 0
        except InvalidOperation:
            return False
    if field_type in {"numeric", "integer", "zip", "npi"}:
        return value.isdigit()
    if field_type == "code":
        return bool(re.fullmatch(r"[A-Z0-9.]{1,16}", value))
    return bool(value)


def _valid_date(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value, fmt)  # noqa: DTZ007
        return True
    except ValueError:
        return False


def main() -> int:
    manifest_path = PILOT / "pilot_manifest.jsonl"
    manifest = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    candidates = json.loads(
        (PILOT / "ocr_shadow/candidates.json").read_text(encoding="utf-8")
    )
    candidates.extend(
        json.loads(
            (PILOT / "ocr_shadow/ppocr_candidates.json").read_text(encoding="utf-8")
        )
    )
    by_id: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_id[candidate["candidate_id"]].append(candidate)

    counts = defaultdict(int)
    decisions = []
    for item in manifest:
        if item["document_family"] == "statement":
            item["data_type"] = {
                "service_date": "date",
                "fee_for_service": "currency",
                "cpt_code": "code",
            }.get(item["semantic_field_name"], item["data_type"])
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for candidate in by_id[item["candidate_id"]]:
            normalized = _normalize(candidate["raw_value"], item["data_type"])
            if normalized:
                grouped[normalized][candidate["independence_group"]].append(candidate)
        independent = [
            (value, groups)
            for value, groups in grouped.items()
            if {"PADDLE_FAMILY", "TESSERACT_FAMILY"}.issubset(groups)
        ]
        if len(independent) == 1 and _hard_valid(
            independent[0][0], item["data_type"], item["semantic_field_name"]
        ):
            value, groups = independent[0]
            status = "CROSS_FAMILY_AGREEMENT"
            suggestion = max(
                groups["PADDLE_FAMILY"] + groups["TESSERACT_FAMILY"],
                key=lambda row: row["raw_confidence"],
            )["raw_value"]
            automatically_acceptable = True
        else:
            paddle = [
                candidate for candidate in by_id[item["candidate_id"]]
                if candidate["independence_group"] == "PADDLE_FAMILY"
                and candidate["raw_value"]
            ]
            suggestion = (
                max(paddle, key=lambda row: row["raw_confidence"])["raw_value"]
                if paddle else ""
            )
            value = _normalize(suggestion, item["data_type"])
            groups = grouped.get(value, {})
            status = "PADDLE_REVIEW_SUGGESTION" if suggestion else "NO_EVIDENCE"
            automatically_acceptable = False
        counts[status] += 1
        item["ocr_suggestion"] = suggestion or ""
        item["ocr_suggestion_authority"] = (
            "CROSS_FAMILY_RECOMMENDATION"
            if automatically_acceptable else "UNVERIFIED_OCR_SUGGESTION"
        )
        item["ocr_cascade_status"] = status
        item["ocr_independence_groups"] = sorted(groups)
        item["automatically_acceptable"] = automatically_acceptable
        decisions.append({
            "candidate_id": item["candidate_id"],
            "field_name": item["semantic_field_name"],
            "suggestion": suggestion,
            "normalized_suggestion": value,
            "status": status,
            "independence_groups": sorted(groups),
            "automatically_acceptable": automatically_acceptable,
            "evaluation_truth_loaded": False,
        })

    manifest_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in manifest) + "\n",
        encoding="utf-8",
    )
    output = PILOT / "ocr_shadow"
    (output / "cascade_decisions.json").write_text(
        json.dumps(decisions, indent=2), encoding="utf-8"
    )
    metrics = {
        "labels_processed": len(manifest),
        "labels_with_suggestion": sum(bool(row["suggestion"]) for row in decisions),
        "cross_family_recommendations": counts["CROSS_FAMILY_AGREEMENT"],
        "paddle_review_suggestions": counts["PADDLE_REVIEW_SUGGESTION"],
        "no_evidence": counts["NO_EVIDENCE"],
        "evaluation_truth_loaded": False,
        "production_policy_changed": False,
    }
    (output / "cascade_metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
