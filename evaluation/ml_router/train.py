from __future__ import annotations
import argparse,hashlib,json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from packages.document_routing.ml.features import FEATURE_NAMES,FEATURE_SCHEMA_VERSION
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/"evaluation_results/router_ml_eligibility_v1";MODELS=ROOT/"models/router_eligibility";CLASSES=["CMS1500","UB04","UNKNOWN_STRUCTURED","NON_CLAIM"]
def rows(source,split=None):
 v=[json.loads(x) for x in (DATA/f"{source}.jsonl").read_text().splitlines()];return [x for x in v if split is None or x["split"] in split]
def train(model_type,source):
 values=rows(source,{"train","calibration"});x=np.array([[r["features"][f] for f in FEATURE_NAMES] for r in values]);y=np.array([CLASSES.index(r["label"]) for r in values]);params={"seed":7416,"n_estimators":80,"max_depth":4,"n_jobs":1}
 if model_type=="lightgbm":
  import lightgbm as lgb;model=lgb.LGBMClassifier(objective="multiclass",num_class=len(CLASSES),learning_rate=.05,num_leaves=15,verbosity=-1,**params);model.fit(x,y,feature_name=FEATURE_NAMES);importance=dict(zip(FEATURE_NAMES,map(float,model.feature_importances_)));ext="txt"
 else:
  import xgboost as xgb;model=xgb.XGBClassifier(objective="multi:softprob",num_class=len(CLASSES),learning_rate=.05,verbosity=0,**params);model.fit(x,y);importance=dict(zip(FEATURE_NAMES,map(float,model.feature_importances_)));ext="json"
 out=MODELS/f"{model_type}_{source.lower()}_v1";out.mkdir(parents=True,exist_ok=True);path=out/f"model.{ext}"
 if model_type=="lightgbm":model.booster_.save_model(str(path))
 else:model.get_booster().feature_names=FEATURE_NAMES;model.get_booster().save_model(path)
 metadata={"model_id":out.name,"model_type":model_type,"model_version":"1.0.0","git_sha":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True).stdout.strip(),"training_dataset":source,"training_hash":hashlib.sha256((DATA/f"{source}.jsonl").read_bytes()).hexdigest(),"feature_schema_version":FEATURE_SCHEMA_VERSION,"feature_names":FEATURE_NAMES,"hyperparameters":params,"classes":CLASSES,"model_file":path.name,"model_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"model_size_bytes":path.stat().st_size,"feature_importance":importance,"created_at":datetime.now(timezone.utc).isoformat(),"status":"EXPERIMENTAL"};(out/"metadata.json").write_text(json.dumps(metadata,indent=2),"utf-8");return out
if __name__=="__main__":p=argparse.ArgumentParser();p.add_argument("model",choices=["lightgbm","xgboost"]);p.add_argument("source");a=p.parse_args();print(train(a.model,a.source))
