#!/usr/bin/env python3
"""Build agent-created ground truth for Hackathon claims and score cascade accuracy.

GT sources (observed ink only — never invented):
  1. Visual inspection of warped ROI crops (agent-labeled)
  2. Multi-engine OCR consensus on the same crops
  3. Service-line Sum for empty box-28 totals

Writes:
  evaluation_data/hackathon_agent_gt/field_truth.json
  evaluation_results/hackathon_gt_accuracy/summary.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"
DEFAULT_RUN = ROOT / "evaluation_results" / "hackathon_1000_cascade_v9"
DEFAULT_GT = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
DEFAULT_OUT = ROOT / "evaluation_results" / "hackathon_gt_accuracy"

CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "ACCEPTED", "AUTO"}
LEDGER_PATH = ROOT / "docs" / "gt" / "ground_truth_discrepancy_ledger.json"


def _claim_keys(claim_id: str) -> set[str]:
    text = str(claim_id or "")
    tail = text.replace("\\", "/").split("/")[-1]
    return {text, text.replace("/", "__"), text.replace("__", "/"), tail}


def load_quarantine(path: Path | None = None) -> set[tuple[str, str]]:
    """Fields whose saved label conflicts with source and leave the accuracy denominator."""
    ledger = path or LEDGER_PATH
    if not ledger.exists():
        return set()
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()
    for record in payload.get("records") or []:
        if not record.get("quarantine_from_accuracy", True):
            continue
        field = record.get("field_name")
        if not field:
            continue
        for key in _claim_keys(str(record.get("claim_id") or "")):
            out.add((key, str(field)))
    return out


def _quarantined(claim_id: str, field: str, table: set[tuple[str, str]] | None = None) -> bool:
    keys = _claim_keys(claim_id)
    blocked = table if table is not None else load_quarantine()
    return any((key, field) in blocked for key in keys)


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _canon_date(value: object) -> str:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        if int(digits[0:4]) >= 1880:
            return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
        return f"{digits[4:8]}-{digits[0:2]}-{digits[2:4]}"
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}-{digits[0:2]}-{digits[2:4]}"
    return text.upper()


def _canon_id(value: object) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if compact.isdigit():
        return compact.lstrip("0") or "0"
    return compact


def _canon_money(value: object) -> str:
    raw = str(value or "").replace(",", "").replace("$", "").strip()
    try:
        return f"{float(raw):.2f}"
    except ValueError:
        return raw


def _canon_name(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _exact(field: str, predicted: object, expected: object, **context: Any) -> bool:
    """Representation normalization only; no OCR repairs or identity deletion."""
    from packages.evaluation.agent_gt_score import exact_match

    return exact_match(
        field=field,
        predicted=predicted,
        expected=expected,
        patient_name=context.get("patient_name"),
    )


# Agent visual GT for claims inspected from warped ROI crops + line-sum evidence.
# Methodology recorded per field in `source`.
SEED_VISUAL_GT: dict[str, dict[str, Any]] = {
    "Group A__M048DJJF.002": {
        "document": "Group A/M048DJJF.002",
        "fields": {
            "patient_dob": {
                "expected_value": "1946-07-16",
                "source": "visual_roi+paddle_span",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "0000374350",
                "source": "multi_engine_agree; border glyph not counted as leading 0",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "1160.00",
                "source": "box28_blank_ruling; line_sum 640+260+260 from warped 24F crops",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.003": {
        "document": "Group A/M048DJJF.003",
        "fields": {
            "patient_dob": {
                "expected_value": "1948-07-10",
                "source": "visual_digit_band 07|10|1948",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "0000374350",
                "source": "visual+rapid; paddle border-extra leading 0 discarded via lstrip norm",
                "confidence": "SILVER",
            },
            "total_charge": {
                "expected_value": "260.00",
                "source": "box28_blank_ruling; single line 24F 260.00",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.006": {
        "document": "Group A/M048DJJF.006",
        "fields": {
            "patient_dob": {
                "expected_value": "1960-01-19",
                "source": "visual_roi MM=01 DD=19 YY=60",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "RENTER ROVINSKI",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "RENTER ROVINSKI",
                "source": "visual_roi; repair I/1 confusable",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "967140950",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "270.00",
                "source": "box28 270.00; single line 24F 270.00 (POS 11 is 24B not a charge)",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.004": {
        "document": "Group A/M048DJJF.004",
        "fields": {
            "patient_dob": {
                "expected_value": "1973-07-01",
                "source": "cascade_span DATE_SHAPED rapidocr 07/01/1973",
                "confidence": "SILVER",
            },
            "patient_name": {
                "expected_value": "BLASZAK HAROLD",
                "source": "multi_engine_auto",
                "confidence": "SILVER",
            },
            "insured_name": {
                "expected_value": "SAME",
                "source": "multi_engine_auto (form SELF marker)",
                "confidence": "SILVER",
            },
            "insured_id_number": {
                "expected_value": "126190668",
                "source": "multi_engine_agree",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "573.00",
                "source": "line_sum E6",
                "confidence": "SILVER",
            },
        },
    },
}


def write_gt(path: Path) -> dict[str, Any]:
    payload = {
        "dataset": "Hackathon - 1000 Claims.zip",
        "created_by": "agent_visual_gt_v1",
        "created_at": _utc(),
        "methodology": [
            "Warp source page with GeometryResult.source_to_geometry_transform",
            "Crop critical ROIs; visually read digits/names",
            "Cross-check with paddle+rapid(+tesseract) span selection",
            "Empty box-28 totals use observed service-line Σ only",
            "Never invent DOB/amounts when ink is unreadable",
        ],
        "claims": SEED_VISUAL_GT,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def score(run_dir: Path, gt: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    field_exact = Counter()
    field_total = Counter()
    false_accepts = 0
    accepted_scored = 0
    quarantined_fields = 0
    missing_results = 0
    incomplete_results = 0
    claim_perfect = 0
    claim_scored = 0
    by_bundle: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarantine = load_quarantine()

    for claim_id, truth in (gt.get("claims") or {}).items():
        result_path = run_dir / "claims" / claim_id / "result.json"
        if not result_path.exists():
            # try ledger
            missing_results += 1
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("completed"):
            incomplete_results += 1
            continue
        fields = result.get("fields") or {}
        claim_ok = True
        field_rows = []
        patient_name_pred = (fields.get("patient_name") or {}).get("value")
        patient_name_gt = ((truth.get("fields") or {}).get("patient_name") or {}).get(
            "expected_value"
        )
        patient_for_same = patient_name_gt or patient_name_pred
        for name, meta in (truth.get("fields") or {}).items():
            expected = meta.get("expected_value")
            pred = (fields.get(name) or {}).get("value")
            disp = (fields.get(name) or {}).get("disp")
            exact = _exact(
                name, pred, expected, patient_name=patient_for_same
            )
            if _quarantined(claim_id, name, quarantine):
                quarantined_fields += 1
                field_rows.append(
                    {
                        "field": name,
                        "expected": expected,
                        "predicted": pred,
                        "disposition": disp,
                        "exact": exact,
                        "false_accept": False,
                        "quarantined": True,
                        "gt_confidence": meta.get("confidence"),
                    }
                )
                continue
            field_total[name] += 1
            if exact:
                field_exact[name] += 1
            else:
                claim_ok = False
            auto = disp in AUTO
            accepted_scored += int(auto)
            if auto and not exact:
                false_accepts += 1
            field_rows.append(
                {
                    "field": name,
                    "expected": expected,
                    "predicted": pred,
                    "disposition": disp,
                    "exact": exact,
                    "false_accept": auto and not exact,
                    "gt_confidence": meta.get("confidence"),
                }
            )
        claim_scored += 1
        if claim_ok:
            claim_perfect += 1
        doc = str(truth.get("document") or result.get("document") or "")
        bundle = str(result.get("bundle_id") or "/".join(doc.split("/")[:1] + [doc.split("/")[-1].split(".")[0]] if "/" in doc else [doc]))
        row = {
            "claim_id": claim_id,
            "true_stp": bool(result.get("true_stp")),
            "disposition": result.get("disposition"),
            "perfect_exact": claim_ok,
            "fields": field_rows,
            "bundle_id": result.get("bundle_id") or bundle,
        }
        rows.append(row)
        by_bundle[str(row["bundle_id"])].append(row)

    n_fields = sum(field_total.values())
    summary = {
        "run_dir": str(run_dir),
        "claims_scored": claim_scored,
        "field_count": n_fields,
        "exact_accuracy": round(sum(field_exact.values()) / n_fields, 6) if n_fields else 0.0,
        "perfect_claim_exact_rate": (
            round(claim_perfect / claim_scored, 6) if claim_scored else 0.0
        ),
        "false_accepts": false_accepts,
        "accepted_fields_scored": accepted_scored,
        "accepted_field_precision": (
            round((accepted_scored - false_accepts) / accepted_scored, 6)
            if accepted_scored else None
        ),
        "false_accept_rate": round(false_accepts / accepted_scored, 6) if accepted_scored else None,
        "false_accepts_per_scored_field": round(false_accepts / n_fields, 6) if n_fields else None,
        "quarantined_fields": quarantined_fields,
        "missing_claim_results": missing_results,
        "incomplete_claim_results": incomplete_results,
        "metric_contract": "strict_representation_only_v1",
        "release_gate_eligible": False,
        "release_gate_reason": "AGENT_LABELS_NOT_INDEPENDENT_ADJUDICATED_TRUTH",
        "field_exact": {
            name: {
                "exact": field_exact[name],
                "n": field_total[name],
                "rate": round(field_exact[name] / field_total[name], 6),
            }
            for name in CRITICAL
            if field_total[name]
        },
        "true_stp_of_scored": sum(1 for r in rows if r.get("true_stp")),
        "by_bundle": {
            bundle: {
                "n": len(items),
                "perfect_exact": sum(1 for r in items if r["perfect_exact"]),
                "true_stp": sum(1 for r in items if r["true_stp"]),
            }
            for bundle, items in sorted(by_bundle.items())
        },
        "claims": rows,
        "generated_at": _utc(),
        "note": (
            "Accuracy vs agent-created visual GT. Hackathon ZIP has no vendor labels; "
            "GT from warped ROI visual read + multi-engine consensus + line-sum E6."
        ),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--gt", type=Path, default=DEFAULT_GT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--write-seed-gt",
        action="store_true",
        help="Overwrite GT with SEED_VISUAL_GT only (destructive). Default: load existing GT.",
    )
    args = parser.parse_args()
    if args.write_seed_gt or not args.gt.exists():
        gt = write_gt(args.gt)
    else:
        gt = json.loads(args.gt.read_text(encoding="utf-8"))
    summary = score(args.run_dir, gt)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in summary if k != "claims"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
