"""Synthetic operational smoke; fixtures never enter production review evidence."""

import hashlib
import json
import re
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from packages.real_data_evaluation.blind_workflow import FIELDS, content_digest


@pytest.fixture
def isolated_ui(tmp_path, monkeypatch):
    from evaluation.annotation_app import qualification_review as ui
    from evaluation.reconstruct_source_bindings import rendered_hash

    data = tmp_path / "evaluation_results/qualification_closure"
    data.mkdir(parents=True)
    assets = tmp_path / "evaluation_data/source_b_1000_claims"
    assets.mkdir(parents=True)
    asset = assets / "synthetic.png"
    Image.new("RGB", (20, 20), "white").save(asset)
    with Image.open(asset) as page:
        digest = rendered_hash(page)
    rows = [
        {
            "page_id": f"synthetic-{i}",
            "package_id": "synthetic",
            "rendered_page_sha256": digest,
            "source_asset_path": str(asset),
            "source_asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            "frame_index": 0,
        }
        for i in range(2)
    ]
    (data / "blind_source_views.local.json").write_text(json.dumps(rows))
    registry = {
        "authorized_reviewers": ["synthetic-one", "synthetic-two"],
        "adjudicators": ["synthetic-third"],
        "identity_verified": True,
        "policy_id": "SYNTHETIC_TEST_ONLY",
    }
    (data / "reviewer_registry.local.json").write_text(json.dumps(registry))
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    monkeypatch.setattr(ui, "DATA", data)
    monkeypatch.setattr(ui, "SESSIONS", {})
    monkeypatch.setattr("evaluation.qualification_closure.refresh", lambda: None)
    app = FastAPI()
    app.include_router(ui.router)
    return ui, TestClient(app), rows


def login(client, name):
    response = client.post("/qualification-review/login", data={"reviewer": name})
    assert response.status_code == 200
    return {"X-Review-Session": client.cookies["qualification_session"]}


def annotation(value="SYNTHETIC"):
    return {
        "fields": {f: {"state": "VALUE", "value": value, "region": [0, 0, 1, 1]} for f in FIELDS},
        "form": "CMS1500",
        "quality": "GOOD",
        "boundary": "START_CLAIM",
        "prediction_visible": False,
    }


def test_source_smoke_has_no_database_access_and_detects_changed_source(isolated_ui):
    from evaluation.qualification_review_smoke import run_source_smoke

    ui, _, rows = isolated_ui
    report = run_source_smoke(ui.DATA, expected_pages=2)
    assert report["status"] == "PASS"
    assert report["png_pages_decoded_and_bound"] == 2
    assert not (ui.DATA / "blind_reviews.sqlite3").exists()
    from pathlib import Path

    Path(rows[0]["source_asset_path"]).write_bytes(b"changed synthetic source")
    report = run_source_smoke(ui.DATA, expected_pages=2)
    assert report["status"] == "FAIL"
    assert len(report["failures"]) == 2


def test_identity_draft_resume_save_next_progress_second_review_adjudication(isolated_ui):
    ui, client, _rows = isolated_ui
    for route in ["page/0", "image/0", "draft/0", "progress", "second-review-queue"]:
        assert client.get("/qualification-review/" + route).status_code == 401
    assert client.post("/qualification-review/login", data={"reviewer": ""}).status_code == 400
    headers = login(client, "synthetic-one")
    payload = {"annotation": annotation(), "complete": False}
    assert client.post("/qualification-review/draft/0", json=payload).status_code == 403
    assert (
        client.post("/qualification-review/draft/0", headers=headers, json=payload).status_code
        == 200
    )
    login(client, "synthetic-one")
    assert client.get("/qualification-review/draft/0").json()["annotation"] == payload["annotation"]
    headers = {"X-Review-Session": client.cookies["qualification_session"]}
    payload["complete"] = True
    assert (
        client.post("/qualification-review/draft/0", headers=headers, json=payload).status_code
        == 200
    )
    response = client.post(
        "/qualification-review/login", data={"reviewer": "synthetic-one"}, follow_redirects=False
    )
    assert response.headers["location"].endswith("/page/1")
    assert client.get("/qualification-review/progress").json()["pages_reviewed"] == 1
    headers = login(client, "synthetic-two")
    queue = client.get("/qualification-review/second-review-queue")
    assert queue.status_code == 200 and "/page/0" in queue.text
    assert "SYNTHETIC" not in queue.text
    assert client.get("/qualification-review/draft/0").json()["annotation"] == {}
    payload["annotation"]["fields"][FIELDS[0]]["value"] = "DISAGREEMENT_SYNTHETIC"
    assert (
        client.post("/qualification-review/draft/0", headers=headers, json=payload).status_code
        == 200
    )
    headers = login(client, "synthetic-third")
    assert "/adjudication/0" in client.get("/qualification-review/adjudication-queue").text
    assert client.get("/qualification-review/adjudication/0").status_code == 200
    reviews = ui.store().completed()
    response = client.post(
        "/qualification-review/adjudication/0",
        headers=headers,
        json={
            "field_name": FIELDS[0],
            "conclusion": annotation()["fields"][FIELDS[0]],
            "review_digest": content_digest(reviews),
        },
    )
    assert response.status_code == 200
    assert "/adjudication/0" not in client.get("/qualification-review/adjudication-queue").text
    assert client.get("/qualification-review/progress").json()["adjudications"] == 1


def test_keyboard_autosave_resume_and_save_next_in_node_dom(isolated_ui, tmp_path):
    """Execute shipped JS against mocked DOM/network; not a browser render test."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; synthetic JS interaction smoke not run")
    _, client, _ = isolated_ui
    login(client, "synthetic-one")
    markup = client.get("/qualification-review/page/0").text
    script = re.search(r"<script>(.*?)</script>", markup, re.DOTALL).group(1)
    harness = r"""
const assert=require('assert'),vm=require('vm');
(async()=>{
const ids=['field','value','state','form','quality','boundary','page','crop','nextField','complete','progress','status'];
const elements=Object.fromEntries(ids.map(id=>[id,{value:'',selectedIndex:0,textContent:'',focus(){},click(){return this.onclick()},getContext(){return {clearRect(){},drawImage(){},strokeRect(){}}}}]));
const names=FIELDS_JSON;elements.field.options=names.map(value=>({value}));
Object.defineProperty(elements.field,'value',{get(){return names[this.selectedIndex]}});
let saves=[],scheduled=null;
const restored={fields:{[names[0]]:{state:'VALUE',value:'RESTORED_SYNTHETIC',region:[0,0,1,1]}},form:'CMS1500',quality:'GOOD',boundary:'START_CLAIM',prediction_visible:false};
const progress={pages_reviewed:0,pages_total:2,fields_reviewed:0,critical_fields_dual_reviewed:0,agreements:0,disagreements:0,adjudications:0,trusted_labels:0};
const document={cookie:'qualification_session=synthetic-token',getElementById:id=>elements[id],querySelector:()=>elements.field,querySelectorAll:()=>[]};
const location={href:''};
const context={document,location,window:{},Image:class{},console,Promise,setTimeout:f=>(scheduled=f,1),clearTimeout:()=>{},fetch:async(url,opts)=>{
if(opts){saves.push(JSON.parse(opts.body));return {ok:true,json:async()=>({saved:true,progress})}}
return {ok:true,json:async()=>url.includes('/draft/')?{annotation:restored,complete:false}:progress}
}};
vm.createContext(context);vm.runInContext(SCRIPT_JSON,context);
await new Promise(setImmediate);
assert.equal(elements.value.value,'RESTORED_SYNTHETIC');
assert.equal(saves.length,0);
elements.value.value='TYPED_SYNTHETIC';elements.value.oninput();assert(scheduled);await scheduled();await new Promise(setImmediate);
assert.equal(saves.at(-1).annotation.fields[names[0]].value,'TYPED_SYNTHETIC');
let prevented=false;document.onkeydown({altKey:true,key:'n',preventDefault(){prevented=true}});await new Promise(setImmediate);
assert(prevented);assert.equal(elements.field.selectedIndex,1);
document.onkeydown({ctrlKey:true,key:'Enter',preventDefault(){}});await new Promise(setImmediate);
assert.equal(saves.at(-1).complete,true);assert.equal(location.href,'/qualification-review/page/1');
console.log('PASS: synthetic DOM keyboard/autosave/resume/save-next');
})().catch(e=>{console.error(e);process.exit(1)});
""".replace("FIELDS_JSON", json.dumps(list(FIELDS))).replace("SCRIPT_JSON", json.dumps(script))
    path = tmp_path / "synthetic-ui-smoke.cjs"
    path.write_text(harness)
    result = subprocess.run(
        [node, str(path)], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
