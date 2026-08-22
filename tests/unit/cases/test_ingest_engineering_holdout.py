from evaluation.ingest_engineering_holdout import _canonical_fields, _form_type


def test_engineering_holdout_maps_only_governed_frontier_fields():
    cms = _canonical_fields("CMS1500_LIKE", {
        "patient_name": "JANE DOE", "dob": "01/02/1980",
        "member_id": "M-1", "total_charge": "10.00", "diagnosis": "I10",
    })
    ub = _canonical_fields("UB04_LIKE", {
        "patient_name": "JANE DOE", "dob": "01/02/1980",
        "provider_npi": "1234567893", "type_of_bill": "0111",
        "principal_diagnosis": "I10", "total_charge": "10.00",
    })

    assert [field.field_name for field in cms] == [
        "patient_name", "patient_dob", "insured_id_number", "total_charge",
    ]
    assert [field.field_name for field in ub] == [
        "patient_name", "patient_dob", "provider_npi", "type_of_bill",
        "principal_diagnosis",
    ]
    assert _form_type("CMS1500_LIKE_EDGE") == "CMS1500"
    assert _form_type("ATTACHMENT") == "UNSTRUCTURED"
