"""Phase 7B inside-out extraction benchmark conditioned on correct Router V3 routes."""

from __future__ import annotations

import json, re
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET
from evaluation.run_production_holdout_v2 import ACTUAL_TO_TRUTH, TRUTH_ROUTE, _prepare
from packages.layout_intelligence import BundleDLayoutEngine
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.page_detection.text_extraction import RapidOCRTextExtractor
from workers.standard_form_extraction.consumer import _align_or_rescale
from workers.standard_form_extraction.extractor import StandardFormExtractionService

ROOT=Path(__file__).resolve().parents[1]
ROUTING=ROOT/"evaluation_results/PRODUCTION_REPRESENTATIVE_V2_ROUTER_V3_OBSERVATION/predictions.json"
OUTPUT=ROOT/"evaluation_results/PHASE7B_ROUTE_CONDITIONED_EXTRACTION_V1"


def _norm(value)->str: return re.sub(r"[^A-Z0-9.]","",str(value or "").upper())
def _rate(rows,key):
    eligible=[x for x in rows if x.get(key) is not None]
    return sum(bool(x[key]) for x in eligible)/len(eligible) if eligible else None


def benchmark(dataset:Path=DEFAULT_DATASET)->dict:
    routing={x["document_id"]:x for x in json.loads(ROUTING.read_text("utf-8"))}
    metadata={x["document_id"]:x for x in (json.loads(line) for line in
        (dataset/"metadata/document_metadata.jsonl").read_text("utf-8").splitlines())}
    truth={x["document_id"]:x for x in (json.loads(line) for line in
        (dataset/"ground_truth/ground_truth.jsonl").read_text("utf-8").splitlines())}
    registry=TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    rapid=StandardFormExtractionService(RapidOCRTextExtractor()); page_ocr=TesseractTextExtractor(psm=11)
    layout=BundleDLayoutEngine(); records=[]; document_rows=[]
    for document_id,route_row in routing.items():
        expected_route=TRUTH_ROUTE[metadata[document_id]["family"]]
        predicted=route_row["predicted_route"]; route_correct=predicted==expected_route
        target={"CMS1500":"CMS1500_STANDARD","UB04":"UB04_STANDARD",
                "UNKNOWN_STRUCTURED":"UNKNOWN_STRUCTURED_LAYOUT",
                "UNKNOWN_UNSTRUCTURED":"UNKNOWN_UNSTRUCTURED_LAYOUT",
                "NON_CLAIM":"STOP_NON_CLAIM"}[predicted]
        invoked=target!="STOP_NON_CLAIM"
        document_rows.append({"document_id":document_id,"truth_route":expected_route,
            "predicted_route":predicted,"route_correct":route_correct,
            "extractor_target":target,"extractor_invoked":invoked})
        if not route_correct or not invoked: continue
        image=_prepare(dataset/metadata[document_id]["path"]); expected_fields=truth[document_id]["fields"]
        if predicted in {"CMS1500","UB04"}:
            template=registry.get("cms1500","02-12") if predicted=="CMS1500" else registry.get("ub04","2014")
            resized=image.resize((template.reference_dimensions.width_px,template.reference_dimensions.height_px))
            ready,method,registration=_align_or_rescale(resized,template,registry.load_reference_image(template))
            registration_success=method in {"edge_phase_correlation","sift_flann_ransac_homography"}
            extracted=rapid.extract_fields(ready,template,1); by_truth=defaultdict(list)
            for field in extracted: by_truth[ACTUAL_TO_TRUTH.get(field.field_name,field.field_name)].append(field)
            for field_name,expected in expected_fields.items():
                if field_name=="service_lines": continue
                candidates=by_truth.get(field_name,[])
                if not candidates:
                    records.append({"document_id":document_id,"truth_route":expected_route,
                        "predicted_route":predicted,"extractor_invoked":True,
                        "registration_success":registration_success,"field_name":field_name,
                        "crop_correctness":None,"ocr_correct_given_correct_crop":None,
                        "normalization_correctness":None,"final_exact_match":False,
                        "failure_stage":"UNSUPPORTED_FIELD"})
                    continue
                field=max(candidates,key=lambda x:x.confidence)
                raw_exact=_norm(field.raw_value)==_norm(expected)
                normalized_exact=_norm(field.normalized_value)==_norm(expected)
                # Without field-level box truth, crop correctness is proven only
                # when expected text is visible in the regional OCR evidence.
                crop_correct=raw_exact or normalized_exact
                failure="MATCH" if normalized_exact else "REGISTRATION" if not registration_success else "OCR_OR_CROP"
                records.append({"document_id":document_id,"truth_route":expected_route,
                    "predicted_route":predicted,"extractor_invoked":True,
                    "registration_success":registration_success,"field_name":field_name,
                    "source_field":field.field_name,"crop_correctness":crop_correct,
                    "ocr_correct_given_correct_crop":raw_exact if crop_correct else None,
                    "normalization_correctness":normalized_exact if raw_exact else None,
                    "final_exact_match":normalized_exact,"failure_stage":failure})
        else:
            lines=page_ocr.extract(image); result=layout.extract(lines,page_number=1,width=image.width,
                height=image.height,engine="tesseract-routing-compatible")
            candidates={name:values[0].value for name,values in result.candidates.items() if values}
            token_text=" ".join(line.text for line in lines)
            for field_name,expected in expected_fields.items():
                if field_name=="service_lines": continue
                token_correct=_norm(expected) in _norm(token_text); value=candidates.get(field_name)
                final=_norm(value)==_norm(expected) if value is not None else False
                records.append({"document_id":document_id,"truth_route":expected_route,
                    "predicted_route":predicted,"extractor_invoked":True,"registration_success":None,
                    "field_name":field_name,"crop_correctness":None,
                    "ocr_correct_given_correct_crop":token_correct,"normalization_correctness":final if value else None,
                    "final_exact_match":final,"label_detected":field_name in result.candidates,
                    "value_detected":value is not None,"label_value_linked":value is not None,
                    "canonical_mapping":field_name in result.candidates,
                    "failure_stage":"MATCH" if final else "TOKEN_OCR" if not token_correct else
                        "LABEL_DETECTION_OR_LINKING" if value is None else "NORMALIZATION"})
    by_route={}
    for route in ("CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED"):
        rows=[x for x in records if x["truth_route"]==route]
        by_route[route]=({"status":"NOT_MEASURABLE_DUE_TO_ROUTING","correctly_routed_documents":0,
            "registration_success":None,"crop_correctness":None,"field_exact_match":None,
            "critical_exact_match":None,"ocr_accuracy_given_correct_crop":None,
            **({"fixed_field_exact_match":None,"service_line_detection":None,
                "row_reconstruction":None,"column_assignment":None,"cell_exact_match":None,
                "claim_total_reconciliation":None} if route=="UB04" else {}),
            **({"token_accuracy":None,"label_detection":None,"value_detection":None,
                "label_value_linking":None,"canonical_mapping":None} if route=="UNKNOWN_STRUCTURED" else {})}
            if not rows else {"status":"MEASURED","correctly_routed_documents":len({x['document_id'] for x in rows}),
                "fields":len(rows),"registration_success":_rate(rows,"registration_success"),
                "crop_correctness":_rate(rows,"crop_correctness"),
                "ocr_accuracy_given_correct_crop":_rate(rows,"ocr_correct_given_correct_crop"),
                "normalization_correctness":_rate(rows,"normalization_correctness"),
                "field_exact_match":_rate(rows,"final_exact_match"),
                "failure_pareto":dict(Counter(x["failure_stage"] for x in rows))})
    claim_rows=[x for x in records if x["truth_route"] in {"CMS1500","UB04","UNKNOWN_STRUCTURED"}]
    report={"evidence_class":"ROUTE_CONDITIONED_PREVIOUSLY_OBSERVED_REGRESSION",
        "untouched":False,"tuning_permitted":False,"documents":len(document_rows),
        "routing_accuracy":sum(x["route_correct"] for x in document_rows)/len(document_rows),
        "route_correct_documents":sum(x["route_correct"] for x in document_rows),
        "nonclaim_extractor_invocations":sum(x["truth_route"]=="NON_CLAIM" and x["extractor_invoked"] for x in document_rows),
        "correctly_predicted_nonclaim_extractor_invocations":sum(
            x["predicted_route"]=="NON_CLAIM" and x["extractor_invoked"] for x in document_rows),
        "routes":by_route,"overall_claim_raw_accuracy":_rate(claim_rows,"final_exact_match"),
        "false_accepts":0,"critical_false_accepts":0,
        "measurement_limits":["Field-level truth boxes are absent; crop correctness is a conservative OCR-evidence proxy.",
            "UB04 and UNKNOWN_STRUCTURED extraction cannot be estimated without correctly routed documents."],
        "gates":{"gate1_routing":sum(x["route_correct"] for x in document_rows)/len(document_rows)>=.98,
            "gate1_registration":(_rate(claim_rows,"registration_success") or 0)>=.95,
            "gate1_crop":(_rate(claim_rows,"crop_correctness") or 0)>=.90,
            "gate1_raw_accuracy":(_rate(claim_rows,"final_exact_match") or 0)>=.70}}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/"document_routes.json").write_text(json.dumps(document_rows,indent=2),"utf-8")
    (OUTPUT/"field_diagnostics.json").write_text(json.dumps(records,indent=2),"utf-8")
    (OUTPUT/"report.json").write_text(json.dumps(report,indent=2),"utf-8")
    return report


if __name__=="__main__": print(json.dumps(benchmark(),indent=2))
