"""One-page shared feature boundary for deterministic Router V4 scorers."""
from __future__ import annotations
from dataclasses import dataclass
import re
import cv2,numpy as np
from PIL import Image
from .router import TextGeometry
from .structural import StructuralDescriptors,describe_structure

ANCHOR_GROUPS={
 "CMS1500":["health insurance claim form","insured id number","patients name","diagnosis or nature of illness","federal tax id"],
 "UB04":["type of bill","patient control","statement covers","principal diagnosis","revenue code","hcpcs","service date","units","total charges"]}
CONFUSIONS=str.maketrans({"0":"o","1":"i","5":"s","8":"b"})
@dataclass(frozen=True)
class NormalizedPageGeometry:
    content_x0:int;content_y0:int;content_x1:int;content_y1:int
    effective_width:int;effective_height:int;rotation:float=0.0;skew:float=0.0
@dataclass(frozen=True)
class NormalizedLine:
    text:str;x0:float;y0:float;x1:float;y1:float
@dataclass(frozen=True)
class TokenGroupMatch:
    anchor_id:str;family:str;observed_tokens:tuple[str,...];match_quality:float;bbox:tuple[float,float,float,float];reconstructed:bool
@dataclass(frozen=True)
class RouterFeatureBundle:
    image:Image.Image;content_image:Image.Image;geometry:NormalizedPageGeometry
    ocr_lines:tuple[TextGeometry,...];normalized_lines:tuple[NormalizedLine,...];virtual_lines:tuple[TextGeometry,...]
    enriched_lines:tuple[TextGeometry,...];enriched_original_lines:tuple[TextGeometry,...];token_group_matches:tuple[TokenGroupMatch,...]
    structural:StructuralDescriptors
def _token(value):return re.sub(r"[^a-z]","",value.casefold().translate(CONFUSIONS))
def detect_content_bounds(image:Image.Image)->NormalizedPageGeometry:
    a=np.asarray(image.convert("L")); ink=cv2.threshold(a,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    kernel=cv2.getStructuringElement(cv2.MORPH_RECT,(5,5)); joined=cv2.morphologyEx(ink,cv2.MORPH_CLOSE,kernel)
    ys,xs=np.nonzero(joined)
    if not len(xs):return NormalizedPageGeometry(0,0,image.width,image.height,image.width,image.height)
    pad=max(4,int(min(image.size)*.006)); x0=max(0,int(np.percentile(xs,.2))-pad);x1=min(image.width,int(np.percentile(xs,99.8))+pad)
    y0=max(0,int(np.percentile(ys,.2))-pad);y1=min(image.height,int(np.percentile(ys,99.8))+pad)
    if x1-x0<image.width*.35 or y1-y0<image.height*.35:return NormalizedPageGeometry(0,0,image.width,image.height,image.width,image.height)
    return NormalizedPageGeometry(x0,y0,x1,y1,x1-x0,y1-y0)
def _normalize_lines(lines,geometry):
    return tuple(NormalizedLine(x.text,(x.x0-geometry.content_x0)/geometry.effective_width,(x.y0-geometry.content_y0)/geometry.effective_height,(x.x1-geometry.content_x0)/geometry.effective_width,(x.y1-geometry.content_y0)/geometry.effective_height) for x in lines)
def recover_token_groups(lines:tuple[NormalizedLine,...])->tuple[tuple[NormalizedLine,...],tuple[TokenGroupMatch,...]]:
    ordered=sorted(lines,key=lambda x:(x.y0,x.x0)); tokens=[]
    for line in ordered:
      for raw in re.findall(r"[A-Za-z0-9]+",line.text):tokens.append((_token(raw),line))
    enriched=list(lines);matches=[]
    for family,anchors in ANCHOR_GROUPS.items():
      for anchor in anchors:
        wanted=[_token(x) for x in anchor.split()]; best=None
        # Bounded ordered clustering tolerates one split token and one corrupt character, never a lone generic token.
        for start in range(len(tokens)):
          selected=[];pos=start
          for expected in wanted:
            combined="";chosen=[]
            for j in range(pos,min(len(tokens),pos+4)):
              combined+=tokens[j][0];chosen.append(tokens[j])
              distance=sum(a!=b for a,b in zip(combined,expected))+abs(len(combined)-len(expected))
              if combined==expected or (len(expected)>=5 and distance<=1):selected+=chosen;pos=j+1;break
              if len(combined)>len(expected)+1:break
            else:break
          if len(selected)>=len(wanted):
            span=max(x[1].y1 for x in selected)-min(x[1].y0 for x in selected)
            if span<=.14:
              quality=max(.75,1-sum(_token(x[0]) not in wanted for x in selected)*.05);best=(selected,quality);break
        if best:
          selected,quality=best;b=(min(x[1].x0 for x in selected),min(x[1].y0 for x in selected),max(x[1].x1 for x in selected),max(x[1].y1 for x in selected))
          matches.append(TokenGroupMatch(anchor,family,tuple(x[0] for x in selected),quality,b,True));enriched.append(NormalizedLine(anchor,*b))
    return tuple(enriched),tuple(matches)
def build_router_feature_bundle(image:Image.Image,lines:list[TextGeometry])->RouterFeatureBundle:
    geometry=detect_content_bounds(image); normalized=_normalize_lines(lines,geometry); enriched,matches=recover_token_groups(normalized)
    crop=image.crop((geometry.content_x0,geometry.content_y0,geometry.content_x1,geometry.content_y1))
    # NormalizedLine coordinates are mapped into this virtual content page so legacy scorers consume content-relative geometry.
    virtual=tuple(NormalizedLine(x.text,x.x0*crop.width,x.y0*crop.height,x.x1*crop.width,x.y1*crop.height) for x in enriched)
    base_virtual=tuple(NormalizedLine(x.text,x.x0*crop.width,x.y0*crop.height,x.x1*crop.width,x.y1*crop.height) for x in normalized)
    original_enriched=list(lines)
    for match in matches:
        x0,y0,x1,y1=match.bbox
        original_enriched.append(NormalizedLine(match.anchor_id,x0*geometry.effective_width+geometry.content_x0,
            y0*geometry.effective_height+geometry.content_y0,x1*geometry.effective_width+geometry.content_x0,
            y1*geometry.effective_height+geometry.content_y0))
    return RouterFeatureBundle(image,crop,geometry,tuple(lines),normalized,base_virtual,virtual,tuple(original_enriched),matches,describe_structure(crop))
