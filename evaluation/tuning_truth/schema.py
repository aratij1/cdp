CMS_FIELDS = (
    "member_id", "patient_name", "patient_dob", "insured_name", "provider_name",
    "provider_npi", "service_date", "cpt_hcpcs", "diagnosis", "total_charge",
    "relationship", "patient_address",
)

UB_FIELDS = (
    "member_id", "patient_name", "patient_dob", "provider_name", "provider_npi",
    "type_of_bill", "principal_diagnosis", "revenue_code", "hcpcs", "service_date",
    "units", "line_charge", "total_charge",
)

CUSTOM_FIELDS = (
    "member_id", "patient_name", "patient_dob", "provider_name", "provider_npi",
    "service_date", "diagnosis", "total_charge",
)

FIELDS_BY_FAMILY = {
    "CMS1500": CMS_FIELDS,
    "UB04": UB_FIELDS,
    "CUSTOM_PROFESSIONAL": CUSTOM_FIELDS,
    "CUSTOM_INSTITUTIONAL": CUSTOM_FIELDS,
}

CRITICAL_FIELDS = {
    "member_id", "patient_name", "patient_dob", "provider_npi", "service_date",
    "cpt_hcpcs", "hcpcs", "diagnosis", "principal_diagnosis", "revenue_code",
    "line_charge", "total_charge", "type_of_bill",
}


def field_policy(field_name: str) -> tuple[bool, str, bool]:
    critical = field_name in CRITICAL_FIELDS
    return critical, "CRITICAL" if critical else "HIGH", critical
