#!/usr/bin/env python3
"""Build and consolidate canonical Ground Truth for CDP.

Consolidates all partial ground truth sources across the repository:
  1. docs/gt/hackathon_agent_field_truth.json (checked-in agent consensus)
  2. Git history snapshot (0b03686~1:evaluation_data/hackathon_agent_gt/field_truth.json)
  3. evaluation_data/hard15_v12_3o/field_truth.json (frozen 15-doc hold-500 gate set)
  4. scripts.score_hackathon_gt_accuracy.SEED_VISUAL_GT (human visual ROI reads)
  5. evaluation_results/feedback/corrections.jsonl (reviewer corrections)
  6. Optional cascade run directories (--run-dir) to mine additional multi-engine consensus

Outputs:
  - evaluation_data/hackathon_agent_gt/field_truth.json (Agent GT schema for cascade & scoring)
  - evaluation_data/ground_truth.json (Pydantic GroundTruthDataset schema for evaluation.runner)
  - evaluation_data/document_manifest.json (Complete manifest of all 1000 claims + pending status)
  - docs/gt/hackathon_agent_field_truth.json (Mirrored documentation copy)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.schemas import GroundTruthDataset, GroundTruthDocument, GroundTruthField
from packages.evaluation.agent_gt_score import exact_match, normalize_field
from scripts.build_hackathon_agent_gt import build_from_run, merge_claims
from scripts.score_hackathon_gt_accuracy import (
    CRITICAL,
    SEED_VISUAL_GT,
    _canon_date,
    _canon_id,
    _canon_money,
    _canon_name,
)

DEFAULT_AGENT_GT_OUT = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
DEFAULT_EVAL_GT_OUT = ROOT / "evaluation_data" / "ground_truth.json"
DEFAULT_MANIFEST_OUT = ROOT / "evaluation_data" / "document_manifest.json"
DOCS_GT_PATH = ROOT / "docs" / "gt" / "hackathon_agent_field_truth.json"
LEDGER_PATH = ROOT / "docs" / "gt" / "ground_truth_discrepancy_ledger.json"
DATASET_RAW = ROOT / "dataset_raw"

CRITICAL_FIELDS = frozenset(
    {
        "patient_name",
        "patient_dob",
        "insured_id_number",
        "insured_name",
        "total_charge",
        "federal_tax_id",
        "provider_npi",
        "principal_diagnosis",
        "type_of_bill",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_git_historical_gt() -> dict[str, dict[str, Any]]:
    """Recover the 228-claim / 844-label ground truth snapshot from git history."""
    try:
        res = subprocess.run(
            ["git", "show", "0b03686~1:evaluation_data/hackathon_agent_gt/field_truth.json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            payload = json.loads(res.stdout)
            claims = payload.get("claims", {})
            print(f"[source] Recovered {len(claims)} claims from git history (0b03686~1)", flush=True)
            return claims
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Could not load git historical GT: {exc}", file=sys.stderr)
    return {}


def load_hard15_gt() -> dict[str, dict[str, Any]]:
    """Load the frozen hard-15 gate set ground truth."""
    local_path = ROOT / "evaluation_data" / "hard15_v12_3o" / "field_truth.json"
    if local_path.is_file():
        try:
            payload = json.loads(local_path.read_text(encoding="utf-8"))
            claims = payload.get("claims", {})
            print(f"[source] Loaded {len(claims)} claims from hard15_v12_3o (disk)", flush=True)
            return claims
        except Exception:  # noqa: BLE001
            pass

    try:
        res = subprocess.run(
            ["git", "show", "0b03686~1:evaluation_data/hard15_v12_3o/field_truth.json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            payload = json.loads(res.stdout)
            claims = payload.get("claims", {})
            print(f"[source] Recovered {len(claims)} claims from hard15_v12_3o (git)", flush=True)
            return claims
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Could not load hard15 GT: {exc}", file=sys.stderr)
    return {}


def load_docs_agent_gt() -> dict[str, dict[str, Any]]:
    """Load the checked-in docs/gt/hackathon_agent_field_truth.json."""
    if DOCS_GT_PATH.is_file():
        try:
            payload = json.loads(DOCS_GT_PATH.read_text(encoding="utf-8"))
            claims = payload.get("claims", {})
            print(f"[source] Loaded {len(claims)} claims from docs/gt/hackathon_agent_field_truth.json", flush=True)
            return claims
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Could not load docs GT: {exc}", file=sys.stderr)
    return {}


def load_feedback_corrections() -> dict[str, dict[str, Any]]:
    """Load reviewer feedback corrections from evaluation_results/feedback/corrections.jsonl."""
    corrections_path = ROOT / "evaluation_results" / "feedback" / "corrections.jsonl"
    if not corrections_path.is_file():
        return {}
    claims: dict[str, dict[str, Any]] = {}
    for line in corrections_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            cid = str(row.get("claim_id") or row.get("document_id") or "")
            fname = str(row.get("field_name") or "")
            cval = row.get("corrected_value")
            if cid and fname and cval:
                slot = claims.setdefault(cid, {"document": cid, "fields": {}})
                slot["fields"][fname] = {
                    "expected_value": str(cval).strip(),
                    "source": f"human_feedback:{row.get('reviewer', 'operator')}",
                    "confidence": "GOLD",
                }
        except Exception:  # noqa: BLE001
            continue
    if claims:
        print(f"[source] Loaded feedback corrections for {len(claims)} records", flush=True)
    return claims


def scan_raw_dataset(dataset_dir: Path) -> dict[str, dict[str, Any]]:
    """Scan dataset_raw to inventory all claims (labelled and pending)."""
    manifest: dict[str, dict[str, Any]] = {}
    if not dataset_dir.is_dir():
        return manifest

    for group_dir in sorted(dataset_dir.iterdir()):
        if not group_dir.is_dir() or not group_dir.name.startswith("Group"):
            continue
        group_name = group_dir.name
        form_type = "CMS1500" if group_name in {"Group A", "Group B"} else "UB04" if group_name == "Group C" else "UNSTRUCTURED"
        for img_path in sorted(group_dir.iterdir()):
            if not img_path.is_file() or img_path.suffix.lower() in {".txt", ".json", ".md"}:
                continue
            claim_id = f"{group_name}__{img_path.name}"
            doc_rel = f"{group_name}/{img_path.name}"
            manifest[claim_id] = {
                "claim_id": claim_id,
                "file_name": doc_rel,
                "group": group_name,
                "form_type": form_type,
                "file_size": img_path.stat().st_size,
            }
    return manifest


def _deterministic_split(document_id: str) -> str:
    """Stable 60/20/20 split: 60% calibration, 20% validation, 20% holdout."""
    bucket = sum(ord(ch) for ch in document_id) % 5
    if bucket == 0:
        return "holdout"
    if bucket == 4:
        return "validation"
    return "calibration"


def build_consolidated_gt(
    run_dirs: list[Path] | None = None,
    dataset_dir: Path = DATASET_RAW,
) -> tuple[dict[str, Any], GroundTruthDataset, dict[str, Any]]:
    """Consolidate all ground truth sources into Agent GT and Pydantic GroundTruthDataset."""
    mined_from_runs: list[dict[str, dict[str, Any]]] = []
    for rd in run_dirs or []:
        rd_path = rd if rd.is_absolute() else ROOT / rd
        if rd_path.is_dir():
            mined = build_from_run(rd_path)
            print(f"[source] Mined {len(mined)} claims from run {rd_path.name}", flush=True)
            mined_from_runs.append(mined)

    hist_gt = load_git_historical_gt()
    hard15_gt = load_hard15_gt()
    docs_gt = load_docs_agent_gt()
    feedback_gt = load_feedback_corrections()

    # Precedence order: later sources override earlier
    # 1. Historical git GT (broad 228-claim base)
    # 2. Docs GT (curated / checked-in)
    # 3. Mined runs (fresh consensus)
    # 4. Hard15 GT (frozen benchmark)
    # 5. Feedback corrections (human operator verified)
    # 6. SEED_VISUAL_GT (human visual ROI inspection)
    merged_claims = merge_claims(
        hist_gt,
        docs_gt,
        *mined_from_runs,
        hard15_gt,
        feedback_gt,
        SEED_VISUAL_GT,
    )

    # Raw dataset inventory
    raw_inventory = scan_raw_dataset(dataset_dir)
    total_raw = len(raw_inventory)

    # Compute statistics
    conf_counter = Counter()
    field_counter = Counter()
    by_group = Counter()
    for cid, payload in merged_claims.items():
        doc = payload.get("document", "")
        group = doc.split("/")[0] if "/" in doc else cid.split("__")[0]
        by_group[group] += 1
        for fname, fmeta in (payload.get("fields") or {}).items():
            conf_counter[str(fmeta.get("confidence", "UNKNOWN"))] += 1
            field_counter[fname] += 1

    total_claims = len(merged_claims)
    total_fields = sum(field_counter.values())

    agent_gt_payload = {
        "dataset": "Hackathon - 1000 Claims.zip",
        "created_by": "consolidated_ground_truth_builder_v1",
        "created_at": _utc_now(),
        "methodology": [
            "Consolidated Ground Truth for CDP platform.",
            "Integrates multi-engine OCR consensus (GOLD), auto-accepted + line-sum (SILVER),",
            "and visual ROI inspection (SEED_VISUAL_GT).",
            "Includes frozen hard-15 gate set and human reviewer corrections.",
            "Never invents ambiguous ink or unreadable amounts.",
        ],
        "stats": {
            "claims": total_claims,
            "field_labels": total_fields,
            "total_dataset_claims": total_raw,
            "coverage_percent": round((total_claims / total_raw * 100), 2) if total_raw else None,
            "by_confidence": dict(conf_counter),
            "by_field": dict(field_counter),
            "by_group": dict(by_group),
        },
        "claims": merged_claims,
    }

    # Build Pydantic GroundTruthDataset
    gt_documents: list[GroundTruthDocument] = []
    for cid in sorted(merged_claims.keys()):
        payload = merged_claims[cid]
        doc_path = str(payload.get("document") or cid.replace("__", "/"))
        group = doc_path.split("/")[0] if "/" in doc_path else cid.split("__")[0]
        form_type = "CMS1500" if group in {"Group A", "Group B"} else "UB04" if group == "Group C" else "UNSTRUCTURED"
        split = _deterministic_split(cid)

        fields: list[GroundTruthField] = []
        for fname in sorted(payload.get("fields", {}).keys()):
            fmeta = payload["fields"][fname]
            val = str(fmeta.get("expected_value") or "").strip()
            fields.append(
                GroundTruthField(
                    field_name=fname,
                    expected_raw=val,
                    expected_normalized=val,
                    required=fname in CRITICAL_FIELDS,
                    critical=fname in CRITICAL_FIELDS,
                )
            )

        gt_documents.append(
            GroundTruthDocument(
                document_id=cid,
                file_name=doc_path,
                form_type=form_type,
                split=split,
                fields=fields,
            )
        )

    pydantic_dataset = GroundTruthDataset(
        schema_version="1.0",
        documents=gt_documents,
    )

    # Build complete document manifest covering all 1000 claims
    manifest_payload: dict[str, dict[str, Any]] = {}
    for cid, info in sorted(raw_inventory.items()):
        is_labelled = cid in merged_claims
        gt_fields = list(merged_claims[cid].get("fields", {}).keys()) if is_labelled else []
        manifest_payload[cid] = {
            "claim_id": cid,
            "file_name": info["file_name"],
            "group": info["group"],
            "form_type": info["form_type"],
            "file_size": info["file_size"],
            "split": _deterministic_split(cid),
            "status": "LABELLED" if is_labelled else "PENDING",
            "field_count": len(gt_fields),
            "fields": gt_fields,
        }

    return agent_gt_payload, pydantic_dataset, manifest_payload


def save_ground_truth(
    agent_gt_payload: dict[str, Any],
    pydantic_dataset: GroundTruthDataset,
    manifest_payload: dict[str, Any],
    agent_gt_path: Path = DEFAULT_AGENT_GT_OUT,
    eval_gt_path: Path = DEFAULT_EVAL_GT_OUT,
    manifest_path: Path = DEFAULT_MANIFEST_OUT,
    sync_docs: bool = True,
) -> None:
    """Save all generated ground truth and manifest files."""
    agent_gt_path.parent.mkdir(parents=True, exist_ok=True)
    eval_gt_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    agent_gt_path.write_text(json.dumps(agent_gt_payload, indent=2) + "\n", encoding="utf-8")
    print(f"[write] Wrote Agent GT to {agent_gt_path} ({agent_gt_payload['stats']['claims']} claims, {agent_gt_payload['stats']['field_labels']} fields)", flush=True)

    eval_gt_path.write_text(pydantic_dataset.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"[write] Wrote Evaluation GT to {eval_gt_path} ({len(pydantic_dataset.documents)} documents)", flush=True)

    manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
    labelled_count = sum(1 for d in manifest_payload.values() if d["status"] == "LABELLED")
    pending_count = len(manifest_payload) - labelled_count
    print(f"[write] Wrote Document Manifest to {manifest_path} (Total: {len(manifest_payload)}, Labelled: {labelled_count}, Pending: {pending_count})", flush=True)

    if sync_docs:
        DOCS_GT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOCS_GT_PATH.write_text(json.dumps(agent_gt_payload, indent=2) + "\n", encoding="utf-8")
        print(f"[write] Synced Agent GT to docs: {DOCS_GT_PATH}", flush=True)


def verify_ground_truth(
    agent_gt_path: Path = DEFAULT_AGENT_GT_OUT,
    eval_gt_path: Path = DEFAULT_EVAL_GT_OUT,
) -> bool:
    """Run verification checks on the generated ground truth files."""
    print("\n--- Verifying Ground Truth Integrity ---", flush=True)
    ok = True

    # 1. Agent GT verification
    if not agent_gt_path.is_file():
        print(f"[FAIL] Missing {agent_gt_path}", file=sys.stderr)
        return False
    try:
        agent_data = json.loads(agent_gt_path.read_text(encoding="utf-8"))
        claims = agent_data.get("claims", {})
        if not claims:
            print("[FAIL] Agent GT claims dictionary is empty", file=sys.stderr)
            ok = False
        else:
            print(f"[PASS] Agent GT valid: {len(claims)} claims loaded")
    except Exception as exc:
        print(f"[FAIL] Agent GT JSON parse error: {exc}", file=sys.stderr)
        ok = False

    # 2. Pydantic Evaluation GT verification
    if not eval_gt_path.is_file():
        print(f"[FAIL] Missing {eval_gt_path}", file=sys.stderr)
        return False
    try:
        eval_ds = GroundTruthDataset.model_validate_json(eval_gt_path.read_text(encoding="utf-8"))
        print(f"[PASS] Evaluation GT valid: {len(eval_ds.documents)} documents validated against Pydantic schema")
    except Exception as exc:
        print(f"[FAIL] Evaluation GT Pydantic validation error: {exc}", file=sys.stderr)
        ok = False

    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", default=[], help="Cascade run dir(s) to mine consensus from.")
    parser.add_argument("--output-gt", type=Path, default=DEFAULT_AGENT_GT_OUT, help="Path for agent GT output.")
    parser.add_argument("--output-eval-gt", type=Path, default=DEFAULT_EVAL_GT_OUT, help="Path for Pydantic evaluation GT output.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_OUT, help="Path for document manifest output.")
    parser.add_argument("--dataset", type=Path, default=DATASET_RAW, help="Path to raw dataset directory.")
    parser.add_argument("--no-docs-sync", action="store_true", help="Do not overwrite docs/gt/hackathon_agent_field_truth.json.")
    parser.add_argument("--verify", action="store_true", default=True, help="Verify generated files.")
    args = parser.parse_args()

    agent_gt, pydantic_gt, manifest = build_consolidated_gt(
        run_dirs=args.run_dir,
        dataset_dir=args.dataset,
    )

    save_ground_truth(
        agent_gt_payload=agent_gt,
        pydantic_dataset=pydantic_gt,
        manifest_payload=manifest,
        agent_gt_path=args.output_gt,
        eval_gt_path=args.output_eval_gt,
        manifest_path=args.manifest,
        sync_docs=not args.no_docs_sync,
    )

    if args.verify:
        success = verify_ground_truth(args.output_gt, args.output_eval_gt)
        if not success:
            return 1

    print("\n[SUCCESS] Ground truth build completed successfully!", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
