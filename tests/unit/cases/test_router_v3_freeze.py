import json

from evaluation.freeze_router_v3 import freeze


def test_freeze_captures_versions_hashes_and_evaluation_only_mode(tmp_path):
    manifest=freeze("a"*40,tmp_path/"freeze.json")
    assert manifest["router_git_sha"]=="a"*40
    assert len(manifest["router_config_sha256"])==64
    assert len(manifest["development_dataset"]["sha256"])==64
    assert manifest["runtime"]["enable_router_v3_default"] is False
    assert manifest["runtime"]["evaluation_only"] is True
    assert manifest["benchmark"]["promotion"]=="PROMOTE"
