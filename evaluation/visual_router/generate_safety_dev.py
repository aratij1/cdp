from __future__ import annotations
import hashlib,json
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/"evaluation_results/visual_safety_dev_v1"
def font(n):
 try:return ImageFont.truetype("C:/Windows/Fonts/cour.ttf",n)
 except:return ImageFont.load_default()
def page(kind,i):
 im=Image.new("L",(1320,1760),255);d=ImageDraw.Draw(im);standard=kind in {"CMS1500","UB04"};rows=11 if kind=="CMS1500" else 16 if kind=="UB04" else 10;cols=8 if kind=="CMS1500" else 10
 title={"CMS1500":"PROFESSIONAL HEALTH CLAIM","UB04":"INSTITUTIONAL BILL","UNKNOWN_STRUCTURED":"ITEMIZED MEDICAL ACCOUNT","NON_CLAIM":"EXPLANATION OF BENEFITS","UNKNOWN_UNSTRUCTURED":"CLINICAL SUMMARY"}[kind];d.text((50,35),title,font=font(24),fill=0)
 if kind!="UNKNOWN_UNSTRUCTURED":
  for y in np.linspace(100,1650,rows+1):d.line((35,int(y),1285,int(y)),fill=60,width=1+(i%2))
  for x in np.linspace(35,1285,cols+1):d.line((int(x),100,int(x),1650),fill=60,width=1)
 labels=("PATIENT INSURED DIAGNOSIS PROVIDER SERVICE CODE CHARGES" if kind=="CMS1500" else "PATIENT TYPE OF BILL STATEMENT COVERS REVENUE HCPCS UNITS CHARGES" if kind=="UB04" else "PATIENT PROVIDER NPI DIAGNOSIS HCPCS CHARGES SERVICE DATE").split()
 for n,s in enumerate(labels):d.text((50,125+n*125),s,font=font(16),fill=0)
 if kind=="UNKNOWN_UNSTRUCTURED":
  for n in range(24):d.text((55,120+n*60),f"Clinical narrative line {n+1}, supporting information {i:03}.",font=font(17),fill=0)
 if i%3==0:im=im.filter(ImageFilter.GaussianBlur(.55))
 if i%5==0:im=im.crop((25,45,1300,1740)).resize((1320,1760))
 return im
def run():
 OUT.mkdir(parents=True,exist_ok=True);docs=[]
 for kind,count in (("CMS1500",30),("UB04",30),("UNKNOWN_STRUCTURED",20),("UNKNOWN_UNSTRUCTURED",20),("NON_CLAIM",20)):
  for i in range(count):
   im=page(kind,i);path=OUT/f"{kind.lower()}_{i:03}.png";im.save(path);docs.append({"document_id":path.stem,"path":str(path.resolve()),"truth":kind,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"source_family":"VISUAL_SAFETY_INDEPENDENT","renderer_family":"PIL_COURIER_CONFUSER_V1","quality":"HARD_CONFUSER","quality_bucket":"HARD_CONFUSER","degradation_family":"MIXED_CONFUSER"})
 m={"dataset_id":"VISUAL_SAFETY_DEV_V1","documents":docs,"contains_phi":False,"frozen_abcd_used":False,"visual_baseline_training_data_used":False};(OUT/"manifest.json").write_text(json.dumps(m,indent=2),"utf-8");return m
if __name__=="__main__":print(len(run()["documents"]))
