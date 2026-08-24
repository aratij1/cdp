from packages.evidence.name_agreement import (
    NAME_NORMALIZATION_VERSION,
    compare_patient_names,
    normalize_name_for_agreement,
)


def test_name_agreement_is_representation_only_and_preserves_token_order():
    punctuation = compare_patient_names(" O’NEIL, MARIA ", "O'NEIL MARIA")
    reversed_order = compare_patient_names("MARIA O'NEIL", "O'NEIL MARIA")

    assert punctuation.agrees
    assert punctuation.version == NAME_NORMALIZATION_VERSION
    assert not reversed_order.agrees


def test_configured_surname_first_handling_requires_explicit_form_semantics():
    default, _ = normalize_name_for_agreement("SMITH, MARIA")
    proven, tokens = normalize_name_for_agreement(
        "SMITH, MARIA", surname_first_proven=True
    )

    assert default == "SMITHMARIA"
    assert proven == "MARIASMITH"
    assert tokens == ("MARIA", "SMITH")


def test_label_contamination_and_disagreement_fail_closed():
    assert not compare_patient_names("PATIENT NAME MARIA SMITH", "MARIA SMITH").agrees
    assert not compare_patient_names("MARIA SMITH", "MARIA SMYTH").agrees
