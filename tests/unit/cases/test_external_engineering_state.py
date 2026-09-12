"""Synthetic external state and engineering labels; never real patient truth."""
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evaluation import candidate_runtime_freeze as candidate
from evaluation import engineering_review as review
from evaluation import qualification_state as state
from evaluation.engineering_accuracy import measure
from evaluation.track_b_inputs import current_registry, owner_approval


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    root=tmp_path/"private_state"; root.mkdir()
    monkeypatch.setenv(state.STATE_ENV,str(root))
    state.initialize_layout()
    return root


def test_missing_mount_is_unknown_not_zero(monkeypatch):
    monkeypatch.delenv(state.STATE_ENV,raising=False); monkeypatch.delenv(state.DEV_ENV,raising=False)
    assert state.status()["counters"]=="UNKNOWN_NOT_ZERO"
    with pytest.raises(state.StateUnavailable): state.mapped(Path("evaluation_results/qualification_closure/blind_reviews.sqlite3"))


def test_workspace_change_preserves_same_review_database(mounted,tmp_path):
    from packages.real_data_evaluation.blind_workflow import BlindReviewStore
    paths=[state.mapped(tmp_path/name/"evaluation_results/qualification_closure/blind_reviews.sqlite3") for name in ["clone_one","clone_two"]]
    from tests.unit.cases.test_qualification_closure_inputs import annotation
    store=BlindReviewStore(paths[0]); store.save("synthetic-page","synthetic-reader","a"*64,annotation(),complete=True)
    assert paths[0]==paths[1]
    assert len(BlindReviewStore(paths[1]).completed())==1
    assert not (tmp_path/"clone_two").exists()
    from evaluation.qualification_closure import readiness
    left=readiness(tmp_path/"clone_one")
    right=readiness(tmp_path/"clone_two")
    assert left["inputs"]["blind_reviews.sqlite3"]["completed_reviews"]==1
    assert right["inputs"]["blind_reviews.sqlite3"]["completed_reviews"]==1
    assert left["governed_state"]["root_id"]==right["governed_state"]["root_id"]
    assert left["qualification_candidate"]["runtime_candidate_sha"]==candidate.CANDIDATE


def test_wrong_membership_receipt_hash_fails(mounted,tmp_path):
    path=state.mapped(tmp_path/"evaluation_results/qualification_closure/membership_owner_approval.local.json")
    path.write_text(json.dumps({"owner_id":"ashish singh","owner_role":"SOURCE_DATA_OWNER","csv_sha256":"a"*64,
        "approval_reference":"synthetic","policy_id":"synthetic","approved_at":datetime.now(UTC).isoformat()}))
    assert owner_approval(tmp_path/"evaluation_results/qualification_closure","b"*64)["status"]=="INVALID"


def test_stale_registry_cache_cannot_authorize(mounted,tmp_path,monkeypatch):
    from evaluation import track_b_inputs
    path=state.mapped(tmp_path/"config/qualification/reviewer_registry.yaml");path.write_text("synthetic: true")
    projected={"identity_verified":True,"contract_sha256":track_b_inputs.digest(path)}
    monkeypatch.setattr(track_b_inputs,"registry_contract",lambda path:projected)
    state.mapped(tmp_path/"evaluation_results/qualification_closure/reviewer_registry.local.json").write_text(json.dumps({**projected,"contract_sha256":"old"}))
    assert current_registry(tmp_path)["contract_status"]=="STALE"


def fixture_manifest(mounted):
    source=mounted/"engineering"/"synthetic_source.txt";source.write_text("SOURCE ONLY SENTINEL")
    rows=[{"field_id":review.content_hash({"field_id":str(i)}),"scan_id":"opaque","page_id":"opaque",
           "field_name":"patient_name","source_path":str(source),"source_sha256":review.digest(source),"frame":0} for i in range(21)]
    manifest={"scope":review.SCOPE,"production_authority":False,"scans":12,"fields":rows,"saved_ocr_sha256":"a"*64}
    manifest["manifest_sha256"]=review.content_hash(manifest)
    state.immutable_json(review.directory()/"source_manifest.json",manifest)
    return manifest


def test_immutable_labels_and_truth(mounted):
    manifest=fixture_manifest(mounted)
    for row in manifest["fields"]:
        review.save_label(row["field_id"],{"state":"VALUE","value":"PRIVATE_SOURCE_SENTINEL",
            "source_region":[0,0,1,1],"source_only_attested":True},"synthetic-independent-reader")
    frozen=review.freeze()
    assert len(frozen["records"])==21 and frozen["production_authority"] is False
    with pytest.raises(ValueError,match="ALREADY_FROZEN"):
        review.save_label(manifest["fields"][0]["field_id"],{},"synthetic")
    with pytest.raises(ValueError,match="IMMUTABLE"):
        state.immutable_json(review.directory()/"engineering_truth.json",{"replacement":True})
    assert not list((mounted/"truth").iterdir())


def test_review_ui_never_prefills_prediction_or_label(mounted):
    from fastapi.testclient import TestClient

    from evaluation.engineering_review_app import create_app
    manifest=fixture_manifest(mounted)
    client=TestClient(create_app("synthetic-reviewer","synthetic-private-token"))
    client.post("/login",data={"token":"synthetic-private-token"})
    response=client.get('/field/'+manifest['fields'][0]['field_id'])
    assert response.status_code==200
    assert '<textarea name="value" autocomplete="off"></textarea>' in response.text
    assert 'SOURCE ONLY SENTINEL' not in response.text
    assert 'raw_value' not in response.text


def test_saved_ocr_hash_mismatch_fails_before_comparison(mounted,tmp_path):
    fixture_manifest(mounted)
    path=tmp_path/"saved";path.mkdir();(path/"raw_execution.local.json").write_text('{"private":"prediction"}')
    with pytest.raises(ValueError,match="SAVED_OCR_BINDING_CHANGED"): measure(path)


def test_report_commit_does_not_change_runtime_candidate(tmp_path):
    subprocess.run(["git","clone","--shared","--no-checkout","--single-branch",str(candidate.ROOT),str(tmp_path)],check=True,capture_output=True)
    subprocess.run(["git","checkout",candidate.CANDIDATE,"--","packages","workers","config",candidate.SEMANTIC],cwd=tmp_path,check=True,capture_output=True)
    candidate.create(tmp_path)
    note=tmp_path/"docs/qualification/synthetic_receipt.json";note.parent.mkdir(parents=True,exist_ok=True);note.write_text('{}')
    subprocess.run(["git","add","docs/qualification/synthetic_receipt.json"],cwd=tmp_path,check=True,capture_output=True)
    subprocess.run(["git","-c","user.name=Synthetic","-c","user.email=synthetic@example.invalid","commit","-m","Synthetic report only"],cwd=tmp_path,check=True,capture_output=True)
    result=candidate.readiness(tmp_path)
    assert result["status"]=="PASS" and result["runtime_candidate_sha"]==candidate.CANDIDATE
    assert result["control_plane_sha"]!=candidate.CANDIDATE


def test_measured_accuracy_is_value_free_and_does_not_modify_saved_ocr(mounted,tmp_path):
    from evaluation.engineering_review_intake import prepare
    source=mounted/"engineering"/"synthetic_image.tif"
    source.write_bytes(b"synthetic test source; not a real scan")
    source_hash=review.digest(source)
    raw={"claims":[]}; inputs={"claims":[]}
    for i in range(12):
        fields=[{"field_id":str(i)+"_"+str(j),"field_name":"patient_name","page_number":1,
                 "raw_value":"PRIVATE_PREDICTION_SENTINEL","normalized_value":"PRIVATE_PREDICTION_SENTINEL"}
                for j in range(2 if i<9 else 1)]
        raw["claims"].append({"claim_alias":str(i),"source_sha256":source_hash,"document_id":str(i),
             "pages":[{"page_number":1,"page_id":str(i)}],"fields":fields,
             "events":[{"topic":"claim.validated","envelope":{"payload":{"form_type":"UNSTRUCTURED"}}}]})
        inputs["claims"].append({"claim_alias":str(i),"source_path":str(source),"source_sha256":source_hash})
    saved=tmp_path/"saved";saved.mkdir()
    (saved/"raw_execution.local.json").write_text(json.dumps(raw))
    (saved/"execution_input.local.json").write_text(json.dumps(inputs))
    before=(saved/"raw_execution.local.json").read_bytes()
    prepare(saved)
    assert "PRIVATE_PREDICTION_SENTINEL" not in (review.directory()/"source_manifest.json").read_text()
    assert measure(saved)["status"]=="WAITING_FOR_SOURCE_ONLY_LABELS"
    for item in review.read_manifest()["fields"]:
        review.save_label(item["field_id"],{"state":"VALUE","value":"PRIVATE_SOURCE_SENTINEL",
            "source_region":[0,0,1,1],"source_only_attested":True},"synthetic-independent-reader")
    review.freeze()
    result=measure(saved)
    assert result["comparable_fields"]==21 and result["exact_accuracy"]==0
    assert "PRIVATE_PREDICTION_SENTINEL" not in json.dumps(result)
    assert "PRIVATE_SOURCE_SENTINEL" not in json.dumps(result)
    assert (saved/"raw_execution.local.json").read_bytes()==before
    assert result["saved_ocr_sha256_before"]==result["saved_ocr_sha256_after"]
    assert not list((mounted/"truth").iterdir())
    from evaluation.engineering_attribution import record as attribute
    for item in review.read_manifest()["fields"]:
        attribute(item["field_id"],"OCR_RECOGNITION_ERROR","synthetic-causal-reviewer","synthetic source-region review")
    attributed=measure(saved)
    assert attributed["recognition_errors"]==21
    assert attributed["localization_errors"]==0
    assert "PRIVATE_SOURCE_SENTINEL" not in json.dumps(attributed)


def test_external_track_b_truth_cannot_be_silently_replaced(mounted,tmp_path):
    from packages.real_data_evaluation.blind_workflow import content_digest
    from packages.real_data_evaluation.release_truth import freeze_truth
    path=state.mapped(tmp_path/"evaluation_results/qualification_closure/release_truth_manifest.local.json")
    original={"status":"FROZEN","records":[{"synthetic":"original"}]}
    original["truth_sha256"]=content_digest(original)
    freeze_truth(path,original)
    replacement={"status":"FROZEN","records":[{"synthetic":"replacement"}]}
    replacement["truth_sha256"]=content_digest(replacement)
    with pytest.raises(ValueError,match="FROZEN_TRUTH_CHANGED"): freeze_truth(path,replacement)
    assert json.loads(path.read_text())==original


def test_engineering_truth_cannot_masquerade_as_production_truth(mounted,tmp_path):
    from evaluation.qualification_closure import readiness
    from packages.real_data_evaluation.blind_workflow import content_digest
    fake={"status":"FROZEN","records":[{"synthetic":"engineering"}],"production_authority":False,"scope":review.SCOPE}
    fake["truth_sha256"]=content_digest(fake)
    path=state.mapped(tmp_path/"evaluation_results/qualification_closure/release_truth_manifest.local.json")
    path.write_text(json.dumps(fake))
    assert readiness(tmp_path)["inputs"]["release_truth_manifest.local.json"]["status"]=="INVALID"


def test_causal_review_cannot_precede_blind_source_truth(mounted):
    from evaluation.engineering_attribution import record
    manifest=fixture_manifest(mounted)
    with pytest.raises(ValueError,match="FREEZE_SOURCE_ONLY_TRUTH"):
        record(manifest["fields"][0]["field_id"],"OCR_RECOGNITION_ERROR","synthetic","synthetic evidence")
