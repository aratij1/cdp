from evaluation.phase8_12_tesseract_confirmation import _canonical, _engine_type


def test_canonical_uses_field_datatype_normalization():
    assert _canonical("DATE", "07/29/25") == "20250729"
    assert _canonical("NPI", "1396827531") == "1396827531"


def test_engine_type_selects_constrained_ocr_profiles():
    assert _engine_type("patient_dob", "DATE") == "date"
    assert _engine_type("provider_npi", "NPI") == "npi"
    assert _engine_type("total_charge", "CURRENCY") == "currency"
    assert _engine_type("provider_name", "PERSON_NAME") == "text"
