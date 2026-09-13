"""Bounded, source-only local alignment for registered CMS-1500 value cells."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import cv2
import numpy as np

@dataclass(frozen=True)
class LocalAlignmentResult:
    refined_bbox: tuple[int,int,int,int]
    status: str
    score: float
    x_offset: int
    y_offset: int
    width_change: int
    height_change: int
    reason_codes: tuple[str, ...] = ()

_ALLOWED = {"REFINED", "CANONICAL_ACCEPTED", "AMBIGUOUS", "NO_INK", "REFINEMENT_REJECTED"}

def _xy(box: Any) -> tuple[int,int,int,int]:
    if hasattr(box, "x0"): return tuple(round(getattr(box,k)) for k in ("x0","y0","x1","y1"))
    if isinstance(box, dict): return tuple(round(box[k]) for k in ("x0","y0","x1","y1"))
    return tuple(round(v) for v in box)

def refine_value_region(image: Any, field_name: str, canonical_bbox: Any, safe_cell_bbox: Any) -> LocalAlignmentResult:
    """Estimate an ink envelope while remaining inside the public safe cell."""
    del field_name
    c = _xy(canonical_bbox); s = _xy(safe_cell_bbox)
    x0,y0,x1,y1 = max(c[0],s[0]),max(c[1],s[1]),min(c[2],s[2]),min(c[3],s[3])
    if x1 <= x0 or y1 <= y0: return LocalAlignmentResult(c,"REFINEMENT_REJECTED",0,0,0,0,0,("INVALID_BOUNDS",))
    arr = np.asarray(image.convert("L") if hasattr(image,"convert") else image)
    arr = arr[max(0,y0):min(arr.shape[0],y1), max(0,x0):min(arr.shape[1],x1)]
    if arr.size == 0: return LocalAlignmentResult(c,"NO_INK",0,0,0,0,0,("EMPTY_REGION",))
    ink = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # Suppress long printed rules; retain connected text components.
    hker=cv2.getStructuringElement(cv2.MORPH_RECT,(max(8,arr.shape[1]//3),1))
    vker=cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(8,arr.shape[0]//2)))
    lines=cv2.bitwise_or(cv2.morphologyEx(ink,cv2.MORPH_OPEN,hker),cv2.morphologyEx(ink,cv2.MORPH_OPEN,vker))
    text=cv2.bitwise_and(ink,cv2.bitwise_not(lines))
    ys,xs=np.where(text>0)
    if len(xs)<2: return LocalAlignmentResult(c,"NO_INK",0,0,0,0,0,("NO_TEXT_INK",))
    ex0,ex1=int(xs.min()),int(xs.max()+1); ey0,ey1=int(ys.min()),int(ys.max()+1)
    # Keep a small baseline margin and never leave the approved cell.
    rx0=max(x0,x0+ex0-2); ry0=max(y0,y0+ey0-2); rx1=min(x1,x0+ex1+2); ry1=min(y1,y0+ey1+2)
    refined=(rx0,ry0,rx1,ry1)
    score=min(1.0,float(len(xs))/(arr.shape[0]*arr.shape[1])*20.0)
    if refined == c: return LocalAlignmentResult(refined,"CANONICAL_ACCEPTED",score,0,0,0,0,("INK_ENVELOPE_MATCH",))
    return LocalAlignmentResult(refined,"REFINED",score,rx0-c[0],ry0-c[1],(rx1-rx0)-(c[2]-c[0]),(ry1-ry0)-(c[3]-c[1]),("TEXT_INK_ENVELOPE",))

__all__=["LocalAlignmentResult","refine_value_region"]
