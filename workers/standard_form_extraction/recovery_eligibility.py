"""Field-aware eligibility for bounded OCR recovery."""
from __future__ import annotations

import re
from dataclasses import dataclass

from packages.domain.extraction import FieldEvidence
from packages.field_normalization import normalize
from packages.local_evidence_cascade import decide_local_candidate
from packages.validation_rules.npi import is_valid_npi


@dataclass(frozen=True)
class RecoveryAssessment:
    eligible: bool
    reasons: tuple[str, ...]
_LABELS = {"patient_name":{"PATIENT","PATIENTS","NAME"},"insured_name":{"INSURED","NAME"},"provider_name":{"SIGNED","DATE","PROVIDER","SUPPLIER"},"patient_dob":{"PATIENT","BIRTH","DATE"},"insured_id_number":{"INSURED","ID","NUMBER"},"federal_tax_no":{"FEDERAL","TAX","ID","NUMBER","NPI"},"principal_diagnosis":{"DIAGNOSIS","ICD","IND"},"total_charge":{"TOTAL","CHARGE"}}
def assess_raw(field_name: str, field_type: str, raw_text: str, *, tokens=(), bounding_box=None) -> RecoveryAssessment:
    raw = raw_text.strip(); reasons=[]
    if not raw: reasons.append("OCR_EMPTY")
    labels=_LABELS.get(field_name,set()); raw_words=set(re.findall(r"[A-Z]+",raw.upper()))
    token_text=[str(token.get("text","")).strip().upper() for token in tokens]
    if labels and (any(token in labels for token in token_text) or bool(raw_words & labels)): reasons.append("LABEL_CONTAMINATION")
    if field_type == "text" and raw.endswith(","): reasons.append("TRUNCATED_TEXT")
    _normalized, parseable=normalize(field_type,raw)
    if raw and not parseable: reasons.append("NORMALIZATION_FAILED")
    if field_name == "principal_diagnosis" and raw and not decide_local_candidate(raw, "ICD_CODE").accepted:
        reasons.append("ICD_STRUCTURE_INVALID")
    amount = r"\$?\s*(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?"
    if field_type == "currency" and raw and not re.fullmatch(rf"(?:-?{amount}|\({amount}\))", raw):
        reasons.append("CURRENCY_STRUCTURE_INVALID")
    if field_type == "npi":
        digits=re.sub(r"\D","",raw)
        if len(digits)==10 and not is_valid_npi(digits): reasons.append("CHECKSUM_INVALID")
    if bounding_box and len(tokens)>1:
        for token in tokens:
            token_box=token.get("bounding_box")
            if isinstance(token_box,dict) and (float(token_box.get("x1",0))>=bounding_box.x1-1 or float(token_box.get("y1",0))>=bounding_box.y1-1):
                reasons.append("TOKEN_TOUCHES_CROP_EDGE"); break
    return RecoveryAssessment(bool(reasons),tuple(dict.fromkeys(reasons)))
def assess_recovery(field_name: str, field_type: str, evidence: FieldEvidence) -> RecoveryAssessment:
    return assess_raw(field_name,field_type,evidence.raw_text,tokens=evidence.tokens,bounding_box=evidence.bounding_box)