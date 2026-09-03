from evaluation.apply_crop_quality_ocr_tuning import _hard_valid


def test_hcpcs_hipps_requires_reference_even_with_cross_family_agreement():
    assert not _hard_valid("N251", "code", "hcpcs_rate_hipps_code")
    assert not _hard_valid("0251", "code", "hcpcs_rate_hipps_code")


def test_other_hard_validated_routes_remain_eligible():
    assert _hard_valid("83036", "code", "cpt_code")
    assert _hard_valid("89.20", "currency", "charge")
