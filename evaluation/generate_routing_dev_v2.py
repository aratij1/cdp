"""Independent routing recovery corpus; never copies V2 holdout pages."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from evaluation.generate_public_synthetic_claims import _font, _render


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation_data/ROUTING_DEV_V2"
CONDITIONS = ("clean", "fax", "rotation", "skew", "jpeg", "edge_clip", "low_contrast")


def _degrade(image: Image.Image, condition: str) -> Image.Image:
    if condition == "fax":
        return image.convert("L").point(lambda value: 255 if value > 170 else 0).filter(ImageFilter.GaussianBlur(.3)).convert("RGB")
    if condition == "rotation":
        return image.rotate(1.5, fillcolor="white", resample=Image.Resampling.BICUBIC)
    if condition == "skew":
        return image.transform(image.size, Image.Transform.AFFINE, (1,.018,-18,0,1,0), fillcolor="white")
    if condition == "jpeg":
        return image.resize((image.width//2,image.height//2)).resize(image.size)
    if condition == "edge_clip":
        return image.crop((14,10,image.width-12,image.height-10)).resize(image.size)
    if condition == "low_contrast":
        return ImageEnhance.Contrast(image).enhance(.4)
    return image


def _standard(family: str, index: int, condition: str) -> Image.Image:
    image, _, _ = _render(family, index, "clean_scan")
    draw = ImageDraw.Draw(image)
    text = ("HEALTH INSURANCE CLAIM FORM  PATIENTS NAME  INSURED ID NUMBER  FEDERAL TAX ID"
            if family == "CMS1500" else
            "TYPE OF BILL  PATIENT CONTROL  STATEMENT COVERS  PRINCIPAL DIAGNOSIS  REVENUE CODE HCPCS SERVICE DATE UNITS TOTAL CHARGES")
    draw.text((40, 105), text, fill=(20,20,20), font=_font(15))
    return _degrade(image, condition)


def _generic(family: str, index: int, condition: str) -> Image.Image:
    image = Image.new("RGB", (1400,1800), "white"); draw = ImageDraw.Draw(image)
    if family == "CUSTOM_STRUCTURED":
        draw.text((60,50), "PROFESSIONAL MEDICAL CLAIM", fill="black", font=_font(28))
        values = (("PATIENT NAME","TEST PERSON"),("MEMBER ID",f"DEV{index:07d}"),
                  ("PROVIDER NPI","1999999998"),("DIAGNOSIS","Z00.00"),
                  ("PROCEDURE","99213"),("SERVICE DATE","01/15/2026"),("TOTAL CHARGE","125.00"))
        for row,(label,value) in enumerate(values):
            y=170+row*110; draw.rectangle((50,y,1320,y+75),outline="black",width=2)
            draw.text((65,y+15),f"{label}: {value}",fill="black",font=_font(22))
    elif family == "ATTACHMENT":
        draw.text((70,70), "CLAIM ATTACHMENT", fill="black", font=_font(28))
        draw.multiline_text((70,180), "Supporting clinical notes\nPatient received medical services.\nPlease associate with submitted claim.", fill="black", font=_font(22), spacing=20)
    else:
        draw.text((70,70), "DOCUMENT COVER SHEET", fill="black", font=_font(28))
        draw.multiline_text((70,180), "CORRESPONDENCE MEMORANDUM\nThis page contains no claim data.", fill="black", font=_font(22), spacing=20)
    return _degrade(image, condition)


def generate(count: int = 140) -> dict:
    rng = random.Random(72819); images = OUTPUT / "images"; images.mkdir(parents=True,exist_ok=True)
    families = (["CMS1500"]*40 + ["UB04"]*40 + ["CUSTOM_STRUCTURED"]*30 +
                ["ATTACHMENT"]*15 + ["NON_CLAIM"]*15)
    rng.shuffle(families); rows=[]
    for index,family in enumerate(families[:count],1):
        condition=CONDITIONS[(index*3)%len(CONDITIONS)]
        image = (_standard(family,index,condition) if family in {"CMS1500","UB04"}
                 else _generic(family,index,condition))
        path=images/f"RDEV2-{index:04d}.jpg"; image.save(path,quality=72 if condition=="jpeg" else 92)
        rows.append({"document_id":path.stem,"path":str(path.relative_to(OUTPUT)).replace("\\","/"),
                     "truth_route":family,"condition":condition})
    (OUTPUT/"ground_truth.jsonl").write_text("\n".join(json.dumps(row) for row in rows)+"\n","utf-8")
    manifest={"dataset_id":"ROUTING_DEV_V2","development_only":True,
              "independent_of":"PRODUCTION_HOLDOUT_V2_REPRESENTATIVE",
              "seed":72819,"documents":len(rows),"distribution":{family:families.count(family) for family in set(families)}}
    (OUTPUT/"manifest.json").write_text(json.dumps(manifest,indent=2),"utf-8")
    return manifest


if __name__ == "__main__": print(json.dumps(generate(),indent=2))
