"""Generate a new synthetic development-only routing corpus (never a holdout)."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from evaluation.generate_public_synthetic_claims import _font

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"evaluation_data/ROUTING_DEV_V3"
CONDITIONS=("clean","fax","skew","low_contrast","edge_clip")


def _degrade(image,condition):
    if condition=="fax": return image.convert("L").point(lambda x:255 if x>165 else 0).filter(ImageFilter.GaussianBlur(.25)).convert("RGB")
    if condition=="skew": return image.transform(image.size,Image.Transform.AFFINE,(1,.014,-14,0,1,0),fillcolor="white")
    if condition=="low_contrast": return ImageEnhance.Contrast(image).enhance(.48)
    if condition=="edge_clip": return image.crop((12,8,image.width-12,image.height-8)).resize(image.size)
    return image


def _standard(family,index,condition):
    image=Image.new("RGB",(1200,1600),"white"); draw=ImageDraw.Draw(image)
    for y in range(190,1450,65): draw.line((30,y,1170,y),fill=(60,60,60),width=2)
    columns=(30,210,440,700,930,1170) if family=="UB04" else (30,380,760,1170)
    for x in columns: draw.line((x,170,x,1450),fill=(60,60,60),width=2)
    identity=index%3!=0
    if family=="CMS1500":
        if identity: draw.text((320,30),"HEALTH INSURANCE CLAIM FORM",fill="black",font=_font(27))
        labels=((45,250,"PATIENTS NAME"),(700,220,"INSURED ID NUMBER"),
                (60,850,"DIAGNOSIS OR NATURE OF ILLNESS"),(760,1250,"FEDERAL TAX ID"))
    else:
        if identity: draw.text((500,28),"UB-04",fill="black",font=_font(27))
        labels=((830,90,"TYPE OF BILL"),(620,135,"PATIENT CONTROL"),(760,180,"STATEMENT COVERS"),
                (55,520,"REVENUE CODE"),(360,520,"HCPCS"),(690,520,"SERVICE DATE"),
                (870,520,"UNITS"),(945,520,"TOTAL CHARGES"),(70,1120,"PRINCIPAL DIAGNOSIS"))
    for x,y,text in labels: draw.text((x,y),text,fill="black",font=_font(20))
    return _degrade(image,condition)


def _generic(family,index,condition):
    image=Image.new("RGB",(1200,1600),"white"); draw=ImageDraw.Draw(image)
    titles={"CUSTOM_STRUCTURED":"CUSTOM MEDICAL CLAIM SUMMARY","ATTACHMENT":"CLINICAL NOTE ATTACHMENT",
            "ADVERSARIAL":"EXPLANATION OF BENEFITS","NON_CLAIM":"DOCUMENT COVER SHEET"}
    draw.text((55,45),titles[family],fill="black",font=_font(28))
    if family in {"CUSTOM_STRUCTURED","ADVERSARIAL"}:
        labels=("PATIENT","PROVIDER NPI","DIAGNOSIS","SERVICE DATE","HCPCS","CHARGES")
        for row,label in enumerate(labels):
            y=190+row*125; draw.rectangle((50,y,1140,y+80),outline="black",width=2)
            draw.text((70,y+20),f"{label}: DEVELOPMENT VALUE {index}",fill="black",font=_font(19))
    elif family=="ATTACHMENT": draw.multiline_text((60,190),"Provider clinical letter\nPatient progress and laboratory findings\nSupporting correspondence",fill="black",font=_font(21),spacing=25)
    else: draw.multiline_text((60,190),"CORRESPONDENCE MEMORANDUM\nBLANK PAGE SEPARATOR",fill="black",font=_font(21),spacing=25)
    return _degrade(image,condition)


def generate():
    rng=random.Random(73107); images=OUTPUT/"images"; images.mkdir(parents=True,exist_ok=True)
    families=["CMS1500"]*60+["UB04"]*60+["CUSTOM_STRUCTURED"]*30+["ATTACHMENT"]*20+["ADVERSARIAL"]*20+["NON_CLAIM"]*20
    rng.shuffle(families); rows=[]
    for index,family in enumerate(families,1):
        condition=CONDITIONS[index%len(CONDITIONS)]
        image=_standard(family,index,condition) if family in {"CMS1500","UB04"} else _generic(family,index,condition)
        path=images/f"RDEV3-{index:04d}.jpg"; image.save(path,quality=88)
        truth="UNKNOWN_STRUCTURED" if family in {"CUSTOM_STRUCTURED","ADVERSARIAL"} else "UNKNOWN_UNSTRUCTURED" if family=="ATTACHMENT" else family
        rows.append({"document_id":path.stem,"path":str(path.relative_to(OUTPUT)).replace("\\","/"),
                     "truth_route":truth,"source_family":family,"quality_bucket":condition,
                     "identity_expected":family in {"CMS1500","UB04"} and index%3!=0})
    (OUTPUT/"ground_truth.jsonl").write_text("\n".join(json.dumps(x) for x in rows)+"\n","utf-8")
    manifest={"dataset_id":"ROUTING_DEV_V3","development_only":True,"synthetic":True,
              "prohibited_as_holdout":True,"seed":73107,"documents":len(rows),
              "independent_of":["PRODUCTION_HOLDOUT_V1","PRODUCTION_HOLDOUT_V2"]}
    (OUTPUT/"manifest.json").write_text(json.dumps(manifest,indent=2),"utf-8"); return manifest


if __name__=="__main__": print(json.dumps(generate(),indent=2))
