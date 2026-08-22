"""Trusted-label eligibility and tamper-evident append-only export."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from pydantic import Field

from packages.criticality import CriticalityLevel
from packages.domain.common import DomainModel, utcnow


class TrustedLabelRequest(DomainModel):
    task_id: str
    tenant_id: str
    document_id: str
    document_family: str
    field_name: str
    criticality: CriticalityLevel
    crop_reference: str
    crop_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    previous_value: str | None = None
    corrected_value: str
    reviewer: str
    approver: str
    validator: str
    correction_reason: str
    deterministic_validation_passed: bool
    claim_revalidated: bool
    evidence_visible: bool
    crop_quality_approved: bool
    source_policy_version: str
    route_id: str | None = None
    route_status: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    evidence_bundle: dict = Field(default_factory=dict)
    system_decision: str | None = None
    human_decision: str | None = None
    review_duration_seconds: float | None = Field(default=None, ge=0)
    holdout_member: bool = False
    eligible_for_automatic_retraining: bool = False


class TrustedLabelDecision(DomainModel):
    eligible: bool
    reason_codes: list[str]


def evaluate_trusted_label(request: TrustedLabelRequest) -> TrustedLabelDecision:
    reasons: list[str] = []
    if request.reviewer == request.approver:
        reasons.append("INDEPENDENT_APPROVER_REQUIRED")
    if not request.deterministic_validation_passed:
        reasons.append("DETERMINISTIC_VALIDATION_REQUIRED")
    if not request.claim_revalidated:
        reasons.append("CLAIM_REVALIDATION_REQUIRED")
    if not request.evidence_visible:
        reasons.append("VISIBLE_CROP_EVIDENCE_REQUIRED")
    if not request.crop_quality_approved:
        reasons.append("CROP_QUALITY_NOT_APPROVED")
    if not request.corrected_value.strip():
        reasons.append("EMPTY_CORRECTION")
    if request.holdout_member:
        reasons.append("HOLDOUT_FEEDBACK_EXCLUDED")
    if request.eligible_for_automatic_retraining:
        reasons.append("AUTOMATIC_PRODUCTION_RETUNING_PROHIBITED")
    return TrustedLabelDecision(eligible=not reasons, reason_codes=reasons)


class TrustedLabelExporter:
    """JSONL hash chain makes deletion/reordering/modification detectable."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _last_hash(self) -> str:
        if not self.path.is_file():
            return "0" * 64
        lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        return json.loads(lines[-1])["event_hash"] if lines else "0" * 64

    def append(self, request: TrustedLabelRequest) -> dict:
        decision = evaluate_trusted_label(request)
        if not decision.eligible:
            raise ValueError("label is not trusted: " + ",".join(decision.reason_codes))
        payload = {
            **request.model_dump(mode="json"),
            "approved_at": utcnow().isoformat(),
            "previous_event_hash": self._last_hash(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload["event_hash"] = sha256(canonical.encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def verify_chain(self) -> bool:
        previous = "0" * 64
        if not self.path.is_file():
            return True
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            payload = json.loads(line)
            event_hash = payload.pop("event_hash")
            if payload.get("previous_event_hash") != previous:
                return False
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if sha256(canonical.encode()).hexdigest() != event_hash:
                return False
            previous = event_hash
        return True
