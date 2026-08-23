from packages.document_taxonomy.taxonomy import DocumentClass
from .cms1500 import CMS1500Verifier
from .contracts import StandardFormVerification
from .evidence import StandardFormEvidence
from .ub04 import UB04Verifier


class StandardFormVerificationService:
    def __init__(self, cms_verifier=None, ub_verifier=None):
        self.cms_verifier = cms_verifier or CMS1500Verifier()
        self.ub_verifier = ub_verifier or UB04Verifier()

    def verify(self, evidence: StandardFormEvidence) -> StandardFormVerification:
        if evidence.candidate_family == DocumentClass.CMS1500:
            return self.cms_verifier.verify(evidence)
        if evidence.candidate_family == DocumentClass.UB04:
            return self.ub_verifier.verify(evidence)
        raise ValueError("only CMS1500 or UB04 may enter standard verification")
