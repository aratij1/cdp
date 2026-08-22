from __future__ import annotations
import hashlib,json,time
from pathlib import Path
import numpy as np
from PIL import Image
from .contracts import VisualRouteEvidence
from .features import VISUAL_FEATURE_VERSION,extract_visual_features
class VisualEvidenceInference:
    def __init__(self,artifact_dir:Path):
      self.path=Path(artifact_dir);self.metadata=json.loads((self.path/"metadata.json").read_text("utf-8"));model=self.path/self.metadata["model_file"]
      if self.metadata["feature_version"]!=VISUAL_FEATURE_VERSION:raise ValueError("visual feature version mismatch")
      if hashlib.sha256(model.read_bytes()).hexdigest()!=self.metadata["model_sha256"]:raise ValueError("visual model hash mismatch")
      import joblib
      self.model=joblib.load(model)
    def predict(self,image:Image.Image):
      start=time.perf_counter();x=extract_visual_features(image).reshape(1,-1);probs=self.model.predict_proba(x)[0];ms=(time.perf_counter()-start)*1000
      return [VisualRouteEvidence(family=f,probability=float(p),model_version=self.metadata["model_version"],feature_version=VISUAL_FEATURE_VERSION,explanation_codes=["LOW_RESOLUTION_PAGE_STRUCTURE"]) for f,p in zip(self.model.classes_,probs)],ms
