import json
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from packages.document_routing.visual import VisualRouteEvidence,extract_visual_features
from packages.document_routing.visual.inference import VisualEvidenceInference
def test_visual_embedding_is_deterministic_and_fixed_size():
    image=Image.new("L",(850,1100),255);ImageDraw.Draw(image).rectangle((50,50,800,1050),outline=0,width=3)
    a=extract_visual_features(image);b=extract_visual_features(image)
    assert a.shape==b.shape and (a==b).all() and a.ndim==1
def test_visual_contract_cannot_be_route_decision():
    value=VisualRouteEvidence(family="UB04",probability=.8,model_version="x",feature_version="page-hog-224-v1")
    assert not hasattr(value,"route")
def test_visual_loader_fails_closed_on_version(tmp_path):
    (tmp_path/"model.joblib").write_bytes(b"x");(tmp_path/"metadata.json").write_text(json.dumps({"model_file":"model.joblib","feature_version":"wrong","model_sha256":"x"}))
    with pytest.raises(ValueError,match="version mismatch"):VisualEvidenceInference(tmp_path)
def test_visual_flags_default_off():
    from packages.settings import Settings
    s=Settings();assert s.enable_visual_evidence is False and s.enable_visual_evidence_shadow is False
