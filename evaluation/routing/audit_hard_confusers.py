"""Convert the frozen 120-page safety result into a taxonomy audit queue; never trains/tunes."""
from __future__ import annotations

import json
from pathlib import Path


LEGACY_TO_TAXONOMY = {
    "CMS1500": "CMS1500", "UB04": "UB04", "UNKNOWN_STRUCTURED": "UNKNOWN",
    "UNKNOWN_UNSTRUCTURED": "UNKNOWN", "NON_CLAIM": "OTHER_NON_CLAIM",
}


def build(input_path: Path, output_path: Path) -> dict:
    records = []
    for line in input_path.read_text("utf-8").splitlines():
        row = json.loads(line)
        visual = max(row.get("visual_evidence", {}).get("a", []),
                     key=lambda item: item["probability"], default={"family": None})
        records.append({
            "document_id": row["document_id"],
            "truth_taxonomy": LEGACY_TO_TAXONOMY[row["truth"]],
            "legacy_truth": row["truth"],
            "visual_prediction": visual["family"],
            "deterministic_prediction": row["predicted"],
            "confusion_family": f'{row["truth"]}_VS_{visual["family"]}',
            "human_visual_distinguishability": "PENDING_INDEPENDENT_REVIEW",
            "required_semantic_context": "PENDING_INDEPENDENT_REVIEW",
            "required_structural_context": "PENDING_INDEPENDENT_REVIEW",
            "page_image_alone_sufficient": None,
            "ocr_semantics_required": None,
            "document_context_required": None,
            "training_eligible": False,
        })
    result = {"corpus": "VISUAL_SAFETY_DEV_V1", "purpose": "TAXONOMY_DIAGNOSIS_ONLY",
              "model_tuning_allowed": False, "human_audit_status": "PENDING", "records": records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), "utf-8")
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    result = build(root / "evaluation_results/visual_safety_dev_v1/benchmark.jsonl",
                   root / "evaluation_results/routing_taxonomy_v1/hard_confuser_taxonomy_audit.json")
    print(json.dumps({"records": len(result["records"]), "human_audit_status": result["human_audit_status"]}))
