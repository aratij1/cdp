"""Adversarial synthetic join tests; no source scans or patient values."""
from copy import deepcopy

import pytest

from evaluation.engineering_accuracy import verify_bindings
from evaluation.engineering_review import content_hash


def cohort():
    field = {"field_id":"synthetic-field", "field_name":"patient_name", "page_number":1,
             "document_id":"synthetic-doc", "raw_value":"SYNTHETIC NAME", "normalized_value":None}
    item = {"field_id":content_hash({"field_id":field["field_id"]}),
            "scan_id":content_hash({"document_id":"synthetic-doc"}),
            "page_id":content_hash({"page_id":"synthetic-page"}),
            "field_name":"patient_name", "source_sha256":"a"*64,"frame":0}
    label = {**item,"state":"VALUE","value":"SYNTHETIC NAME"}
    claim = {"claim_alias":"synthetic-claim", "document_id":"synthetic-doc", "source_sha256":"a"*64,
             "pages":[{"page_id":"synthetic-page","page_number":1,"document_id":"synthetic-doc"}],
             "fields":[field],"events":[{"topic":"claim.validated","envelope":{"payload":{"form_type":"CMS1500"}}}]}
    return {"fields":[item]}, [label], {"claims":[claim]}


def test_complete_binding_with_optional_null_normalized():
    verify_bindings(*cohort())


@pytest.mark.parametrize("target,code", [("manifest","MANIFEST_FIELD_ID"),("truth","TRUTH_FIELD_ID"),
    ("raw","RAW_FIELD_ID"),("claim","CLAIM_ALIAS"),("page","PAGE_NUMBER")])
def test_duplicate_ids_fail(target,code):
    m,t,r=cohort(); c=r["claims"][0]
    rows={"manifest":m["fields"],"truth":t,"raw":c["fields"],"claim":r["claims"],"page":c["pages"]}[target]
    rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError,match="DUPLICATE_"+code): verify_bindings(m,t,r)


@pytest.mark.parametrize("side",["manifest","truth","raw"])
def test_exact_field_set_required(side):
    m,t,r=cohort()
    {"manifest":m["fields"],"truth":t,"raw":r["claims"][0]["fields"]}[side].clear()
    with pytest.raises(ValueError,match="FIELD_SET_MISMATCH"): verify_bindings(m,t,r)


@pytest.mark.parametrize("side",["manifest","truth"])
@pytest.mark.parametrize("key",["scan_id","page_id","field_name","source_sha256"])
def test_all_metadata_must_agree(side,key):
    m,t,r=cohort(); row=m["fields"][0] if side=="manifest" else t[0]
    row[key]="wrong-synthetic-identity"
    with pytest.raises(ValueError,match="BINDING_MISMATCH_"+key.upper()): verify_bindings(m,t,r)


@pytest.mark.parametrize("target,key",[("claim","document_id"),("claim","source_sha256"),
    ("page","page_id"),("page","page_number"),("field","field_id"),("field","page_number"),
    ("field","field_name"),("field","raw_value"),("field","document_id"),("page","document_id")])
def test_missing_raw_identity_or_value(target,key):
    m,t,r=cohort(); c=r["claims"][0]
    {"claim":c,"page":c["pages"][0],"field":c["fields"][0]}[target].pop(key)
    with pytest.raises(ValueError): verify_bindings(m,t,r)


@pytest.mark.parametrize("key,value",[("raw_value",None),("raw_value",123),("raw_value",[]),
    ("normalized_value",123),("normalized_value",{}),("page_number",True)])
def test_wrong_raw_value_types_fail(key,value):
    m,t,r=cohort(); r["claims"][0]["fields"][0][key]=value
    with pytest.raises(ValueError): verify_bindings(m,t,r)


@pytest.mark.parametrize("value",[None,"",123])
def test_validated_form_type_required(value):
    m,t,r=cohort(); r["claims"][0]["events"][0]["envelope"]["payload"]["form_type"]=value
    with pytest.raises(ValueError,match="MISSING_VALIDATED_FORM_TYPE"): verify_bindings(m,t,r)


def test_validation_event_required():
    m,t,r=cohort(); r["claims"][0]["events"]=[]
    with pytest.raises(ValueError,match="MISSING_VALIDATED_FORM_TYPE"): verify_bindings(m,t,r)


@pytest.mark.parametrize("target",["page","field"])
def test_document_identity_mismatch(target):
    m,t,r=cohort(); c=r["claims"][0]
    c["pages" if target=="page" else "fields"][0]["document_id"]="wrong"
    with pytest.raises(ValueError,match="DOCUMENT_MISMATCH"): verify_bindings(m,t,r)


def test_frame_mismatch():
    m,t,r=cohort(); m["fields"][0]["frame"]=1
    with pytest.raises(ValueError,match="BINDING_MISMATCH_FRAME"): verify_bindings(m,t,r)


def test_error_does_not_expose_value():
    m,t,r=cohort(); r["claims"][0]["fields"][0]["raw_value"]={"secret":"SYNTHETIC PRIVATE SENTINEL"}
    with pytest.raises(ValueError) as error: verify_bindings(m,t,r)
    assert "SENTINEL" not in str(error.value)
