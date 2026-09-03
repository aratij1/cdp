from evaluation.phase8_13_p1_tuning import _semantic_candidate, _wilson_lower
from workers.standard_form_extraction.extractor import _valid_regional_organization


def test_provider_semantics_prefer_complete_organization_shape():
    selected = _semantic_candidate("provider_name", [
        {"raw_value": "NORTHSIDEMEDICAI", "raw_confidence": .85},
        {"raw_value": "ORCHARD MEDICAL GROUP 1016", "raw_confidence": .79},
    ])
    assert selected["qualified_value"] == "ORCHARD MEDICAL GROUP 1016"


def test_small_perfect_sample_cannot_qualify_critical_precision():
    assert _wilson_lower(42, 42) < .995


def test_provider_shape_requires_complete_name_and_terminal_site_id():
    assert not _valid_regional_organization("NORTHSIDEMEDICAI")
    assert _valid_regional_organization("ORCHARD MEDICAL GROUP 1016")
