"""Lazy, hash-governed inference; fails closed without compatible artifacts."""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from .contracts import MLRouteEvidence
from .features import FEATURE_NAMES,FEATURE_SCHEMA_VERSION,MLEligibilityFeatures
class MLEligibilityInference:
    def __init__(self,artifact_dir:Path):
      self.path=Path(artifact_dir);self.metadata=json.loads((self.path/"metadata.json").read_text("utf-8"));model_path=self.path/self.metadata["model_file"]
      if self.metadata["feature_schema_version"]!=FEATURE_SCHEMA_VERSION or self.metadata["feature_names"]!=FEATURE_NAMES:raise ValueError("ML eligibility feature schema mismatch")
      if hashlib.sha256(model_path.read_bytes()).hexdigest()!=self.metadata["model_sha256"]:raise ValueError("ML eligibility model hash mismatch")
      if self.metadata["model_type"]=="lightgbm":
        import lightgbm as lgb;self.model=lgb.Booster(model_file=str(model_path))
      elif self.metadata["model_type"]=="xgboost":
        import xgboost as xgb;self.model=xgb.Booster();self.model.load_model(model_path)
      else:raise ValueError("unsupported model type")
    def predict(self,features:MLEligibilityFeatures)->tuple[list[MLRouteEvidence],float]:
      import numpy as np;start=time.perf_counter();x=np.array([[getattr(features,k) for k in FEATURE_NAMES]],dtype=float)
      if self.metadata["model_type"]=="xgboost":
        import xgboost as xgb;probs=self.model.predict(xgb.DMatrix(x,feature_names=FEATURE_NAMES))[0]
      else:probs=self.model.predict(x)[0]
      elapsed=(time.perf_counter()-start)*1000
      importance=self.metadata.get("feature_importance",{});top=sorted(importance,key=importance.get,reverse=True)[:5]
      return [MLRouteEvidence(family=f,probability=float(p),model_version=self.metadata["model_version"],feature_version=FEATURE_SCHEMA_VERSION,top_positive_features=top) for f,p in zip(self.metadata["classes"],probs)],elapsed
