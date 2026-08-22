"""REM-03A stages over frozen remediation evidence; no OCR/CV recomputation."""
from __future__ import annotations
import json,statistics,time
from collections import Counter,defaultdict
from pathlib import Path
from packages.document_routing import RoutingEvidence,evaluate_standard_eligibility

ROOT=Path(__file__).resolve().parents[1]; SOURCE=ROOT/"evaluation_results/router_v4/remediation_01_before_rem01_rem02.jsonl"; OUT=ROOT/"evaluation_results/router_v4/rem03a"
FAMILIES=("CMS1500","UB04")
def _available(e):return sum(v>0 for v in (e.identity_evidence,e.anchor_evidence,e.geometry_evidence,e.structure_evidence,e.template_evidence,e.service_table_evidence))>=2
def evaluate():
    rows=[json.loads(x) for x in SOURCE.read_text("utf-8").splitlines()]; decisions={x["document_id"]:RoutingEvidence(**x["decision"]) for x in rows};OUT.mkdir(parents=True,exist_ok=True)
    audit=[]
    for x in rows:
      if x["truth"] not in FAMILIES or x["truth"]==x["predicted"]:continue
      d=decisions[x["document_id"]];families={f:evaluate_standard_eligibility(d,f,stage=1).model_dump(mode="json") for f in FAMILIES}
      audit.append({"document_id":x["document_id"],"truth_family":x["truth"],"predicted_route":x["predicted"],"quality_bucket":x["quality_bucket"],"family_eligibility":families,
        "winner":max(d.scores,key=d.scores.get),"runner_up":sorted(d.scores,key=d.scores.get,reverse=True)[1],"final_margin":d.margin})
    reasons=Counter(x["family_eligibility"][x["truth_family"]]["primary_rejection_reason"] for x in audit)
    groups=Counter()
    for x in audit:
      e=x["family_eligibility"][x["truth_family"]];positive=sum(v>0 for v in (e["identity_evidence"],e["anchor_evidence"],e["geometry_evidence"],e["structure_evidence"],e["service_table_evidence"]))
      groups[(x["truth_family"],"EVIDENCE_RICH_ELIGIBILITY_BLOCKED" if positive>=3 else "EVIDENCE_PARTIAL" if positive>=1 else "EVIDENCE_POOR")]+=1
    (OUT/"rejection_audit.json").write_text(json.dumps(audit,indent=2),"utf-8")
    summary={"experiment":"REM-03A-1","misses":len(audit),"meaningful_primary_reason_rate":sum(v for k,v in reasons.items() if k!="OTHER")/len(audit),"primary_rejection_pareto":dict(reasons.most_common()),"evidence_groups":{"|".join(k):v for k,v in groups.items()}}
    stages={}
    baseline_final={x["document_id"]:x["predicted"] for x in rows}
    previous={f:set() for f in FAMILIES}
    for stage in range(2,6):
      start=time.perf_counter();evaluated={}
      repeats=1
      for _ in range(repeats):
       evaluated={(x["document_id"],f):evaluate_standard_eligibility(decisions[x["document_id"]],f,stage=stage) for x in rows for f in FAMILIES}
      elapsed=(time.perf_counter()-start)*1000/(len(rows)*repeats)
      metrics={};eligible_sets={}
      for family in FAMILIES:
        truth={x["document_id"] for x in rows if x["truth"]==family};eligible={x["document_id"] for x in rows if evaluated[(x["document_id"],family)].eligible};eligible_sets[family]=eligible
        winners={x["document_id"] for x in rows if max(decisions[x["document_id"]].scores,key=decisions[x["document_id"]].scores.get)==family}
        metrics[family]={"documents":len(truth),"evidence_available":sum(_available(evaluated[(x["document_id"],family)]) for x in rows if x["truth"]==family),"eligible":len(truth&eligible),"eligibility_recall":len(truth&eligible)/len(truth),"eligibility_precision":len(truth&eligible)/len(eligible) if eligible else None,"false_eligibility_rate":len(eligible-truth)/(len(rows)-len(truth)),"highest_score":len(truth&winners),"ranking_recall_given_eligible":len(truth&eligible&winners)/len(truth&eligible) if truth&eligible else None,"final_correct":sum(x["truth"]==family and x["predicted"]==family for x in rows),"final_recall":sum(x["truth"]==family and x["predicted"]==family for x in rows)/len(truth),"newly_eligible_correct":len((truth&eligible)-previous[family])}
        previous[family]=truth&eligible
      path_pages=defaultdict(set);false_paths=Counter()
      for x in rows:
       for family in FAMILIES:
        ev=evaluated[(x["document_id"],family)]
        for path in ev.eligibility_paths_passed:
          if x["truth"]==family:path_pages[(family,path)].add(x["document_id"])
          else:false_paths[(family,path)]+=1
      attribution={}
      for (family,path),ids in path_pages.items():
        other=set().union(*(v for k,v in path_pages.items() if k[0]==family and k[1]!=path),set())
        attribution[f"{family}|{path}"]={"correct_pages":len(ids),"unique_correct_recoveries":len(ids-other),"overlapping_correct_recoveries":len(ids&other),"false_eligibility":false_paths[(family,path)]}
      stages[f"REM-03A-{stage}"]={"stage":stage,"metrics":metrics,"dual_standard_eligibility_rate":len(eligible_sets["CMS1500"]&eligible_sets["UB04"])/len(rows),"decision_logic_cpu_ms_page":elapsed,"final_routes_changed":0,"final_false_standard_routes":sum(x["truth"] not in FAMILIES and x["predicted"] in FAMILIES for x in rows),"path_attribution":attribution}
    result={"audit":summary,"stages":stages,"acceptance_thresholds_changed":False,"final_margin_changed":False,"OCR_calls_page":1,"production_default_changed":False}
    (OUT/"report.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":print(json.dumps(evaluate(),indent=2))
