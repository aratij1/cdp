from __future__ import annotations

from packages.layout_intelligence.models import SchemaEvidence


SCHEMAS = {
    "INSTITUTIONAL_CLAIM_LIKE": {"type_of_bill", "revenue_code", "principal_diagnosis", "provider_npi"},
    "PROFESSIONAL_CLAIM_LIKE": {"insured_id_number", "patient_name", "provider_npi", "procedure_code", "total_charge"},
    "EOB": {"insured_id_number", "service_date", "total_charge"},
    "MEDICAL_INVOICE": {"patient_name", "provider_name", "total_charge"},
}


def infer_schema(fields: set[str], *, token_count: int) -> SchemaEvidence:
    ranked = sorted(((len(fields & expected) / len(expected), name, fields & expected)
                     for name, expected in SCHEMAS.items()), reverse=True)
    score, family, supporting = ranked[0]
    if score >= .45:
        return SchemaEvidence(schema_family=family, confidence=score,
                              supporting_fields=sorted(supporting),
                              reason_codes=["HEALTHCARE_LABEL_DENSITY_HIGH"])
    if token_count < 5:
        return SchemaEvidence(schema_family="NON_CLAIM", confidence=.9,
                              supporting_fields=[], reason_codes=["INSUFFICIENT_PAGE_CONTENT"])
    return SchemaEvidence(schema_family="UNKNOWN", confidence=max(.2, score),
                          supporting_fields=sorted(supporting),
                          reason_codes=["SCHEMA_EVIDENCE_INSUFFICIENT"])
