from __future__ import annotations
import json,math
from pathlib import Path
from PIL import Image
from packages.document_routing.visual import VisualEvidenceInference
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/"evaluation_results/router_visual_v1";BASE=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl"
def run():
 base={x["document_id"]:x for x in (json.loads(v) for v in BASE.read_text().splitlines())};errors=[];groups={"false_UB":[],"true_UB":[],"true_CMS":[]}
 for test,train in (("VISUAL_SOURCE_A","VISUAL_SOURCE_B"),("VISUAL_SOURCE_B","VISUAL_SOURCE_A")):
  docs=json.loads((DATA/f"{test}.json").read_text())["documents"];engine=VisualEvidenceInference(ROOT/"models/router_visual"/f"hog_logistic_{train.lower()}_v1")
  for item in docs:
   ev,_=engine.predict(Image.open(item["path"]));p={x.family:x.probability for x in ev};rank=sorted(p,key=p.get,reverse=True);row=base.get(item["document_id"])
   if not row:continue
   d=row["decision"];record={"document_id":item["document_id"],"source_family":test,"renderer_family":item["renderer_family"],"truth_family":item["label"],"visual_prediction":rank[0],"visual_probability_vector":p,"top1_probability":p[rank[0]],"top2_probability":p[rank[1]],"visual_margin":p[rank[0]]-p[rank[1]],"entropy":-sum(v*math.log(max(v,1e-12)) for v in p.values()),"CMS_evidence":{"identity":bool(d["matched_anchors"].get("CMS1500_IDENTITY")),"anchors":len(d["matched_anchors"].get("CMS1500",[])),"structure":d["standard_structure"].get("CMS1500",0),"geometry":d["anchor_geometry_score"].get("CMS1500",0),"template":d["standard_structure"].get("template_similarity",0)},"UB_evidence":{"identity":bool(d["matched_anchors"].get("UB04_IDENTITY")),"anchors":len(d["matched_anchors"].get("UB04",[])),"structure":d["standard_structure"].get("UB04",0),"geometry":d["anchor_geometry_score"].get("UB04",0),"service_table":d["standard_structure"].get("service_table_score",0),"template":d["standard_structure"].get("template_similarity",0)},"image_quality":row["quality_bucket"],"DPI":200,"crop_framing":"REMEDIATION_SOURCE"}
   key="false_UB" if item["label"]=="CMS1500" and rank[0]=="UB04" else "true_UB" if item["label"]=="UB04" and rank[0]=="UB04" else "true_CMS" if item["label"]=="CMS1500" and rank[0]=="CMS1500" else None
   if key:groups[key].append(record)
   if key=="false_UB":errors.append(record)
 result={"false_standard_errors":errors,"comparison_summary":{k:{"count":len(v),"median_visual_margin":sorted(x["visual_margin"] for x in v)[len(v)//2] if v else None,"mean_CMS_structure":sum(x["CMS_evidence"]["structure"] for x in v)/len(v) if v else None,"mean_UB_structure":sum(x["UB_evidence"]["structure"] for x in v)/len(v) if v else None,"mean_service_table":sum(x["UB_evidence"]["service_table"] for x in v)/len(v) if v else None} for k,v in groups.items()}}
 (DATA/"false_standard_forensics.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":print(json.dumps(run(),indent=2))
