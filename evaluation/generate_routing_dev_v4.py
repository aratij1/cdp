"""Generate four PHI-free, attributable Router V4 development partitions."""
from __future__ import annotations
import cv2,hashlib,json,random
import numpy as np
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw,ImageEnhance,ImageFilter,ImageFont

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"evaluation_results/router_v4/datasets"; SEED=7413
BUCKETS=["CLEAN","OFFICE_SCAN","FAX","PHOTOCOPY","LOW_DPI","HIGH_DPI","LOW_CONTRAST","JPEG_COMPRESSION","NOISE","SKEW","ROTATION","PERSPECTIVE","EDGE_CLIPPING","LINE_FADING","UNEVEN_ILLUMINATION","PARTIAL_HEADER_LOSS","PARTIAL_FOOTER_LOSS"]
def _font(size,b=False):
    names=["C:/Windows/Fonts/arialbd.ttf" if b else "C:/Windows/Fonts/arial.ttf","C:/Windows/Fonts/calibri.ttf"]
    for n in names:
        try:return ImageFont.truetype(n,size)
        except OSError:pass
    return ImageFont.load_default()
def _pil_form(family,i,w=1275,h=1650):
    im=Image.new("L",(w,h),255); d=ImageDraw.Draw(im); margin=45+(i%5)*4
    title="HEALTH INSURANCE CLAIM FORM" if family=="CMS1500" else "INSTITUTIONAL CLAIM"
    d.text((margin,25),title,font=_font(27,True),fill=0)
    if family=="CMS1500": labels=["PATIENTS NAME","INSURED ID NUMBER","DIAGNOSIS OR NATURE OF ILLNESS","FEDERAL TAX ID","SERVICE DATE","PROCEDURE","CHARGES"] ; rows=8
    else: labels=["PATIENT CONTROL","TYPE OF BILL","STATEMENT COVERS","PRINCIPAL DIAGNOSIS","REVENUE CODE","HCPCS","UNITS","TOTAL CHARGES"]; rows=13
    top=95
    for y in range(top,h-90,max(55,(h-190)//rows)): d.line((margin,y,w-margin,y),fill=30,width=1+i%3)
    cols=6 if family=="CMS1500" else 8
    for x in np.linspace(margin,w-margin,cols+1): d.line((int(x),top,int(x),h-90),fill=30,width=1+i%2)
    for j,label in enumerate(labels): d.text((margin+10,(top+20+j*145)%(h-150)),label,font=_font(17),fill=0)
    d.text((margin+230,top+20),f"ALEX TEST {i:03d}",font=_font(17),fill=0)
    return im
def _cv_form(family,i):
    h,w=1728,1224; a=np.full((h,w),255,np.uint8); thick=1+(i%2)
    title="1500 HEALTH INSURANCE CLAIM" if family=="CMS1500" else "UNIFORM BILLING INSTITUTIONAL"
    cv2.putText(a,title,(55,55),cv2.FONT_HERSHEY_DUPLEX,.75,0,1,cv2.LINE_AA)
    cv2.putText(a,f"TEST CLAIM {i:05d}",(w-300,82),cv2.FONT_HERSHEY_SIMPLEX,.42,0,1,cv2.LINE_AA)
    rows=9 if family=="CMS1500" else 15; cols=5 if family=="CMS1500" else 9
    for y in np.linspace(95,h-70,rows+1): cv2.line(a,(35,int(y)),(w-35,int(y)),30,thick)
    for x in np.linspace(35,w-35,cols+1): cv2.line(a,(int(x),95),(int(x),h-70),30,thick)
    labels=("PATIENT NAME|INSURED ID NUMBER|DIAGNOSIS|FEDERAL TAX ID|PROCEDURE|CHARGES" if family=="CMS1500" else "PATIENT CONTROL|TYPE OF BILL|STATEMENT COVERS|REVENUE CODE|HCPCS|SERVICE DATE|UNITS|TOTAL CHARGES").split("|")
    for j,s in enumerate(labels): cv2.putText(a,s,(48,125+j*120),cv2.FONT_HERSHEY_SIMPLEX,.46,0,1,cv2.LINE_AA)
    return Image.fromarray(a)
def _custom(kind,i):
    im=Image.new("L",(1100,1450),255); d=ImageDraw.Draw(im); healthcare="PATIENT  NPI  PROVIDER  DIAGNOSIS  HCPCS  CHARGES  SERVICE DATE"
    title={"UNKNOWN_STRUCTURED":"ITEMIZED MEDICAL INVOICE","UNKNOWN_UNSTRUCTURED":"CLINICAL NOTE ATTACHMENT","NON_CLAIM":"ADMINISTRATIVE CORRESPONDENCE"}[kind]
    d.text((60,45),title,font=_font(28,True),fill=0); d.text((60,105),healthcare,font=_font(15),fill=0)
    d.text((820,45),f"TEST {i:04d}",font=_font(14),fill=0)
    if kind=="UNKNOWN_STRUCTURED":
        for y in range(190,1180,85): d.rectangle((55,y,1045,y+65),outline=0,width=2); d.text((70,y+18),f"Service {y//85}:  9921{i%10}   ${20+i%80}.00",font=_font(17),fill=0)
    else:
        for n in range(10): d.text((70,210+n*65),f"{title.title()} paragraph {n+1}. Reference information only.",font=_font(18),fill=0)
    return im
def _degrade(im,bucket,i):
    if bucket=="CLEAN":return im
    if bucket in {"OFFICE_SCAN","PHOTOCOPY"}: return ImageEnhance.Contrast(im.filter(ImageFilter.GaussianBlur(.4))).enhance(.8)
    if bucket=="FAX": return im.resize((850,1100)).point(lambda x:255 if x>165 else 0).resize(im.size)
    if bucket=="LOW_DPI": return im.resize((638,825)).resize(im.size)
    if bucket=="HIGH_DPI": return im.resize((1912,2475))
    if bucket=="LOW_CONTRAST": return ImageEnhance.Contrast(im).enhance(.35)
    if bucket=="JPEG_COMPRESSION":
        import io; b=io.BytesIO(); im.save(b,"JPEG",quality=25); b.seek(0); return Image.open(b).copy()
    if bucket=="NOISE":
        a=np.array(im).astype(np.int16); rng=np.random.default_rng(SEED+i); return Image.fromarray(np.clip(a+rng.normal(0,18,a.shape),0,255).astype(np.uint8))
    if bucket in {"SKEW","ROTATION"}: return im.rotate(2.2 if bucket=="SKEW" else -3.0,fillcolor=255)
    if bucket=="PERSPECTIVE":
        a=np.array(im); h,w=a.shape; m=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[0,h],[w,h]]),np.float32([[18,5],[w-8,18],[4,h-10],[w-22,h-3]])); return Image.fromarray(cv2.warpPerspective(a,m,(w,h),borderValue=255))
    a=np.array(im).copy(); h,w=a.shape
    if bucket=="EDGE_CLIPPING": a[:,:35]=255; a[:,-35:]=255
    elif bucket=="LINE_FADING": a=np.where(a<100,115,a).astype(np.uint8)
    elif bucket=="UNEVEN_ILLUMINATION": a=np.clip(a.astype(float)*np.linspace(.65,1.05,w)[None,:],0,255).astype(np.uint8)
    elif bucket=="PARTIAL_HEADER_LOSS": a[:int(h*.1)]=255
    elif bucket=="PARTIAL_FOOTER_LOSS": a[int(h*.88):]=255
    return Image.fromarray(a)
def _save(partition,records,attestation=None):
    path=OUT/partition; path.mkdir(parents=True,exist_ok=True); now=datetime.now(timezone.utc).isoformat(); rows=[]
    for name,image,meta in records:
        target=path/name; image.save(target); rows.append({"document_id":name[:-4],"file":name,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"created_at":now,"dataset_version":"4.0.0",**meta})
    manifest={"dataset_id":partition,"dataset_version":"4.0.0","created_at":now,"document_count":len(rows),"contains_phi":False,"source_independence_attestation":attestation,"documents":rows}
    (path/"manifest.json").write_text(json.dumps(manifest,indent=2),"utf-8"); return manifest
def generate():
    rng=random.Random(SEED); manifests=[]
    a=[]; b=[]
    for family in ("CMS1500","UB04"):
      for i in range(105):
        a.append((f"a_{family}_{i:03}.png",_degrade(_pil_form(family,i),rng.choice(["CLEAN","OFFICE_SCAN","LOW_CONTRAST"]),i),{"truth":family,"quality_bucket":"NORMAL","source_family":"PIL_PRIMARY","renderer_family":"PIL_TRUETYPE_GRID_V1","generator_id":"router-v4-a-v1","degradation_family":"NORMAL_SCAN"}))
        b.append((f"b_{family}_{i:03}.png",_degrade(_cv_form(family,i),rng.choice(["CLEAN","PHOTOCOPY","JPEG_COMPRESSION"]),i),{"truth":family,"quality_bucket":"NORMAL","source_family":"OPENCV_ALTERNATE","renderer_family":"OPENCV_HERSHEY_V1","generator_id":"router-v4-b-v1","degradation_family":"ALTERNATE_SCAN"}))
    manifests.append(_save("ROUTING_DEV_V4_A",a)); manifests.append(_save("ROUTING_DEV_V4_B",b,{"independent":True,"reason":"OpenCV/Hershey renderer, dimensions, font metrics, rasterization and scan transforms differ from PIL/TrueType V4-A."}))
    c=[]
    for truth,count in (("UNKNOWN_STRUCTURED",70),("UNKNOWN_UNSTRUCTURED",40),("NON_CLAIM",70)):
      for i in range(count): c.append((f"c_{truth}_{i:03}.png",_custom(truth,i),{"truth":truth,"quality_bucket":"MIXED","source_family":"ADVERSARIAL_CUSTOM","renderer_family":"PIL_DOCUMENT_V2","generator_id":"router-v4-c-v1","degradation_family":"CLEAN"}))
    manifests.append(_save("ROUTING_DEV_V4_C",c))
    d=[]
    for family in ("CMS1500","UB04"):
      for bi,bucket in enumerate(BUCKETS):
       for i in range(4): d.append((f"d_{family}_{bucket}_{i}.png",_degrade(_cv_form(family,1000+bi*4+i),bucket,bi*4+i),{"truth":family,"quality_bucket":"DEGRADED","source_family":"STRESS_PIPELINE","renderer_family":"OPENCV_HERSHEY_DEGRADATION_V1","generator_id":"router-v4-d-v1","degradation_family":bucket}))
    manifests.append(_save("ROUTING_DEV_V4_D",d)); return manifests
if __name__=="__main__": print(json.dumps([{k:v for k,v in x.items() if k!="documents"} for x in generate()],indent=2))
