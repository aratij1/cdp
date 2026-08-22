from packages.document_routing.eligibility import StandardEligibilityEvidence
from packages.document_routing.ml.contracts import MLRouteEvidence,FusedEligibilityEvidence
class EligibilityFusionService:
    def __init__(self,config:dict):self.config=config
    def fuse(self,deterministic:StandardEligibilityEvidence,ml:MLRouteEvidence)->FusedEligibilityEvidence:
      policy=self.config["families"][deterministic.family];support=[]
      if deterministic.structure_evidence>=policy["minimum_structure"]:support.append("STRUCTURAL")
      if deterministic.anchor_evidence>=policy["minimum_semantic"]:support.append("SEMANTIC")
      if deterministic.geometry_evidence>=policy["minimum_spatial"]:support.append("SPATIAL")
      if deterministic.service_table_evidence>=policy.get("minimum_service_table",2):support.append("SERVICE_TABLE")
      proposed=ml.probability>=policy["threshold"];assisted=proposed and len(set(support)&set(policy["support_classes"]))>=policy["minimum_support_classes"]
      eligible=deterministic.eligible or assisted
      return FusedEligibilityEvidence(family=deterministic.family,eligible=eligible,deterministic_eligible=deterministic.eligible,ml_proposed_eligible=proposed,probability=ml.probability,threshold=policy["threshold"],deterministic_support=support,reason_codes=["DETERMINISTIC_ELIGIBLE"] if deterministic.eligible else ["ML_WITH_DETERMINISTIC_CORROBORATION"] if assisted else ["INSUFFICIENT_CORROBORATION"])
