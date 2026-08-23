from packages.document_taxonomy.taxonomy import DocumentClass
from .cms1500 import _result
from .evidence import StandardFormEvidence


class UB04Verifier:
    policy_version = "ub04-verifier-v1"

    def verify(self, evidence: StandardFormEvidence):
        if evidence.candidate_family != DocumentClass.UB04:
            raise ValueError("UB04Verifier requires a UB04 nomination")
        regions = evidence.region_layout_scores
        classes = {
            "PAGE_GEOMETRY": evidence.page_geometry_score >= .70,
            "INSTITUTIONAL_GRID": regions.get("institutional_grid", 0) >= .65,
            "BILL_AND_STATEMENT_REGIONS": min(regions.get("type_of_bill", 0), regions.get("statement_covers", 0)) >= .55,
            "PAYER_PROVIDER_RELATIONSHIP": regions.get("payer_provider", 0) >= .45,
            "REVENUE_SERVICE_REGION": regions.get("revenue_service", 0) >= .30,
            "HCPCS_CHARGE_RELATIONSHIP": evidence.service_grid_score >= .30,
            "DIAGNOSIS_REGION": regions.get("diagnosis", 0) >= .45,
            "REPEATING_INSTITUTIONAL_ROWS": evidence.repeating_row_score >= .45,
            "HIGH_VALUE_ANCHORS": evidence.high_value_anchor_score >= .55,
            "SPATIAL_RELATIONSHIPS": evidence.spatial_relationship_score >= .45,
            "TEMPLATE_REGISTRATION": (evidence.template_registration_score or 0) >= .70,
        }
        return _result(evidence, classes,
                       essential=("INSTITUTIONAL_GRID", "REVENUE_SERVICE_REGION", "SPATIAL_RELATIONSHIPS"),
                       policy=self.policy_version)
