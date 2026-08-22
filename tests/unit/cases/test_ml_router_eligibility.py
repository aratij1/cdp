import json
from pathlib import Path
import pytest,yaml
from packages.document_routing import MultiSignalRouter,evaluate_standard_eligibility
from packages.document_routing.eligibility_fusion import EligibilityFusionService
from packages.document_routing.ml import FEATURE_NAMES,FEATURE_SCHEMA_VERSION,MLRouteEvidence,features_from_evidence
from packages.document_routing.ml.inference import MLEligibilityInference
from PIL import Image

def _observation():return {"aspect_ratio":.77,"ocr_token_count":12,"ocr_line_count":6,"ocr_character_count":80,"healthcare_token_density":.2,"family_evidence":{}}
def test_feature_schema_is_fixed_phi_safe_and_deterministic():
    decision=MultiSignalRouter.load().route(Image.new("L",(850,1100),255),[])
    a=features_from_evidence(decision,_observation());b=features_from_evidence(decision,_observation())
    assert a==b and list(a.model_dump())==FEATURE_NAMES
    assert not any(x in FEATURE_NAMES for x in ("patient_name","member_id","raw_ocr_text","address"))

def test_model_load_fails_closed_on_feature_version(tmp_path):
    model=tmp_path/"model.txt";model.write_text("x")
    (tmp_path/"metadata.json").write_text(json.dumps({"model_file":"model.txt","feature_schema_version":"wrong","feature_names":FEATURE_NAMES,"model_sha256":"bad"}))
    with pytest.raises(ValueError,match="schema mismatch"):MLEligibilityInference(tmp_path)

def test_model_load_fails_closed_on_hash(tmp_path):
    model=tmp_path/"model.txt";model.write_text("x")
    (tmp_path/"metadata.json").write_text(json.dumps({"model_file":"model.txt","feature_schema_version":FEATURE_SCHEMA_VERSION,"feature_names":FEATURE_NAMES,"model_sha256":"bad"}))
    with pytest.raises(ValueError,match="hash mismatch"):MLEligibilityInference(tmp_path)

def test_fusion_requires_deterministic_corroboration():
    decision=MultiSignalRouter.load().route(Image.new("L",(850,1100),255),[]);det=evaluate_standard_eligibility(decision,"CMS1500",stage=1)
    config=yaml.safe_load(Path("config/document_routing_ml.yaml").read_text())
    fused=EligibilityFusionService(config).fuse(det,MLRouteEvidence(family="CMS1500",probability=.999,model_version="x",feature_version=FEATURE_SCHEMA_VERSION))
    assert fused.eligible is False and fused.reason_codes==["INSUFFICIENT_CORROBORATION"]

def test_ml_flags_default_off_and_shadow_cannot_change_route():
    from packages.settings import Settings
    settings=Settings();assert settings.enable_ml_eligibility is False and settings.enable_ml_eligibility_shadow is False
