from __future__ import annotations
import argparse,hashlib,json,statistics,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
import joblib,numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix,precision_recall_fscore_support
from packages.document_routing.visual.features import VISUAL_FEATURE_VERSION,extract_visual_features
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/"evaluation_results/router_visual_v1";MODELS=ROOT/"models/router_visual"
def load(source):return json.loads((DATA/f"{source}.json").read_text("utf-8"))["documents"]
def run(train_source,test_source):
 train,test=load(train_source),load(test_source);x=np.array([extract_visual_features(Image.open(r["path"])) for r in train]);y=np.array([r["label"] for r in train]);model=LogisticRegression(max_iter=500,C=1.0,class_weight="balanced",random_state=7417,n_jobs=1).fit(x,y)
 out=MODELS/f"hog_logistic_{train_source.lower()}_v1";out.mkdir(parents=True,exist_ok=True);path=out/"model.joblib";joblib.dump(model,path,compress=3)
 meta={"model_id":out.name,"model_type":"HOG_LOGISTIC","model_version":"1.0.0","feature_version":VISUAL_FEATURE_VERSION,"training_source":train_source,"classes":list(model.classes_),"model_file":path.name,"model_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"model_size_bytes":path.stat().st_size,"git_sha":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True).stdout.strip(),"created_at":datetime.now(timezone.utc).isoformat(),"status":"EXPERIMENTAL"};(out/"metadata.json").write_text(json.dumps(meta,indent=2),"utf-8")
 probs=[];lat=[]
 for r in test:
  start=time.perf_counter();v=extract_visual_features(Image.open(r["path"]));probs.append(model.predict_proba(v.reshape(1,-1))[0]);lat.append((time.perf_counter()-start)*1000)
 pred=model.classes_[np.argmax(probs,axis=1)];truth=np.array([r["label"] for r in test]);p,re,f,_=precision_recall_fscore_support(truth,pred,labels=model.classes_,zero_division=0)
 result={"train_source":train_source,"test_source":test_source,"documents":len(test),"accuracy":float(np.mean(pred==truth)),"per_family":{c:{"precision":float(p[i]),"recall":float(re[i]),"f1":float(f[i])} for i,c in enumerate(model.classes_)},"confusion_matrix":confusion_matrix(truth,pred,labels=model.classes_).tolist(),"latency_ms":{"p50":statistics.median(lat),"p95":sorted(lat)[int(len(lat)*.95)-1]},"model_size_bytes":path.stat().st_size,"gpu_required":False,"cloud_cost":0}
 (DATA/f"result_{train_source.lower()}_to_{test_source.lower()}.json").write_text(json.dumps(result,indent=2),"utf-8");return result
if __name__=="__main__":p=argparse.ArgumentParser();p.add_argument("train");p.add_argument("test");a=p.parse_args();print(json.dumps(run(a.train,a.test),indent=2))
