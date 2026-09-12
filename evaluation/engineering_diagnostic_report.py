"""Three separate metrics surfaces; aggregate output has no source/predicted values."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluation.candidate_runtime_freeze import readiness as runtime_readiness
from evaluation.engineering_accuracy import measure
from evaluation.qualification_state import (
    StateUnavailable,
    immutable_json,
    initialize_layout,
    status,
)
from evaluation.validation_blockers import classify_validation


def report(saved: Path, code_root: Path) -> dict:
    state=status()
    quality: dict = {"status":"WAITING_FOR_SOURCE_ONLY_LABELS", "labels_completed":"UNKNOWN_STATE_NOT_MOUNTED",
                    "expected_labels":21,"exact_accuracy":"NOT_EVALUABLE","normalized_accuracy":"NOT_EVALUABLE",
                    "critical_accuracy":"NOT_EVALUABLE","recognition_errors":"NOT_EVALUABLE",
                    "localization_errors":"NOT_EVALUABLE","validator_true_rejects":"NOT_EVALUABLE",
                    "validator_false_rejects":"NOT_EVALUABLE"}
    if state["status"]=="MOUNTED":
        try: quality=measure(saved)
        except FileNotFoundError:
            quality.update(labels_completed=0, status="ENGINEERING_REVIEW_NOT_PREPARED")
    replay=json.loads((saved/"disposition_replay_authority_v1.local.json").read_text(encoding="utf-8"))
    from evaluation.engineering_review import content_hash
    rows=[]
    for field in replay["fields"]:
        rows.append({"field_id":content_hash({"field_id":field["field_id"]}), "field_type":field["canonical_field"], "extraction_status":"VALUE_EXTRACTED_NOT_TRUTH_VERIFIED",
            "validation_status":"PASS" if not field["validation_blocker"] else "+".join(classify_validation(field["validation_reasons"])),
            "authority_status":field["authority_state"],
            "consensus_status":"INDEPENDENT_CONFIRMATION_REQUIRED" if field["consensus_required"] else "NOT_POLICY_REQUIRED",
            "acceptance_status":"BLOCKED" if not field["auto_eligible"] else "ELIGIBLE",
            "final_disposition":field["disposition"]})
    if state["status"]=="MOUNTED":
        immutable_json(initialize_layout()/"engineering"/"fresh_12"/"field_diagnostic.json",{"scope":"FRESH_12_ENGINEERING_ONLY","fields":rows})
    aggregate={key:dict(Counter(row[key] for row in rows)) for key in ("extraction_status","validation_status","authority_status","consensus_status","acceptance_status","final_disposition")} if rows else {}
    from evaluation.engineering_review import digest
    current=digest(saved/"raw_execution.local.json")
    if current!=replay["aggregate"]["source_execution_sha256"]: raise ValueError("SAVED_OCR_BINDING_CHANGED")
    return {"runtime":runtime_readiness(code_root),"governed_state":state,
            "A_extraction_quality":quality,
            "B_runtime_automation":{"fields":len(rows),"stages":aggregate,"auto_eligible":sum(f["auto_eligible"] for f in replay["fields"]),
                "validation_blocked":sum(f["validation_blocker"] for f in replay["fields"]),
                "authority_blocked":sum(bool(f["authority_blockers"]) for f in replay["fields"]),
                "independent_confirmation_required":sum(f["consensus_required"] for f in replay["fields"]),
                "hitl_required":sum(f["disposition"]=="HUMAN_REVIEW_REQUIRED" for f in replay["fields"])},
            "C_production_qualification":{key:"NOT_EVALUABLE" for key in ["track_b_accuracy","accepted_precision",
                "critical_accepted_precision","claim_hitl","STP_SAFE","false_accepts"]},
            "ocr_calls_during_measurement":0,"saved_ocr_sha256_before":current,"saved_ocr_sha256_after":current,
            "track_b_execution":"NOT_RUN","runtime_tuning":"NONE"}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--saved",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try: result=report(args.saved,Path(__file__).resolve().parents[1])
    except (StateUnavailable,ValueError,OSError,KeyError): raise SystemExit("DIAGNOSTIC_INPUT_UNAVAILABLE_OR_CHANGED") from None
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
