from packages.document_taxonomy.taxonomy import DocumentClass

from .contracts import StandardFormStatus, StandardFormVerification
from .evidence import StandardFormEvidence


class CMS1500Verifier:
    policy_version = "cms1500-verifier-v1"

    def verify(self, evidence: StandardFormEvidence) -> StandardFormVerification:
        if evidence.candidate_family != DocumentClass.CMS1500:
            raise ValueError("CMS1500Verifier requires a CMS1500 nomination")
        regions = evidence.region_layout_scores
        classes = {
            "PAGE_GEOMETRY": evidence.page_geometry_score >= .70,
            "PATIENT_INSURED_RELATIONSHIP": regions.get("patient_insured", 0) >= .55,
            "CLAIM_DIAGNOSIS_LAYOUT": min(regions.get("claim_information", 0), regions.get("diagnosis", 0)) >= .45,
            "SERVICE_LINE_GRID": evidence.service_grid_score >= .65,
            "PROVIDER_BILLING_LAYOUT": regions.get("provider_billing", 0) >= .45,
            "HIGH_VALUE_ANCHORS": evidence.high_value_anchor_score >= .55,
            "SPATIAL_RELATIONSHIPS": evidence.spatial_relationship_score >= .45,
            "TEMPLATE_REGISTRATION": (evidence.template_registration_score or 0) >= .70,
        }
        return _result(evidence, classes, essential=("SERVICE_LINE_GRID", "SPATIAL_RELATIONSHIPS"),
                       policy=self.policy_version)


def _result(evidence, classes, essential, policy):
    support = tuple(name for name, passed in classes.items() if passed)
    contradictions = tuple(evidence.contradiction_codes)
    verified = len(support) >= 3 and all(classes[name] for name in essential) and not contradictions
    status = StandardFormStatus.VERIFIED if verified else (
        StandardFormStatus.AMBIGUOUS if len(support) >= 2 and not contradictions else StandardFormStatus.NOT_VERIFIED)
    if evidence.candidate_family == DocumentClass.CMS1500:
        if verified:
            reasons = ("CMS_VERIFIED_IDENTITY",)
        elif any("UB" in code or "INSTITUTIONAL" in code for code in contradictions):
            reasons = ("CMS_UB_CONTRADICTION",)
        elif contradictions:
            reasons = ("CMS_LAYOUT_CONTRADICTION",)
        elif status == StandardFormStatus.AMBIGUOUS:
            reasons = ("CMS_AMBIGUOUS",)
        else:
            reasons = ("CMS_INSUFFICIENT_EVIDENCE",)
    else:
        if verified:
            reasons = ("UB_VERIFIED_IDENTITY",)
        elif any("CMS" in code for code in contradictions):
            reasons = ("UB_CMS_CONTRADICTION",)
        elif contradictions:
            reasons = ("UB_LAYOUT_CONTRADICTION",)
        elif status == StandardFormStatus.AMBIGUOUS:
            reasons = ("UB_AMBIGUOUS",)
        else:
            reasons = ("UB_INSUFFICIENT_EVIDENCE",)
    return StandardFormVerification(candidate_family=evidence.candidate_family, status=status,
        verification_score=len(support) / len(classes), supporting_evidence_classes=support,
        contradicting_evidence_classes=contradictions,
        reason_codes=reasons,
        template_version=evidence.template_version, verification_policy_version=policy,
        eligible_for_fixed_extractor=verified)
