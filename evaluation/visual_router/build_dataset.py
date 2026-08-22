"""Build two renderer-separated page-image sources plus new unstructured pages."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2];REM=ROOT/"evaluation_results/router_v4/remediation_01";OUT=ROOT/"evaluation_results/router_visual_v1"
def _font(n):
 try:return ImageFont.truetype("C:/Windows/Fonts/georgia.ttf",n)
 except:return ImageFont.load_default()
def build():
 m=json.loads((REM/"manifest.json").read_text("utf-8"));OUT.mkdir(parents=True,exist_ok=True);sources={}
 for source,needle in (("VISUAL_SOURCE_A","PIL_"),("VISUAL_SOURCE_B","OPENCV_")):
  folder=OUT/source;folder.mkdir(exist_ok=True);docs=[]
  for x in m["documents"]:
   if not x["renderer_family"].startswith(needle):continue
   docs.append({"document_id":x["document_id"],"path":str((REM/x["file"]).resolve()),"label":x["truth"],"renderer_family":x["renderer_family"],"sha256":x["sha256"]})
  for i in range(20):
   if source.endswith("A"):
    im=Image.new("L",(1450,1900),255);d=ImageDraw.Draw(im);d.text((80,80),"CLINICAL NARRATIVE ATTACHMENT",font=_font(26),fill=0)
    for n in range(22):d.text((90,170+n*65),f"Narrative paragraph {n+1}; supporting clinical information {i:03}.",font=_font(17),fill=0)
   else:
    a=np.full((1680,1180),255,np.uint8);cv2.putText(a,"SUPPORTING DOCUMENT",(55,70),cv2.FONT_HERSHEY_DUPLEX,.8,0,1)
    for n in range(24):cv2.putText(a,f"Narrative line {n+1} reference {i:03}",(60,140+n*55),cv2.FONT_HERSHEY_SIMPLEX,.48,0,1,cv2.LINE_AA)
    im=Image.fromarray(a)
   path=folder/f"unstructured_{i:03}.png";im.save(path);docs.append({"document_id":f"{source.lower()}_unstructured_{i:03}","path":str(path.resolve()),"label":"UNKNOWN_UNSTRUCTURED","renderer_family":source,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
  manifest={"source":source,"created_at":datetime.now(timezone.utc).isoformat(),"documents":docs,"contains_phi":False,"frozen_abcd_used":False};path=OUT/f"{source}.json";path.write_text(json.dumps(manifest,indent=2),"utf-8");sources[source]={"count":len(docs),"hash":hashlib.sha256(path.read_bytes()).hexdigest()}
 result={"dataset_id":"ROUTING_DEV_VISUAL_EVIDENCE_V1","sources":sources,"classes":["CMS1500","UB04","UNKNOWN_STRUCTURED","UNKNOWN_UNSTRUCTURED","NON_CLAIM"],"frozen_abcd_used":False};(OUT/"manifest.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":print(json.dumps(build(),indent=2))
