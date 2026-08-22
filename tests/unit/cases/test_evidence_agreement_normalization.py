from packages.evidence.normalization import normalize_agreement_value


def test_name_punctuation_is_representation_only_for_agreement():
    assert normalize_agreement_value("patient_name", "| DOE, JANE _") == normalize_agreement_value(
        "patient_name", "DOE JANE",
    )


def test_money_decimal_is_not_stripped_into_false_agreement():
    assert normalize_agreement_value("total_charge", "10.00") != normalize_agreement_value(
        "total_charge", "1000",
    )


def test_compact_and_display_icd_are_equivalent_for_agreement():
    assert normalize_agreement_value("principal_diagnosis", "Z00.00") == normalize_agreement_value(
        "principal_diagnosis", "Z0000",
    )
