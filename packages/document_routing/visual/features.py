"""Low-resolution PHI-minimizing HOG page embedding contract."""
from __future__ import annotations
from dataclasses import dataclass
import cv2,numpy as np
from PIL import Image
VISUAL_FEATURE_VERSION="page-hog-224-v1"
@dataclass(frozen=True)
class VisualFeatureContract:
    version:str=VISUAL_FEATURE_VERSION;width:int=224;height:int=224;cell:int=16;block:int=32;bins:int=9
def extract_visual_features(image:Image.Image,contract=VisualFeatureContract())->np.ndarray:
    gray=np.asarray(image.convert("L").resize((contract.width,contract.height)),dtype=np.uint8)
    # Normalize illumination; no OCR text or identifiers leave this function.
    gray=cv2.equalizeHist(gray)
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=1);gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=1)
    magnitude,angle=cv2.cartToPolar(gx,gy,angleInDegrees=True);cells=[]
    for y in range(0,224,16):
      for x in range(0,224,16):
        hist=np.zeros(9,np.float32);bins=(angle[y:y+16,x:x+16]%180/20).astype(int);mag=magnitude[y:y+16,x:x+16]
        for b in range(9):hist[b]=mag[bins==b].sum()
        hist/=np.linalg.norm(hist)+1e-6;cells.extend(hist)
    vector=np.asarray(cells,np.float32)
    projections=np.concatenate([np.mean(gray<220,axis=0)[::8],np.mean(gray<220,axis=1)[::8]]).astype(np.float32)
    return np.concatenate([vector,projections])
