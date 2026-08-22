from evaluation.generate_public_synthetic_claims import _fields, _render, _valid_npi
from packages.validation_rules.npi import is_valid_npi

def test_generated_npi_is_checksum_valid_but_fixture_is_marked_synthetic():
    assert is_valid_npi(_valid_npi(42))
    assert _fields("CMS1500", 42)["insured_id_number"].startswith("SYN")

def test_generated_families_have_truth_and_template_sized_images():
    cms, cms_truth, cms_crops = _render("CMS1500", 1, "clean_scan")
    ub, ub_truth, ub_crops = _render("UB04", 2, "fax")
    assert cms.size == (1712, 2214)
    assert ub.size == (1711, 2216)
    assert set(cms_crops) <= set(cms_truth)
    assert {"provider_npi", "type_of_bill", "principal_diagnosis"} <= set(ub_crops)
