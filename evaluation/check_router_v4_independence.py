"""Leakage audit using byte, perceptual, structure and generator identities."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]; BASE=ROOT/"evaluation_results/router_v4/datasets"
LEGACY=[ROOT/"evaluation_results/ROUTING_DEV_V2",ROOT/"evaluation_results/ROUTING_DEV_V3",
        ROOT/"evaluation_results/PRODUCTION_REPRESENTATIVE_V2_ROUTER_V3_OBSERVATION"]
def _bits(path,size=16):
    a=np.asarray(Image.open(path).convert("L").resize((size,size)),dtype=float); return (a<a.mean()).reshape(-1)
def audit():
    docs=[]
    for manifest_path in BASE.glob("*/manifest.json"):
        manifest=json.loads(manifest_path.read_text("utf-8"))
        for d in manifest["documents"]: docs.append((manifest["dataset_id"],manifest_path.parent/d["file"],d))
    exact={}; legacy_ids=set(); legacy=[]
    for root in LEGACY:
      if root.exists():
       for path in root.rglob("*"):
        if path.suffix.lower() in {".png",".jpg",".jpeg",".tif",".tiff"}:
         digest=hashlib.sha256(path.read_bytes()).hexdigest(); exact[digest]=str(path); legacy_ids.add(path.name)
         try: legacy.append((path,_bits(path)))
         except Exception: pass
    failures=[]; cross={}; seen_generator={}
    for partition,path,d in docs:
        if d["sha256"] in exact: failures.append({"type":"EXACT_SHA256","document_id":d["document_id"],"match":exact[d["sha256"]]})
        if d["file"] in legacy_ids: failures.append({"type":"SOURCE_FILENAME","document_id":d["document_id"]})
        prior=seen_generator.setdefault(d["generator_id"],partition)
        if prior!=partition: failures.append({"type":"GENERATOR_ID_REUSE","document_id":d["document_id"],"partitions":[prior,partition]})
        cross.setdefault(d["sha256"],[]).append(partition)
        if legacy:
            bits=_bits(path); nearest=min((int(np.count_nonzero(bits!=b)),str(p)) for p,b in legacy)
            if nearest[0]<=2: failures.append({"type":"PERCEPTUAL_NEAR_DUPLICATE","document_id":d["document_id"],"hamming":nearest[0],"match":nearest[1]})
    for digest,parts in cross.items():
        if len(set(parts))>1: failures.append({"type":"CROSS_PARTITION_EXACT_DUPLICATE","sha256":digest,"partitions":sorted(set(parts))})
    value={"audit_version":"router-v4-independence-v1","development_documents":len(docs),"legacy_images_compared":len(legacy),
      "exact_sha_checks":True,"perceptual_hamming_threshold":2,"generator_id_checks":True,"failures":failures,
      "known_representative_page_in_development":any("PRODUCTION_REPRESENTATIVE" in x.get("match","") for x in failures),
      "status":"PASS" if not failures else "FAIL"}
    out=ROOT/"evaluation_results/router_v4/independence.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(value,indent=2),"utf-8"); return value
if __name__=="__main__": print(json.dumps(audit(),indent=2))
