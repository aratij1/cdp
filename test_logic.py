import json

try:
    with open("apps/evaluation_ui/public/reports/evaluation.json") as f:
        d = json.load(f)
        
    evidence = d.get("field_evidence", [])
    local = sum(1 for row in evidence if row.get("correct") and not ("hitl" in (row.get("extraction_method") or "").lower() or "human" in (row.get("extraction_method") or "").lower()))
    hitl = sum(1 for row in evidence if row.get("correct") and ("hitl" in (row.get("extraction_method") or "").lower() or "human" in (row.get("extraction_method") or "").lower()))
    
    print("Local:", local)
    print("HITL:", hitl)
    
except Exception as e:
    print(f"Error: {e}")
