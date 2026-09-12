"""Value-free categorization of deterministic validator failures."""
CATEGORIES = ("FORMAT", "CHECKSUM", "DATE", "CODE SET", "CROSS-FIELD CONSISTENCY",
              "TOTAL RECONCILIATION", "MISSING REQUIRED VALUE", "FORM IDENTITY", "REFERENCE LOOKUP", "OTHER")


def classify_validation(reasons: list[str]) -> list[str]:
    result = set()
    for reason in reasons:
        if reason == "EMPTY_VALUE": category = "MISSING REQUIRED VALUE"
        elif reason == "CHECKSUM_FAILURE": category = "CHECKSUM"
        elif reason == "INVALID_DATE": category = "DATE"
        elif reason in {"CODE_NOT_IN_SET", "CODE_SET_UNAVAILABLE"}: category = "CODE SET"
        elif reason in {"CROSS_FIELD_MISMATCH", "DATE_RELATIONSHIP_INVALID"}: category = "CROSS-FIELD CONSISTENCY"
        elif reason in {"TOTAL_MISMATCH", "TOTAL_RECONCILIATION_REQUIRED"}: category = "TOTAL RECONCILIATION"
        elif reason in {"FORM_IDENTITY_REQUIRED", "FORM_IDENTITY_UNVERIFIED"}: category = "FORM IDENTITY"
        elif reason in {"REFERENCE_UNAVAILABLE", "REFERENCE_LOOKUP_REQUIRED"}: category = "REFERENCE LOOKUP"
        elif reason.startswith("INVALID_") or reason in {"LABEL_CONTAMINATION", "REGISTERED_FIELD_LABEL_AS_VALUE", "NEGATIVE_AMOUNT", "CHECKBOX_AMBIGUOUS"}: category = "FORMAT"
        else: category = "OTHER"
        result.add(category)
    return sorted(result or {"OTHER"})
