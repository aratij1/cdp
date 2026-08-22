"""Independent PHI-free reproductions for REM-01/02; never copies A/B/C/D pages."""
from __future__ import annotations
import hashlib,json,random
from datetime import datetime,timezone
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont,ImageFilter

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"evaluation_results/router_v4/remediation_01"; RNG=random.Random(7104)
BUCKETS=["CMS_ANCHOR_LOSS","CMS_GEOMETRY_SHIFT","CMS_MIXED_SHIFT","UB_ANCHOR_LOSS","UB_GEOMETRY_SHIFT","UB_SERVICE_TABLE_SHIFT","UB_HEADER_LOSS","UB_MIXED_SHIFT","CUSTOM_STRUCTURED_VARIANTS","NON_CLAIM_VARIANTS"]
def font(n):
    try:return ImageFont.truetype("C:/Windows/Fonts/tahoma.ttf",n)
    except OSError:return ImageFont.load_default()
def raster_one(bucket,i):
    standard=bucket.startswith(("CMS","UB")); truth="CMS1500" if bucket.startswith("CMS") else "UB04" if bucket.startswith("UB") else "UNKNOWN_STRUCTURED" if bucket.startswith("CUSTOM") else "NON_CLAIM"
    canvas=Image.new("L",(1450,1900),255); d=ImageDraw.Draw(canvas); left=120+(i%5)*25; top=135+(i%4)*32; right=1320-(i%3)*35; bottom=1760-(i%4)*25
    if standard:
      rows=9 if truth=="CMS1500" else 15; cols=6 if truth=="CMS1500" else 9
      for y in np.linspace(top,bottom,rows+1): d.line((left,int(y),right,int(y)),fill=35,width=2)
      for x in np.linspace(left,right,cols+1): d.line((int(x),top,int(x),bottom),fill=35,width=2)
      cms=["HEALTH INSURANCE CLAIM FORM","PATIENTS NAME","INSURED ID NUMBER","DIAGNOSIS OR NATURE OF ILLNESS","FEDERAL TAX ID"]
      ub=["TYPE OF BILL","STATEMENT COVERS","PATIENT CONTROL","PRINCIPAL DIAGN0SIS","REVENUE CODE","HCPCS","UNITS","TOTAL CHARGES"]
      labels=cms if truth=="CMS1500" else ub
      for n,s in enumerate(labels):
        if "HEADER_LOSS" in bucket and n==0:continue
        if "ANCHOR_LOSS" in bucket and n%2==0:s=" ".join(s[j:j+max(3,len(s)//2)] for j in range(0,len(s),max(3,len(s)//2)))
        d.text((left+12,top+18+n*150),s,font=font(18),fill=0)
    elif truth=="UNKNOWN_STRUCTURED":
      d.text((left,top),"SPECIALTY MEDICAL ACCOUNT",font=font(26),fill=0)
      for n in range(12): d.rectangle((left,top+80+n*92,right,top+150+n*92),outline=0,width=2); d.text((left+15,top+100+n*92),f"FIELD {n+1}: VALUE {i:03}-{n:02}  ${n+20}.00",font=font(17),fill=0)
    else:
      d.text((left,top),"ADMINISTRATIVE MEMORANDUM",font=font(27),fill=0)
      d.text((left,top+55),"PATIENT NPI PROVIDER DIAGNOSIS HCPCS CHARGES SERVICE DATE",font=font(15),fill=0)
      for n in range(12): d.text((left,top+130+n*55),f"General correspondence paragraph {n+1}; no claim submitted. Ref {i:03}.",font=font(17),fill=0)
    if "GEOMETRY" in bucket or "MIXED" in bucket: canvas=canvas.crop((55+(i%3)*25,35,1400,1870)).resize((1450,1900))
    if "ANCHOR" in bucket or "MIXED" in bucket: canvas=canvas.filter(ImageFilter.GaussianBlur(.65))
    return canvas,truth
def raster_two(bucket,i):
    image,truth=raster_one(bucket,i); a=np.asarray(image); a=cv2.resize(a,(1180,1680),interpolation=cv2.INTER_AREA)
    if i%2: a=cv2.copyMakeBorder(a,70,30,110,45,cv2.BORDER_CONSTANT,value=255)
    cv2.putText(a,f"R2-{i:03}",(max(10,a.shape[1]-180),a.shape[0]-25),cv2.FONT_HERSHEY_SIMPLEX,.45,0,1,cv2.LINE_AA)
    return Image.fromarray(a),truth
def generate():
    OUT.mkdir(parents=True,exist_ok=True); now=datetime.now(timezone.utc).isoformat(); docs=[]
    for bucket in BUCKETS:
      for i in range(20):
        renderer="PIL_TAHOMA_CONTENT_FRAMED_V1" if i<10 else "OPENCV_RESAMPLED_PADDED_V1"; image,truth=(raster_one if i<10 else raster_two)(bucket,i)
        name=f"{bucket.lower()}_{i:03}.png"; path=OUT/name; image.save(path)
        docs.append({"document_id":name[:-4],"file":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"truth":truth,"quality_bucket":"REMEDIATION","failure_bucket":bucket,"source_family":"INDEPENDENT_FAILURE_REPRODUCTION","renderer_family":renderer,"degradation_family":bucket,"template_version":"remediation-layout-v1","dpi":200 if i<10 else 165,"page_dimensions":list(image.size),"scan_type":"OFFICE_SCAN" if i%2 else "DIGITAL","created_at":now})
    value={"dataset_id":"ROUTING_DEV_V4_REMEDIATION_01","dataset_version":"1.0.0","generator_version":"remediation-independent-v1","created_at":now,"document_count":len(docs),"contains_phi":False,"derived_from_v4_abcd_pixels":False,"documents":docs}
    (OUT/"manifest.json").write_text(json.dumps(value,indent=2),"utf-8"); return value
if __name__=="__main__": print(json.dumps({k:v for k,v in generate().items() if k!="documents"},indent=2))
